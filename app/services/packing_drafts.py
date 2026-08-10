from pathlib import Path

from app.models import OrderLine, PackingDraft, PackingDraftLine, PackingDraftPhoto, SalesOrder
from app.services.order_archives import get_open_archive
from app.services.quantities import parse_quantity
from app.services.shipments import submit_shipment_report


def _next_package_no(session, pack_date: str) -> str:
    count = session.query(PackingDraft).filter_by(pack_date=pack_date).count()
    compact = str(pack_date or "").replace("-", "")
    return f"PKG-{compact}-{count + 1:03d}"


def _clean_lines(lines: list[dict]) -> list[dict]:
    cleaned = []
    for line in lines:
        size = str(line.get("size", "")).strip()
        quantity = parse_quantity(line.get("quantity"))
        order_line_id = line.get("order_line_id") or None
        if size and quantity > 0:
            cleaned.append({"size": size, "quantity": quantity, "order_line_id": int(order_line_id) if order_line_id else None})
    return cleaned


def _validate_formal_order_lines(session, order: SalesOrder, lines: list[dict]) -> None:
    for line in lines:
        order_line = session.get(OrderLine, line.get("order_line_id")) if line.get("order_line_id") else None
        if order_line is None or order_line.order_id != order.id or order_line.size != line["size"]:
            raise ValueError("包货尺码不属于所选订单")


def create_packing_draft(
    session,
    user_id: int,
    pack_date: str,
    company_name: str,
    product_name: str,
    style_name: str,
    lines: list[dict],
    note: str = "",
    photo_paths: list[str] | None = None,
    waybill_no: str = "",
    order_id: int | None = None,
) -> PackingDraft:
    cleaned_lines = _clean_lines(lines)
    selected_order = session.get(SalesOrder, int(order_id)) if order_id else None
    if order_id and selected_order is None:
        raise ValueError("所选订单不存在")
    if selected_order is not None:
        if get_open_archive(session, selected_order.id):
            raise ValueError("订单已归档，请先恢复")
        if selected_order.status != "active":
            raise ValueError("所选订单已停用")
        _validate_formal_order_lines(session, selected_order, cleaned_lines)
        company_name = selected_order.company.name
        product_name = selected_order.product_name
        style_name = selected_order.style_name
    draft = PackingDraft(
        user_id=user_id,
        order_id=selected_order.id if selected_order else None,
        pack_date=pack_date,
        company_name=company_name,
        product_name=product_name,
        style_name=style_name,
        package_no=_next_package_no(session, pack_date),
        waybill_no=str(waybill_no or "").strip(),
        note=note,
    )
    session.add(draft)
    session.flush()
    for line in cleaned_lines:
        session.add(
            PackingDraftLine(
                draft_id=draft.id,
                order_line_id=line.get("order_line_id"),
                size=line["size"],
                quantity=line["quantity"],
            )
        )
    for path in photo_paths or []:
        session.add(PackingDraftPhoto(draft_id=draft.id, file_path=path, original_name=Path(path).name))
    session.commit()
    session.refresh(draft)
    return draft


def _get_own_draft(session, draft_id: int, user_id: int) -> PackingDraft:
    draft = session.get(PackingDraft, draft_id)
    if draft is None or draft.user_id != user_id:
        raise ValueError("不能修改这条包货记录")
    if draft.submitted_report_id is not None:
        raise ValueError("已提交的包货记录不能修改")
    return draft


def update_packing_draft(
    session,
    draft_id: int,
    user_id: int,
    lines: list[dict],
    note: str = "",
    photo_paths: list[str] | None = None,
    waybill_no: str | None = None,
) -> PackingDraft:
    draft = _get_own_draft(session, draft_id, user_id)
    cleaned_lines = _clean_lines(lines)
    if draft.order_id:
        selected_order = session.get(SalesOrder, draft.order_id)
        if selected_order is None:
            raise ValueError("所选订单不存在")
        if get_open_archive(session, selected_order.id):
            raise ValueError("订单已归档，请先恢复")
        _validate_formal_order_lines(session, selected_order, cleaned_lines)
    for line in list(draft.lines):
        session.delete(line)
    session.flush()
    for line in cleaned_lines:
        session.add(
            PackingDraftLine(
                draft_id=draft.id,
                order_line_id=line.get("order_line_id"),
                size=line["size"],
                quantity=line["quantity"],
            )
        )
    for path in photo_paths or []:
        session.add(PackingDraftPhoto(draft_id=draft.id, file_path=path, original_name=Path(path).name))
    draft.note = note
    if waybill_no is not None:
        draft.waybill_no = str(waybill_no).strip()
    session.commit()
    session.refresh(draft)
    return draft


def delete_packing_draft(session, draft_id: int, user_id: int) -> None:
    draft = _get_own_draft(session, draft_id, user_id)
    session.delete(draft)
    session.commit()


def submit_packing_draft(session, draft_id: int, user_id: int):
    draft = _get_own_draft(session, draft_id, user_id)
    lines = [{"size": line.size, "quantity": line.quantity, "order_line_id": line.order_line_id} for line in draft.lines]
    report = submit_shipment_report(
        session,
        user_id=user_id,
        ship_date=draft.pack_date,
        company_name=draft.company_name,
        product_name=draft.product_name,
        style_name=draft.style_name,
        lines=lines,
        photo_paths=[photo.file_path for photo in draft.photos],
        note=draft.note,
        waybill_no=draft.waybill_no or "",
        order_id=draft.order_id,
    )
    draft.submitted_report_id = report.id
    for photo in report.photos:
        photo.draft_id = draft.id
    session.commit()
    session.refresh(report)
    return report
