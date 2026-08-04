from pathlib import Path

from sqlalchemy.orm import Session

from app.models import ReturnRework, ReturnReworkPhoto
from app.services.ledger import recompute_order_ledger

RETURN_STATUSES = {"pending_rework", "reworked", "scrapped"}


def create_return_rework(
    session: Session,
    order_line_id: int,
    user_id: int,
    quantity: int,
    reason_type: str = "退回返工",
    reason: str = "",
    status: str = "pending_rework",
    report_id: int | None = None,
    photo_paths: list[str] | None = None,
) -> ReturnRework:
    if status not in RETURN_STATUSES:
        status = "pending_rework"
    record = ReturnRework(
        order_line_id=int(order_line_id),
        report_id=int(report_id) if report_id else None,
        quantity=int(quantity),
        reason_type=(reason_type or "退回返工").strip(),
        reason=(reason or "").strip(),
        status=status,
        created_by=int(user_id),
    )
    session.add(record)
    session.flush()
    for path in photo_paths or []:
        session.add(ReturnReworkPhoto(return_id=record.id, file_path=path, original_name=Path(path).name))
    session.commit()
    recompute_order_ledger(session, int(order_line_id))
    session.refresh(record)
    return record


def set_return_rework_status(session: Session, return_id: int, status: str) -> ReturnRework:
    record = session.get(ReturnRework, return_id)
    if record is None:
        raise ValueError("退货/返工记录不存在")
    if status not in RETURN_STATUSES:
        raise ValueError("不支持的状态")
    record.status = status
    session.commit()
    recompute_order_ledger(session, record.order_line_id)
    session.refresh(record)
    return record


def list_return_reworks(session: Session, order_line_id: int) -> list[ReturnRework]:
    return (
        session.query(ReturnRework)
        .filter_by(order_line_id=int(order_line_id))
        .order_by(ReturnRework.created_at.desc(), ReturnRework.id.desc())
        .all()
    )
