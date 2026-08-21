from sqlalchemy.orm import Session

from app.models import (
    Company,
    OrderAdjustment,
    OrderLedgerEntry,
    OrderLine,
    OrderLineClose,
    ReturnRework,
    ShipmentLine,
    ShipmentReport,
)
from app.services.aliases import canonical_item
from app.services.orders import APPROVED_STATUSES


def _delete_entries_for_line(session: Session, order_line_id: int) -> None:
    for entry in session.query(OrderLedgerEntry).filter_by(order_line_id=order_line_id).all():
        session.delete(entry)


def recompute_order_ledger(session: Session, order_line_id: int, *, commit: bool = True) -> None:
    """按来源表重建订单行流水：发货、退货/返工、调整（含报废）、关闭。"""
    _delete_entries_for_line(session, order_line_id)
    session.flush()

    shipped_rows = (
        session.query(ShipmentLine, ShipmentReport)
        .join(ShipmentReport, ShipmentReport.id == ShipmentLine.report_id)
        .filter(
            ShipmentLine.order_line_id == order_line_id,
            ShipmentReport.status.in_(APPROVED_STATUSES),
        )
        .all()
    )
    for line, report in shipped_rows:
        session.add(
            OrderLedgerEntry(
                order_line_id=order_line_id,
                movement_type="shipped",
                quantity=int(line.quantity or 0),
                reason=f"发货 {report.ship_date}",
                ref_report_id=report.id,
                created_by=report.user_id,
                created_at=report.created_at,
            )
        )

    returns = session.query(ReturnRework).filter_by(order_line_id=order_line_id).all()
    for ret in returns:
        reason_text = ret.reason_type or "退货/返工"
        if ret.reason:
            reason_text = f"{reason_text}：{ret.reason}"
        session.add(
            OrderLedgerEntry(
                order_line_id=order_line_id,
                movement_type="returned",
                quantity=int(ret.quantity or 0),
                reason=reason_text,
                ref_return_id=ret.id,
                created_by=ret.created_by,
                created_at=ret.created_at,
            )
        )
        if ret.status == "scrapped":
            session.add(
                OrderLedgerEntry(
                    order_line_id=order_line_id,
                    movement_type="adjusted",
                    quantity=int(ret.quantity or 0),
                    reason="报废核销",
                    ref_return_id=ret.id,
                    created_by=ret.created_by,
                    created_at=ret.created_at,
                )
            )

    for adj in session.query(OrderAdjustment).filter_by(order_line_id=order_line_id).all():
        session.add(
            OrderLedgerEntry(
                order_line_id=order_line_id,
                movement_type="adjusted",
                quantity=int(adj.quantity or 0),
                reason=adj.reason or "盘点调整",
                ref_adjustment_id=adj.id,
                created_by=adj.created_by,
                created_at=adj.created_at,
            )
        )

    for close in session.query(OrderLineClose).filter_by(order_line_id=order_line_id).all():
        session.add(
            OrderLedgerEntry(
                order_line_id=order_line_id,
                movement_type="closed",
                quantity=int(close.quantity or 0),
                reason=close.reason or "客户不再需要",
                ref_close_id=close.id,
                created_by=close.created_by,
                created_at=close.created_at,
            )
        )
    allocated_unbound = allocated_unbound_for_line(session, order_line_id)
    if allocated_unbound > 0:
        session.add(
            OrderLedgerEntry(
                order_line_id=order_line_id,
                movement_type="shipped",
                quantity=allocated_unbound,
                reason="历史导入未绑定发货（按款式归入本单）",
            )
        )
    session.flush()
    if commit:
        session.commit()


def recompute_for_report(session: Session, report_id: int, *, commit: bool = True) -> None:
    """重建某发货单涉及的订单行流水。"""
    order_line_ids = {
        int(line.order_line_id)
        for line in session.query(ShipmentLine).filter_by(report_id=report_id).all()
        if line.order_line_id
    }
    for order_line_id in order_line_ids:
        recompute_order_ledger(session, order_line_id, commit=False)
    session.flush()
    if commit:
        session.commit()


