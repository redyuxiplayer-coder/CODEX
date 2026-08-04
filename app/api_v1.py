from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth import authenticate, require_admin, require_user
from app.config import SESSION_COOKIE
from app.db import get_session
from app.models import (
    OrderLedgerEntry,
    OrderLine,
    OrderLineComment,
    ShipmentLine,
    ShipmentReport,
    User,
)
from app.services.adjustments import (
    create_order_adjustment,
    create_order_line_close,
    list_adjustments,
    list_closes,
)
from app.services.ledger import order_line_totals
from app.services.orders import get_order_balances
from app.services.photos import save_uploads
from app.services.returns import (
    create_return_rework,
    list_return_reworks,
    set_return_rework_status,
)

router = APIRouter(prefix="/api/v1")

APPROVED_STATUSES = {"auto_approved", "approved_after_edit"}


def _user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
    }


def _status_rank(row: dict) -> int:
    if int(row.get("remaining") or 0) > 0:
        return 0
    if int(row.get("over_shipped") or 0) > 0:
        return 1
    return 2


def _matches_status(row: dict, status: str) -> bool:
    remaining = int(row.get("remaining") or 0)
    over_shipped = int(row.get("over_shipped") or 0)
    if status == "need":
        return remaining > 0
    if status == "over":
        return over_shipped > 0
    if status == "done":
        return remaining <= 0 and over_shipped <= 0
    return True


def _sort_balances(rows: list[dict]) -> list[dict]:
    return sorted(
        rows,
        key=lambda row: (
            _status_rank(row),
            row.get("company", ""),
            row.get("product", ""),
            row.get("style", ""),
            row.get("order_date") or row.get("order_ref") or "",
            row.get("size", ""),
        ),
    )


def _ledger_dict(entry: OrderLedgerEntry) -> dict:
    return {
        "id": entry.id,
        "movement_type": entry.movement_type,
        "quantity": entry.quantity,
        "reason": entry.reason,
        "created_at": entry.created_at.isoformat() if entry.created_at else "",
        "creator": entry.creator.display_name if entry.creator else "",
    }


def _return_dict(record) -> dict:
    return {
        "id": record.id,
        "quantity": record.quantity,
        "reason_type": record.reason_type,
        "reason": record.reason,
        "status": record.status,
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "creator": record.creator.display_name if record.creator else "",
        "photos": [{"id": photo.id} for photo in record.photos],
    }


def _adjustment_dict(record) -> dict:
    return {
        "id": record.id,
        "quantity": record.quantity,
        "reason": record.reason,
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "creator": record.creator.display_name if record.creator else "",
    }


def _close_dict(record) -> dict:
    return {
        "id": record.id,
        "quantity": record.quantity,
        "reason": record.reason,
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "creator": record.creator.display_name if record.creator else "",
    }


def _comment_dict(record: OrderLineComment) -> dict:
    return {
        "id": record.id,
        "content": record.content,
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "user": record.user.display_name if record.user else "",
    }


def _shipment_dict(report: ShipmentReport, line: ShipmentLine) -> dict:
    return {
        "id": report.id,
        "ship_date": report.ship_date,
        "status": report.status,
        "quantity": line.quantity,
        "note": report.note,
        "waybill_no": report.waybill_no or "",
    }


def _order_dict(order: OrderLine) -> dict:
    return {
        "id": order.id,
        "company": order.company.name if order.company else "",
        "product": order.product_name,
        "style": order.style_name,
        "size": order.size,
        "sku": order.sku or "",
        "quantity": order.quantity,
        "order_date": order.order_date or "",
        "delivery_date": order.delivery_date or "",
        "batch": order.batch or "",
        "note": order.note or "",
    }


