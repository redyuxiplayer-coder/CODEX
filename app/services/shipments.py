import json
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from pathlib import Path

from app.models import AuditLog, OrderLine, SalesOrder, ShipmentLine, ShipmentPhoto, ShipmentReport, User
from app.services.aliases import canonical_item
from app.services.ledger import recompute_for_report, recompute_order_ledger
from app.services.order_archives import get_open_archive, worker_visible_balances
from app.services.orders import get_order_balances
from app.services.quantities import parse_quantity

APPROVED_STATUSES = {"auto_approved", "approved_after_edit"}


def resolve_order_line_id(
    session: Session,
    company_name: str,
    product_name: str,
    style_name: str,
    size: str,
    preferred: int | None = None,
) -> int | None:
    """Return an order_line_id for a shipment line.

    Keeps the preferred binding when it is still valid, otherwise picks the
    first matching order line that still has unshipped quantity.
    """
    clean_size = str(size or "").strip()
    if preferred:
        order = session.get(OrderLine, int(preferred))
        if (
            order is not None
            and order.is_active
            and str(order.size or "").strip() == clean_size
            and (not order.order_id or get_open_archive(session, order.order_id) is None)
        ):
            return int(preferred)
    for row in worker_visible_balances(session, company_name=company_name):
        if (
            row["product"] == product_name
            and row["style"] == style_name
            and row["size"] == clean_size
            and int(row["remaining"]) > 0
        ):
            return int(row["order_id"])
    return None


def _resolve_lines_with_binding(
    session: Session,
    report: ShipmentReport,
    replacement_lines: list[dict],
) -> list[dict]:
    existing_by_size: dict[str, int | None] = {}
    for line in report.lines:
        existing_by_size.setdefault(line.size, line.order_line_id)
    cleaned = []
    for line in replacement_lines:
        size = str(line.get("size", "")).strip()
        quantity = parse_quantity(line.get("quantity"))
        if not size or quantity <= 0:
            continue
        order_line_id = line.get("order_line_id")
        if order_line_id:
            try:
                order_line_id = int(order_line_id)
            except (TypeError, ValueError):
                order_line_id = None
        if not order_line_id:
            order_line_id = existing_by_size.get(size)
        if not order_line_id:
            order_line_id = resolve_order_line_id(
                session,
                report.company_name,
                report.product_name,
                report.style_name,
                size,
            )
        cleaned.append({"size": size, "quantity": quantity, "order_line_id": order_line_id})
    return cleaned


def _balance_map(session: Session, company_name: str) -> dict[tuple[str, str, str], dict]:
    balances: dict[tuple[str, str, str], dict] = {}
    for row in get_order_balances(session, company_name=company_name):
        key = (row["product"], row["style"], row["size"])
        current = balances.setdefault(key, {"ordered": 0, "shipped": 0, "remaining": 0, "over_shipped": 0})
        current["ordered"] += int(row["ordered"])
        current["shipped"] += int(row["shipped"])
        current["remaining"] += int(row["remaining"])
        current["over_shipped"] += int(row["over_shipped"])
    return balances


def _review_reasons(session: Session, user_id: int, company_name: str, product_name: str, style_name: str, lines: list[dict]) -> list[str]:
    balances = _balance_map(session, company_name)
    reasons = []
    for line in lines:
        size = str(line["size"]).strip()
        quantity = int(line["quantity"])
        order_line_id = line.get("order_line_id")
        if order_line_id:
            order = session.get(OrderLine, int(order_line_id))
            balance = next((row for row in get_order_balances(session, company_name=company_name) if row["order_id"] == int(order_line_id)), None)
            if order is None or balance is None:
                reasons.append(f"{size} 无对应订单")
            elif quantity > int(balance["remaining"]):
                reasons.append(f"{size} 可能超发 {quantity - int(balance['remaining'])} 件")
            continue
        key = (product_name, style_name, size)
        balance = balances.get(key)
        if not balance:
            reasons.append(f"{size} 无对应订单")
            continue
        if quantity > int(balance["remaining"]):
            reasons.append(f"{size} 可能超发 {quantity - int(balance['remaining'])} 件")

    cutoff = datetime.now() - timedelta(minutes=10)
    for line in lines:
        duplicate = (
            session.query(ShipmentReport)
            .join(ShipmentLine, ShipmentLine.report_id == ShipmentReport.id)
            .filter(
                ShipmentReport.user_id == user_id,
                ShipmentReport.company_name == company_name,
                ShipmentReport.product_name == product_name,
                ShipmentReport.style_name == style_name,
                ShipmentLine.size == str(line["size"]).strip(),
                ShipmentLine.quantity == int(line["quantity"]),
                ShipmentReport.created_at >= cutoff,
            )
            .first()
        )
        if duplicate:
            reasons.append(f"{line['size']} 疑似重复上报")
    return reasons


