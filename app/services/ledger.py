from sqlalchemy.orm import Session

from app.models import (
    OrderAdjustment,
    OrderLedgerEntry,
    OrderLine,
    OrderLineClose,
    ReturnRework,
    ShipmentLine,
    ShipmentReport,
)
from app.services.orders import APPROVED_STATUSES


def _delete_entries_for_line(session: Session, order_line_id: int) -> None:
    for entry in session.query(OrderLedgerEntry).filter_by(order_line_id=order_line_id).all():
        session.delete(entry)


def recompute_order_ledger(session: Session, order_line_id: int) -> None:
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
    session.commit()


def order_line_totals(session: Session, order_line_id: int) -> dict[str, int]:
    """单个订单行的发货/退回/调整/关闭/剩余汇总，与流水同源。"""
    order = session.get(OrderLine, order_line_id)
    shipped = sum(
        int(row[0] or 0)
        for row in session.query(ShipmentLine.quantity)
        .join(ShipmentReport, ShipmentReport.id == ShipmentLine.report_id)
        .filter(
            ShipmentLine.order_line_id == order_line_id,
            ShipmentReport.status.in_(APPROVED_STATUSES),
        )
        .all()
    )
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