def _detail_payload(session: Session, line_id: int) -> dict:
    order = session.get(OrderLine, line_id)
    if order is None or not order.is_active:
        raise HTTPException(status_code=404, detail="订单行不存在")
    shipments = (
        session.query(ShipmentReport, ShipmentLine)
        .join(ShipmentLine, ShipmentLine.report_id == ShipmentReport.id)
        .filter(
            ShipmentLine.order_line_id == line_id,
            ShipmentReport.status.in_(APPROVED_STATUSES),
        )
        .order_by(ShipmentReport.ship_date.desc(), ShipmentReport.id.desc())
        .all()
    )
    ledger = (
        session.query(OrderLedgerEntry)
        .filter_by(order_line_id=line_id)
        .order_by(OrderLedgerEntry.created_at.desc(), OrderLedgerEntry.id.desc())
        .all()
    )
    comments = (
        session.query(OrderLineComment)
        .filter_by(order_line_id=line_id)
        .order_by(OrderLineComment.created_at.desc(), OrderLineComment.id.desc())
        .all()
    )
    return {
        "order": _order_dict(order),
        "totals": order_line_totals(session, line_id),
        "ledger": [_ledger_dict(entry) for entry in ledger],
        "returns": [_return_dict(record) for record in list_return_reworks(session, line_id)],
        "adjustments": [_adjustment_dict(record) for record in list_adjustments(session, line_id)],
        "closes": [_close_dict(record) for record in list_closes(session, line_id)],
        "comments": [_comment_dict(record) for record in comments],
        "shipments": [_shipment_dict(report, line) for report, line in shipments],
    }


@router.post("/login")
def api_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    user = authenticate(session, username, password)
    if not user:
        return JSONResponse({"detail": "账号或密码错误"}, status_code=401)
    response = JSONResponse(_user_dict(user))
    response.set_cookie(SESSION_COOKIE, str(user.id), httponly=True)
    return response


@router.post("/logout")
def api_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("/me")
def api_me(request: Request, session: Session = Depends(get_session)):
    user = require_user(request, session)
    return _user_dict(user)


@router.get("/orders/balances")
def api_orders_balances(
    request: Request,
    company: str = "",
    item: str = "",
    status: str = "",
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    all_rows = get_order_balances(session)
    companies = sorted({row["company"] for row in all_rows})
    item_choices = sorted({row["product"] for row in all_rows if row["product"]})
    item_text = item.strip()
    status_text = status.strip() or "all"
    rows = [
        row
        for row in all_rows
        if (not company or row["company"] == company)
        and (not item_text or row["product"] == item_text)
        and _matches_status(row, status_text)
    ]
    return {
        "companies": companies,
        "item_choices": item_choices,
        "balances": _sort_balances(rows),
    }


@router.get("/order-lines/{line_id}")
def api_order_line_detail(
    request: Request,
    line_id: int,
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    return _detail_payload(session, line_id)


@router.post("/order-lines/{line_id}/returns")
async def api_add_return(
    request: Request,
    line_id: int,
    quantity: int = Form(...),
    reason_type: str = Form("退回返工"),
    reason: str = Form(""),
    status: str = Form("pending_rework"),
    photos: list[UploadFile] = File([]),
    session: Session = Depends(get_session),
):
    admin = require_admin(request, session)
    _detail_payload(session, line_id)
    paths = await save_uploads(photos)
    create_return_rework(session, line_id, admin.id, quantity, reason_type, reason, status, photo_paths=paths)
    return _detail_payload(session, line_id)


@router.post("/order-lines/{line_id}/returns/{return_id}/status")
def api_return_status(
    request: Request,
    line_id: int,
    return_id: int,
    status: str = Form(...),
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    set_return_rework_status(session, return_id, status)
    return _detail_payload(session, line_id)


@router.post("/order-lines/{line_id}/adjustments")
def api_add_adjustment(
    request: Request,
    line_id: int,
    quantity: int = Form(...),
    reason: str = Form(""),
    session: Session = Depends(get_session),
):
    admin = require_admin(request, session)
    _detail_payload(session, line_id)
    create_order_adjustment(session, line_id, admin.id, quantity, reason)
    return _detail_payload(session, line_id)


@router.post("/order-lines/{line_id}/closes")
def api_add_close(
    request: Request,
    line_id: int,
    quantity: int = Form(...),
    reason: str = Form(""),
    session: Session = Depends(get_session),
):
    admin = require_admin(request, session)
    _detail_payload(session, line_id)
    create_order_line_close(session, line_id, admin.id, quantity, reason)
    return _detail_payload(session, line_id)


@router.post("/order-lines/{line_id}/comments")
def api_add_comment(
    request: Request,
    line_id: int,
    content: str = Form(...),
    session: Session = Depends(get_session),
):
    admin = require_admin(request, session)
    _detail_payload(session, line_id)
    content = content.strip()
    if content:
        session.add(OrderLineComment(order_line_id=line_id, user_id=admin.id, content=content))
        session.commit()
    return _detail_payload(session, line_id)
