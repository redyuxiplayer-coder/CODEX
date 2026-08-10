import json

from sqlalchemy.orm import Session

from app.models import OperationLog, OrderLine, SalesOrder, SalesOrderArchive, now
from app.services.orders import get_order_balances


def get_open_archive(session: Session, order_id: int) -> SalesOrderArchive | None:
    return (
        session.query(SalesOrderArchive)
        .filter(
            SalesOrderArchive.order_id == int(order_id),
            SalesOrderArchive.restored_at.is_(None),
        )
        .order_by(SalesOrderArchive.id.desc())
        .first()
    )


def archived_order_ids(session: Session) -> set[int]:
    return {
        int(order_id)
        for (order_id,) in session.query(SalesOrderArchive.order_id)
        .filter(SalesOrderArchive.restored_at.is_(None))
        .all()
    }


def archived_order_line_ids(session: Session) -> set[int]:
    order_ids = archived_order_ids(session)
    if not order_ids:
        return set()
    return {
        int(line_id)
        for (line_id,) in session.query(OrderLine.id)
        .filter(OrderLine.order_id.in_(order_ids))
        .all()
    }


def worker_visible_balances(session: Session, company_name: str | None = None) -> list[dict]:
    hidden_line_ids = archived_order_line_ids(session)
    return [
        row
        for row in get_order_balances(session, company_name=company_name)
        if not hidden_line_ids.intersection(int(line_id) for line_id in row.get("order_ids", []))
    ]


def _history_item(record: SalesOrderArchive) -> dict:
    return {
        "id": record.id,
        "order_id": record.order_id,
        "archived_by": record.archived_by,
        "archived_by_name": record.archiver.display_name if record.archiver else "",
        "archived_at": record.archived_at,
        "restored_by": record.restored_by,
        "restored_by_name": record.restorer.display_name if record.restorer else "",
        "restored_at": record.restored_at,
    }


def _balance_rows(session: Session, order: SalesOrder) -> list[dict]:
    active_line_ids = {int(line.id) for line in order.lines if line.is_active}
    if not active_line_ids:
        return []
    rows = get_order_balances(session, company_name=order.company.name)
    return [
        row
        for row in rows
        if active_line_ids.intersection(int(line_id) for line_id in row.get("order_ids", []))
    ]


def archive_state(session: Session, order: SalesOrder) -> dict:
    active_lines = [line for line in order.lines if line.is_active]
    current = get_open_archive(session, order.id)
    history = (
        session.query(SalesOrderArchive)
        .filter(SalesOrderArchive.order_id == order.id)
        .order_by(SalesOrderArchive.archived_at.desc(), SalesOrderArchive.id.desc())
        .all()
    )
    rows = _balance_rows(session, order) if active_lines else []
    blocking_sizes = [
        {"size": row["size"], "remaining": int(row.get("remaining") or 0)}
        for row in rows
        if int(row.get("remaining") or 0) > 0
    ]
    return {
        "is_archived": current is not None,
        "can_archive": bool(active_lines) and current is None and not blocking_sizes,
        "blocking_sizes": blocking_sizes,
        "current_archive": _history_item(current) if current else None,
        "history": [_history_item(record) for record in history],
    }


def _locked_order(session: Session, order_id: int) -> SalesOrder:
    order = (
        session.query(SalesOrder)
        .filter(SalesOrder.id == int(order_id))
        .with_for_update()
        .one_or_none()
    )
    if order is None:
        raise ValueError("订单不存在")
    return order


def archive_sales_order(session: Session, order_id: int, actor_id: int) -> SalesOrderArchive:
    order = _locked_order(session, order_id)
    if get_open_archive(session, order.id):
        raise ValueError("订单已经归档")
    if not any(line.is_active for line in order.lines):
        raise ValueError("订单没有有效明细")

    state = archive_state(session, order)
    if state["blocking_sizes"]:
        detail = "，".join(
            f'{item["size"]} 码还需 {item["remaining"]} 件'
            for item in state["blocking_sizes"]
        )
        raise ValueError(f"{detail}，不能归档")

    record = SalesOrderArchive(order_id=order.id, archived_by=int(actor_id))
    session.add(record)
    session.add(
        OperationLog(
            actor_id=int(actor_id),
            action="archive_sales_order",
            target=order.system_order_no,
            detail=json.dumps({"order_id": order.id}, ensure_ascii=False),
        )
    )
    session.commit()
    session.refresh(record)
    return record


def restore_sales_order(session: Session, order_id: int, actor_id: int) -> SalesOrderArchive:
    order = _locked_order(session, order_id)
    record = get_open_archive(session, order.id)
    if record is None:
        raise ValueError("订单尚未归档")

    record.restored_by = int(actor_id)
    record.restored_at = now()
    session.add(
        OperationLog(
            actor_id=int(actor_id),
            action="restore_sales_order",
            target=order.system_order_no,
            detail=json.dumps({"order_id": order.id, "archive_id": record.id}, ensure_ascii=False),
        )
    )
    session.commit()
    session.refresh(record)
    return record