def submit_shipment_report(
    session: Session,
    user_id: int,
    ship_date: str,
    company_name: str,
    product_name: str,
    style_name: str,
    lines: list[dict],
    photo_paths: list[str] | None = None,
    note: str = "",
    waybill_no: str = "",
    order_id: int | None = None,
) -> ShipmentReport:
    cleaned_lines = [
        {
            "size": str(line["size"]).strip(),
            "quantity": parse_quantity(line["quantity"]),
            "order_line_id": int(line["order_line_id"]) if line.get("order_line_id") else None,
        }
        for line in lines
        if str(line.get("size", "")).strip() and parse_quantity(line.get("quantity")) > 0
    ]
    selected_order = session.get(SalesOrder, int(order_id)) if order_id else None
    if order_id and selected_order is None:
        raise ValueError("所选订单不存在")
    if selected_order is not None:
        if get_open_archive(session, selected_order.id):
            raise ValueError("订单已归档，请先恢复")
        if selected_order.status != "active":
            raise ValueError("所选订单已停用")
        for line in cleaned_lines:
            bound_line = session.get(OrderLine, line.get("order_line_id")) if line.get("order_line_id") else None
            if bound_line is None or bound_line.order_id != selected_order.id or bound_line.size != line["size"]:
                raise ValueError("发货尺码不属于所选订单")
        company_name = selected_order.company.name
        canonical_product = selected_order.product_name
        canonical_style = selected_order.style_name
    else:
        for line in cleaned_lines:
            bound_line = session.get(OrderLine, line.get("order_line_id")) if line.get("order_line_id") else None
            if bound_line and bound_line.order_id and get_open_archive(session, bound_line.order_id):
                raise ValueError("订单已归档，请先恢复")
        canonical_product, canonical_style = canonical_item(session, company_name, product_name, style_name)
    reasons = _review_reasons(session, user_id, company_name, canonical_product, canonical_style, cleaned_lines)
    user = session.get(User, user_id)
    if user and user.role == "worker":
        reasons.insert(0, "员工上报，等待老板审核")
    status = "pending_review" if reasons else "auto_approved"
    report = ShipmentReport(
        user_id=user_id,
        order_id=selected_order.id if selected_order else None,
        ship_date=ship_date,
        company_name=company_name,
        product_name=canonical_product,
        style_name=canonical_style,
        waybill_no=str(waybill_no or "").strip(),
        note=note,
        status=status,
        review_reason="；".join(reasons),
    )
    session.add(report)
    session.flush()
    for line in cleaned_lines:
        session.add(
            ShipmentLine(
                report_id=report.id,
                order_line_id=line.get("order_line_id"),
                size=line["size"],
                quantity=line["quantity"],
            )
        )
    for path in photo_paths or []:
        session.add(ShipmentPhoto(report_id=report.id, file_path=path, original_name=Path(path).name))
    session.commit()
    session.refresh(report)
    recompute_for_report(session, report.id)
    return report


def approve_report(session: Session, report_id: int, admin_id: int, note: str = "") -> ShipmentReport:
    report = session.get(ShipmentReport, report_id)
    before = report.status
    report.status = "approved_after_edit"
    if note:
        report.review_reason = note
    session.add(AuditLog(report_id=report.id, admin_id=admin_id, action="approve", before_text=before, after_text=report.status, note=note))
    session.commit()
    session.refresh(report)
    recompute_for_report(session, report.id)
    return report


def reject_report(session: Session, report_id: int, admin_id: int, note: str = "") -> ShipmentReport:
    report = session.get(ShipmentReport, report_id)
    before = report.status
    report.status = "rejected"
    if note:
        report.review_reason = note
    session.add(AuditLog(report_id=report.id, admin_id=admin_id, action="reject", before_text=before, after_text=report.status, note=note))
    session.commit()
    session.refresh(report)
    recompute_for_report(session, report.id)
    return report


def edit_and_approve_report(session: Session, report_id: int, admin_id: int, replacement_lines: list[dict], note: str = "") -> ShipmentReport:
    report = session.get(ShipmentReport, report_id)
    before = json.dumps([{"size": line.size, "quantity": line.quantity} for line in report.lines], ensure_ascii=False)
    cleaned_lines = _resolve_lines_with_binding(session, report, replacement_lines)
    for line in list(report.lines):
        session.delete(line)
    session.flush()
    for line in cleaned_lines:
        session.add(
            ShipmentLine(
                report_id=report.id,
                order_line_id=line["order_line_id"],
                size=line["size"],
                quantity=line["quantity"],
            )
        )
    report.status = "approved_after_edit"
    report.review_reason = ""
    after = json.dumps(cleaned_lines, ensure_ascii=False)
    session.add(AuditLog(report_id=report.id, admin_id=admin_id, action="edit_approve", before_text=before, after_text=after, note=note))
    session.commit()
    session.refresh(report)
    recompute_for_report(session, report.id)
    return report


def _get_own_pending_report(session: Session, report_id: int, user_id: int) -> ShipmentReport:
    report = session.get(ShipmentReport, report_id)
    if report is None or report.user_id != user_id:
        raise ValueError("不能修改这条记录")
    if report.status != "pending_review":
        raise ValueError("只能修改待审核记录")
    return report


def update_own_pending_report(session: Session, report_id: int, user_id: int, replacement_lines: list[dict], note: str = "") -> ShipmentReport:
    report = _get_own_pending_report(session, report_id, user_id)
    cleaned_lines = _resolve_lines_with_binding(session, report, replacement_lines)
    for line in list(report.lines):
        session.delete(line)
    session.flush()
    for line in cleaned_lines:
        session.add(
            ShipmentLine(
                report_id=report.id,
                order_line_id=line["order_line_id"],
                size=line["size"],
                quantity=line["quantity"],
            )
        )
    report.note = note
    report.review_reason = "员工已修改，等待老板审核"
    session.commit()
    session.refresh(report)
    recompute_for_report(session, report.id)
    return report


def delete_own_pending_report(session: Session, report_id: int, user_id: int) -> None:
    report = _get_own_pending_report(session, report_id, user_id)
    order_line_ids = {int(line.order_line_id) for line in report.lines if line.order_line_id}
    session.delete(report)
    session.commit()
    for order_line_id in order_line_ids:
        recompute_order_ledger(session, order_line_id)
