from sqlalchemy.orm import Session

from app.models import OperationLog


def log_operation(session: Session, actor_id: int | None, action: str, target: str = "", detail: str = "") -> OperationLog:
    log = OperationLog(actor_id=actor_id, action=action, target=target, detail=detail)
    session.add(log)
    session.commit()
    return log


def recent_operation_logs(session: Session, limit: int = 200) -> list[OperationLog]:
    return session.query(OperationLog).order_by(OperationLog.created_at.desc()).limit(limit).all()