def _bound_shipped_for_line(session: Session, order_line_id: int) -> int:
    return sum(
        int(row[0] or 0)
        for row in session.query(ShipmentLine.quantity)
        .join(ShipmentReport, ShipmentReport.id == ShipmentLine.report_id)
        .filter(
            ShipmentLine.order_line_id == order_line_id,
            ShipmentReport.status.in_(APPROVED_STATUSES),
        )
        .all()
    )


def _unbound_shipped_for_base_key(
    session: Session,
    company_name: str,
    canonical_product: str,
    canonical_style: str,
    size: str,
) -> int:
    rows = (
        session.query(ShipmentReport, ShipmentLine)
        .join(ShipmentLine, ShipmentLine.report_id == ShipmentReport.id)
        .filter(
            ShipmentLine.order_line_id.is_(None),
            ShipmentReport.company_name == company_name,
            ShipmentLine.size == size,
            ShipmentReport.status.in_(APPROVED_STATUSES),
        )
        .all()
    )
    total = 0
    for report, line in rows:
        product, style = canonical_item(session, report.company_name, report.product_name, report.style_name)
        if product == canonical_product and style == canonical_style:
            total += int(line.quantity or 0)
    return total


def allocated_unbound_for_line(session: Session, order_line_id: int) -> int:
    """按与 get_order_balances 相同的分配逻辑，计算未绑定历史发货归入本单的数量。"""
    order = session.get(OrderLine, order_line_id)
    if order is None or not order.is_active:
        return 0
    canonical_product, canonical_style = canonical_item(session, order.company.name, order.product_name, order.style_name)
    lines = (
        session.query(OrderLine)
        .join(Company, Company.id == OrderLine.company_id)
        .filter(
            Company.name == order.company.name,
            OrderLine.size == order.size,
            OrderLine.is_active.is_(True),
        )
        .order_by(OrderLine.order_date, OrderLine.id)
        .all()
    )
    matching = [
        line
        for line in lines
        if canonical_item(session, line.company.name, line.product_name, line.style_name)
        == (canonical_product, canonical_style)
    ]
    if not matching:
        return 0
    remaining = _unbound_shipped_for_base_key(
        session,
        order.company.name,
        canonical_product,
        canonical_style,
        order.size,
    )
    allocations: dict[int, int] = {}
    for index, line in enumerate(matching):
        direct = _bound_shipped_for_line(session, line.id)
        open_quantity = max(0, int(line.quantity or 0) - direct)
        allocated = min(open_quantity, remaining)
        allocations[line.id] = allocated
        remaining -= allocated
        if index == len(matching) - 1 and remaining > 0:
            allocations[line.id] = allocations.get(line.id, 0) + remaining
            remaining = 0
    return allocations.get(order_line_id, 0)


def order_line_totals(session: Session, order_line_id: int) -> dict[str, int]:
    """单个订单行的发货/退回/调整/关闭/剩余汇总，与流水同源。"""
    order = session.get(OrderLine, order_line_id)
    shipped = _bound_shipped_for_line(session, order_line_id) + allocated_unbound_for_line(session, order_line_id)
    returned = int(sum(row.quantity or 0 for row in session.query(ReturnRework).filter_by(order_line_id=order_line_id).all()))
    scrapped = int(sum(row.quantity or 0 for row in session.query(ReturnRework).filter_by(order_line_id=order_line_id, status="scrapped").all()))
    adjusted = int(sum(row.quantity or 0 for row in session.query(OrderAdjustment).filter_by(order_line_id=order_line_id).all()))
    closed = int(sum(row.quantity or 0 for row in session.query(OrderLineClose).filter_by(order_line_id=order_line_id).all()))
    ordered = int(order.quantity or 0) if order else 0
    remaining = ordered - shipped + returned - (adjusted + scrapped) - closed
    return {
        "ordered": ordered,
        "shipped": shipped,
        "returned": returned,
        "adjusted": adjusted + scrapped,
        "closed": closed,
        "remaining": remaining,
        "over_shipped": max(0, -remaining),
    }
