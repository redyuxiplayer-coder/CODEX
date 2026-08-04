from sqlalchemy.orm import Session

from app.models import OrderAdjustment, OrderLineClose
from app.services.ledger import recompute_order_ledger


def create_order_adjustment(
    session: Session,
    order_line_id: int,
    user_id: int,
    quantity: int,
    reason: str = "盘点调整",
) -> OrderAdjustment:
    record = OrderAdjustment(
        order_line_id=int(order_line_id),
        quantity=int(quantity),
        reason=(reason or "盘点调整").strip(),
        created_by=int(user_id),
    )
    session.add(record)
    session.commit()
    recompute_order_ledger(session, int(order_line_id))
    session.refresh(record)
    return record


def create_order_line_close(
    session: Session,
    order_line_id: int,
    user_id: int,
    quantity: int,
    reason: str = "客户不再需要",
) -> OrderLineClose:
    record = OrderLineClose(
        order_line_id=int(order_line_id),
        quantity=int(quantity),
        reason=(reason or "客户不再需要").strip(),
        created_by=int(user_id),
    )
    session.add(record)
    session.commit()
    recompute_order_ledger(session, int(order_line_id))
    session.refresh(record)
    return record


def list_adjustments(session: Session, order_line_id: int) -> list[OrderAdjustment]:
    return (
        session.query(OrderAdjustment)
        .filter_by(order_line_id=int(order_line_id))
        .order_by(OrderAdjustment.created_at.desc(), OrderAdjustment.id.desc())
        .all()
    )


def list_closes(session: Session, order_line_id: int) -> list[OrderLineClose]:
    return (
        session.query(OrderLineClose)
        .filter_by(order_line_id=int(order_line_id))
        .order_by(OrderLineClose.created_at.desc(), OrderLineClose.id.desc())
        .all()
    )
