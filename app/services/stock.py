"""Local stock: per 款 + 颜色 + 尺码 quantities, with a movement trail."""

from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Spu, StockItem, StockMovement


def normalize(value: object) -> str:
    return str(value or "").strip()


def get_spu(session: Session, spu_id: int) -> Spu:
    spu = session.get(Spu, int(spu_id))
    if spu is None:
        raise ValueError("款不存在")
    return spu


def list_spus(session: Session) -> list[Spu]:
    return session.query(Spu).filter(Spu.is_active.is_(True)).order_by(Spu.code).all()


def get_item(session: Session, item_id: int) -> StockItem:
    item = session.get(StockItem, int(item_id))
    if item is None:
        raise ValueError("库存行不存在")
    return item


def ensure_item(
    session: Session,
    spu: Spu,
    color_name: str,
    color_code: str,
    size: str,
) -> StockItem:
    clean_color = normalize(color_name)
    clean_code = normalize(color_code)
    clean_size = normalize(size)
    item = (
        session.query(StockItem)
        .filter(
            StockItem.spu_id == spu.id,
            StockItem.color_name == clean_color,
            StockItem.size == clean_size,
        )
        .one_or_none()
    )
    if item is not None:
        return item
    item = StockItem(
        spu_id=spu.id,
        product_name=spu.product_name,
        style_name=spu.style_name,
        color_name=clean_color,
        color_code=clean_code,
        size=clean_size,
        quantity=0,
    )
    session.add(item)
    session.flush()
    return item


def list_stock(session: Session, q: str = "") -> list[StockItem]:
    query = session.query(StockItem)
    text = normalize(q)
    if text:
        like = f"%{text}%"
        query = query.filter(
            or_(
                StockItem.style_name.ilike(like),
                StockItem.product_name.ilike(like),
                StockItem.color_name.ilike(like),
                StockItem.size.ilike(like),
            )
        )
    return query.order_by(
        StockItem.product_name, StockItem.style_name, StockItem.color_name, StockItem.size
    ).all()


def _record(
    session: Session,
    item: StockItem,
    movement_type: str,
    delta: int,
    reason: str,
    actor_id: int | None,
) -> StockMovement:
    movement = StockMovement(
        item_id=item.id,
        movement_type=movement_type,
        quantity_delta=delta,
        quantity_after=item.quantity,
        reason=normalize(reason),
        created_by=actor_id,
    )
    session.add(movement)
    return movement


def set_stock_count(
    session: Session,
    item: StockItem,
    quantity: int,
    reason: str,
    actor_id: int | None,
) -> StockMovement:
    """盘点：把现有数直接改成实际数，差异记入流水。"""
    target = int(quantity)
    if target < 0:
        raise ValueError("数量不能小于 0")
    delta = target - int(item.quantity or 0)
    item.quantity = target
    item.updated_by = actor_id
    item.updated_at = datetime.now()
    movement = _record(session, item, "count", delta, reason or "盘点", actor_id)
    session.commit()
    session.refresh(movement)
    return movement


def add_stock_in(
    session: Session,
    item: StockItem,
    quantity: int,
    reason: str,
    actor_id: int | None,
) -> StockMovement:
    """入库：进多少件就加多少。"""
    add = int(quantity)
    if add <= 0:
        raise ValueError("入库数量必须大于 0")
    item.quantity = int(item.quantity or 0) + add
    item.updated_by = actor_id
    item.updated_at = datetime.now()
    movement = _record(session, item, "in", add, reason or "入库", actor_id)
    session.commit()
    session.refresh(movement)
    return movement


def list_movements(session: Session, item_id: int | None = None, limit: int = 100) -> list[StockMovement]:
    query = session.query(StockMovement)
    if item_id is not None:
        query = query.filter(StockMovement.item_id == int(item_id))
    return query.order_by(StockMovement.created_at.desc(), StockMovement.id.desc()).limit(limit).all()
