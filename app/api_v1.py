from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import authenticate, require_admin, require_user
from app.config import SESSION_COOKIE
from app.db import get_session
from app.models import (
    Company,
    OrderLedgerEntry,
    OrderLine,
    OrderLineComment,
    SalesOrder,
    ShipmentLine,
    ShipmentReport,
    Spu,
    User,
    WaybillRecord,
)
from app.services.adjustments import (
    create_order_adjustment,
    create_order_line_close,
    list_adjustments,
    list_closes,
)
from app.services.daily_goals import get_daily_goals, set_daily_goals
from app.services.daily_stats import daily_shipment_stats
from app.services.ledger import order_line_totals
from app.services.logistics import (
    create_waybill_record,
    delete_waybill_record,
    link_candidates,
    link_reports_to_waybill,
    list_unlinked_reports,
    list_waybill_records,
    quick_link_waybill,
    set_unlinked_reason,
    unlink_report_from_waybill,
    update_waybill_record,
)
from app.services.operation_logs import recent_operation_logs
from app.services.order_archives import (
    archive_sales_order,
    archive_state,
    archived_order_ids,
    restore_sales_order,
)
from app.services.orders import (
    build_structured_note,
    clean_order_lines_from_form,
    create_order_lines_batch,
    find_duplicate_order_lines,
    get_order_balances,
    get_order_choices,
)
from app.services.sales_orders import create_sales_order
from app.services.spus import create_spu, normalize_code
from app.services.photos import save_uploads
from app.services.returns import (
    create_return_rework,
    list_return_reworks,
    set_return_rework_status,
)
from app.services.users import create_worker_user, set_user_password, update_user_profile
from app.services.waybills import (
    import_waybill_directory,
    list_waybill_photos,
    save_waybill_uploads,
    update_waybill_date,
    waybill_display_name,
)
from app.services.work_info import (
    approve_work_info_proposal,
    get_work_info,
    pending_work_info_proposals,
    proposal_rows,
    reject_work_info_proposal,
    save_work_info,
)
from app.models import OperationLog, WaybillPhoto
from sqlalchemy import func

router = APIRouter(prefix="/api/v1")

APPROVED_STATUSES = {"auto_approved", "approved_after_edit"}


class CompanyCodePayload(BaseModel):
    code: str


class SpuPayload(BaseModel):
    code: str = ""
    product_name: str
    style_name: str
    note: str = ""


class SpuUpdatePayload(SpuPayload):
    is_active: bool = True


class SalesOrderLinePayload(BaseModel):
    size: str
    quantity: int
    customer_sku: str = ""


class SalesOrderPayload(BaseModel):
    company_id: int
    spu_id: int
    color_name: str = ""
    color_code: str = ""
    order_date: str
    customer_order_no: str = ""
    delivery_date: str = ""
    note: str = ""
    lines: list[SalesOrderLinePayload] = Field(min_length=1)


def _user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
    }


def _spu_dict(spu: Spu) -> dict:
    return {
        "id": spu.id,
        "code": spu.code,
        "product_name": spu.product_name,
        "style_name": spu.style_name,
        "note": spu.note or "",
        "is_active": bool(spu.is_active),
    }


def _sales_order_dict(order: SalesOrder, state: dict | None = None) -> dict:
    archive_info = state or {
        "is_archived": False,
        "can_archive": False,
        "blocking_sizes": [],
        "current_archive": None,
        "history": [],
    }
    return {
        "id": order.id,
        "system_order_no": order.system_order_no,
        "customer_order_no": order.customer_order_no or "",
        "company": {"id": order.company.id, "name": order.company.name, "code": order.company.code or ""},
        "company_sequence": order.company_sequence,
        "spu": _spu_dict(order.spu),
        "product_name": order.product_name,
        "style_name": order.style_name,
        "color_name": order.color_name or "",
        "color_code": order.color_code or "",
        "order_date": order.order_date,
        "delivery_date": order.delivery_date or "",
        "note": order.note or "",
        "status": order.status,
        "lines": [
            {
                "id": line.id,
                "size": line.size,
                "quantity": line.quantity,
                "customer_sku": line.customer_sku or "",
            }
            for line in order.lines
        ],
        **archive_info,
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
        "bound": True,
    }


def _unbound_shipment_rows(session: Session, order: OrderLine) -> list[tuple[ShipmentReport, ShipmentLine]]:
    from app.services.aliases import canonical_item

    canonical_product, canonical_style = canonical_item(session, order.company.name, order.product_name, order.style_name)
    rows = (
        session.query(ShipmentReport, ShipmentLine)
        .join(ShipmentLine, ShipmentLine.report_id == ShipmentReport.id)
        .filter(
            ShipmentLine.order_line_id.is_(None),
            ShipmentReport.company_name == order.company.name,
            ShipmentLine.size == order.size,
            ShipmentReport.status.in_(APPROVED_STATUSES),
        )
        .all()
    )
    result = []
    for report, line in rows:
        product, style = canonical_item(session, report.company_name, report.product_name, report.style_name)
        if product == canonical_product and style == canonical_style:
            result.append((report, line))
    return result


def _report_dict(report: ShipmentReport) -> dict:
    lines = []
    for line in report.lines:
        order = line.order_line
        formal_order = order.order if order else None
        order_batch = order.batch if order else ""
        system_order_no = formal_order.system_order_no if formal_order else ""
        order_date = formal_order.order_date if formal_order else (order.order_date if order else "")
        order_reference = system_order_no or order_batch
        if order_reference and order_date:
            order_label = f"{order_reference} · {order_date}"
        else:
            order_label = order_reference or order_date or (f"订单 #{order.id}" if order else "")
        lines.append(
            {
                "size": line.size,
                "quantity": line.quantity,
                "order_line_id": line.order_line_id,
                "customer_sku": order.customer_sku if order else "",
                "system_order_no": system_order_no,
                "order_date": order_date or "",
                "order_batch": order_batch or "",
                "order_label": order_label,
            }
        )

    related_orders = []
    seen_order_ids = set()
    if report.order:
        related_orders.append(report.order)
        seen_order_ids.add(report.order.id)
    for line in report.lines:
        line_order = line.order_line.order if line.order_line else None
        if line_order and line_order.id not in seen_order_ids:
            related_orders.append(line_order)
            seen_order_ids.add(line_order.id)

    def joined_order_value(getter) -> str:
        values = []
        for related_order in related_orders:
            value = getter(related_order)
            if value and value not in values:
                values.append(value)
        return " / ".join(values)

    return {
        "id": report.id,
        "order_id": report.order_id,
        "system_order_no": joined_order_value(lambda order: order.system_order_no),
        "customer_order_no": joined_order_value(lambda order: order.customer_order_no),
        "order_date": joined_order_value(lambda order: order.order_date),
        "color_name": joined_order_value(lambda order: order.color_name),
        "spu_code": joined_order_value(lambda order: order.spu.code if order.spu else ""),
        "has_multiple_orders": len(related_orders) > 1,
        "ship_date": report.ship_date,
        "created_at": report.created_at.isoformat() if report.created_at else "",
        "user": report.user.display_name if report.user else "",
        "company": report.company_name,
        "product": report.product_name,
        "style": report.style_name,
        "waybill_no": report.waybill_no or "",
        "note": report.note,
        "status": report.status,
        "review_reason": report.review_reason,
        "lines": lines,
        "photos": [{"id": photo.id} for photo in report.photos],
    }


def _proposal_dict(proposal) -> dict:
    rows = []
    for index, row in enumerate(proposal_rows(proposal)):
        rows.append(
            {
                "row_index": index,
                "section_title": row.get("section_title", ""),
                "content": row.get("content", ""),
                "has_photo": bool(row.get("photo_path")),
            }
        )
    return {
        "id": proposal.id,
        "created_at": proposal.created_at.isoformat() if proposal.created_at else "",
        "user": proposal.user.display_name if proposal.user else "",
        "company": proposal.company_name,
        "product": proposal.product_name,
        "style": proposal.style_name,
        "rows": rows,
    }


def _waybill_dict(record: WaybillRecord) -> dict:
    return {
        "id": record.id,
        "company_name": record.company_name,
        "ship_date": record.ship_date,
        "waybill_no": record.waybill_no,
        "courier": record.courier,
        "weight_kg": record.weight_kg,
        "package_count": record.package_count,
        "note": record.note,
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "linked_count": len(record.reports),
        "linked_qty": sum(
            int(line.quantity or 0)
            for report in record.reports
            for line in report.lines
        ),
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
    unbound_shipments = _unbound_shipment_rows(session, order)
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
        "shipments": [_shipment_dict(report, line) for report, line in shipments]
        + [
            {**_shipment_dict(report, line), "bound": False}
            for report, line in unbound_shipments
        ],
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


@router.get("/companies")
def api_companies(request: Request, session: Session = Depends(get_session)):
    require_admin(request, session)
    companies = session.query(Company).order_by(Company.name).all()
    return {
        "companies": [
            {
                "id": company.id,
                "name": company.name,
                "code": company.code or "",
                "next_order_sequence": int(company.next_order_sequence or 1),
                "is_active": bool(company.is_active),
            }
            for company in companies
        ]
    }


@router.post("/companies/{company_id}/code")
def api_company_code(
    request: Request,
    company_id: int,
    payload: CompanyCodePayload,
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="公司不存在")
    try:
        code = normalize_code(payload.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    duplicate = session.query(Company.id).filter(Company.code == code, Company.id != company.id).first()
    if duplicate:
        raise HTTPException(status_code=400, detail="公司代码已存在")
    company.code = code
    session.commit()
    return {"id": company.id, "name": company.name, "code": company.code}


@router.get("/spus")
def api_spus(request: Request, q: str = "", session: Session = Depends(get_session)):
    require_admin(request, session)
    query = session.query(Spu).order_by(Spu.code)
    text_query = q.strip()
    if text_query:
        like = f"%{text_query}%"
        query = query.filter(
            (Spu.code.ilike(like)) | (Spu.product_name.ilike(like)) | (Spu.style_name.ilike(like))
        )
    return {"spus": [_spu_dict(spu) for spu in query.all()]}


@router.post("/spus")
def api_create_spu(
    request: Request,
    payload: SpuPayload,
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    try:
        return _spu_dict(
            create_spu(
                session,
                payload.code,
                payload.product_name,
                payload.style_name,
                payload.note,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/spus/{spu_id}/update")
def api_update_spu(
    request: Request,
    spu_id: int,
    payload: SpuUpdatePayload,
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    spu = session.get(Spu, spu_id)
    if spu is None:
        raise HTTPException(status_code=404, detail="SPU 不存在")
    try:
        code = normalize_code(payload.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    duplicate = session.query(Spu.id).filter(Spu.code == code, Spu.id != spu.id).first()
    if duplicate:
        raise HTTPException(status_code=400, detail="SPU 编码已存在")
    product_name = payload.product_name.strip()
    style_name = payload.style_name.strip()
    if not product_name or not style_name:
        raise HTTPException(status_code=400, detail="产品和款式不能为空")
    spu.code = code
    spu.product_name = product_name
    spu.style_name = style_name
    spu.note = payload.note.strip()
    spu.is_active = payload.is_active
    session.commit()
    return _spu_dict(spu)


@router.get("/sales-orders")
def api_sales_orders(
    request: Request,
    company_id: int | None = None,
    q: str = "",
    archive_status: str = "active",
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    if archive_status not in {"active", "archived", "all"}:
        raise HTTPException(status_code=400, detail="归档筛选值无效")
    hidden_order_ids = archived_order_ids(session)
    query = session.query(SalesOrder).order_by(SalesOrder.created_at.desc(), SalesOrder.id.desc())
    if archive_status == "active" and hidden_order_ids:
        query = query.filter(~SalesOrder.id.in_(hidden_order_ids))
    elif archive_status == "archived":
        if not hidden_order_ids:
            return {"orders": []}
        query = query.filter(SalesOrder.id.in_(hidden_order_ids))
    if company_id is not None:
        query = query.filter(SalesOrder.company_id == company_id)
    text_query = q.strip()
    if text_query:
        like = f"%{text_query}%"
        query = query.filter(
            (SalesOrder.system_order_no.ilike(like))
            | (SalesOrder.customer_order_no.ilike(like))
            | (SalesOrder.style_name.ilike(like))
        )
    return {
        "orders": [
            _sales_order_dict(
                order,
                {
                    "is_archived": order.id in hidden_order_ids,
                    "can_archive": False,
                    "blocking_sizes": [],
                    "current_archive": None,
                    "history": [],
                },
            )
            for order in query.limit(200).all()
        ]
    }


@router.get("/sales-orders/{order_id}")
def api_sales_order_detail(
    request: Request,
    order_id: int,
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    order = session.get(SalesOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    return _sales_order_dict(order, archive_state(session, order))


@router.post("/sales-orders/{order_id}/archive")
def api_archive_sales_order(
    request: Request,
    order_id: int,
    session: Session = Depends(get_session),
):
    admin = require_admin(request, session)
    try:
        archive_sales_order(session, order_id, admin.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    order = session.get(SalesOrder, order_id)
    return _sales_order_dict(order, archive_state(session, order))


@router.post("/sales-orders/{order_id}/restore")
def api_restore_sales_order(
    request: Request,
    order_id: int,
    session: Session = Depends(get_session),
):
    admin = require_admin(request, session)
    try:
        restore_sales_order(session, order_id, admin.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    order = session.get(SalesOrder, order_id)
    return _sales_order_dict(order, archive_state(session, order))


@router.post("/sales-orders")
def api_create_sales_order(
    request: Request,
    payload: SalesOrderPayload,
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    try:
        order = create_sales_order(
            session,
            company_id=payload.company_id,
            spu_id=payload.spu_id,
            color_name=payload.color_name,
            color_code=payload.color_code,
            order_date=payload.order_date,
            lines=[line.model_dump() for line in payload.lines],
            customer_order_no=payload.customer_order_no,
            delivery_date=payload.delivery_date,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _sales_order_dict(order)


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


@router.get("/dashboard")
def api_dashboard(request: Request, session: Session = Depends(get_session)):
    require_admin(request, session)
    from datetime import date

    today = date.today().isoformat()
    balances = get_order_balances(session)
    pending = session.query(ShipmentReport).filter_by(status="pending_review").count()
    today_reports = session.query(ShipmentReport).filter_by(ship_date=today).all()
    today_total = sum(
        line.quantity
        for report in today_reports
        if report.status in APPROVED_STATUSES
        for line in report.lines
    )
    recent = session.query(ShipmentReport).order_by(ShipmentReport.created_at.desc()).limit(12).all()
    return {
        "today": today,
        "today_total": today_total,
        "pending": pending,
        "unshipped_total": sum(max(0, row["remaining"]) for row in balances),
        "over_total": sum(row["over_shipped"] for row in balances),
        "recent": [_report_dict(report) for report in recent],
    }


@router.get("/orders/options")
def api_orders_options(request: Request, session: Session = Depends(get_session)):
    require_admin(request, session)
    companies = [
        name
        for (name,) in session.query(Company.name)
        .join(OrderLine, OrderLine.company_id == Company.id)
        .filter(Company.is_active.is_(True), OrderLine.is_active.is_(True))
        .distinct()
        .order_by(Company.name)
        .all()
        if name
    ]
    return {"companies": companies, "choices": get_order_choices(session)}


@router.post("/orders")
def api_create_orders(
    request: Request,
    company_name: str = Form(...),
    product_name: str = Form(...),
    style_name: str = Form(...),
    sizes: list[str] = Form([]),
    quantities: list[str] = Form([]),
    order_date: str = Form(""),
    delivery_date: str = Form(""),
    accessories: str = Form(""),
    material: str = Form(""),
    spec_size: str = Form(""),
    note: str = Form(""),
    confirm_duplicate: str = Form("0"),
    session: Session = Depends(get_session),
):
    admin = require_admin(request, session)
    lines = clean_order_lines_from_form(sizes, quantities)
    structured_note = build_structured_note(accessories, material, spec_size, note)
    duplicates = find_duplicate_order_lines(session, company_name, product_name, style_name, order_date, lines)
    if duplicates and confirm_duplicate != "1":
        return {
            "duplicates": [
                {
                    "company": order.company.name,
                    "product": order.product_name,
                    "style": order.style_name,
                    "size": order.size,
                    "quantity": order.quantity,
                    "order_date": order.order_date,
                }
                for order in duplicates
            ],
            "created": 0,
        }
    created = create_order_lines_batch(
        session,
        company_name,
        product_name,
        style_name,
        lines,
        order_date,
        delivery_date,
        structured_note,
    )
    return {"created": len(created), "total": sum(line["quantity"] for line in lines), "duplicates": []}


@router.get("/review/pending")
def api_review_pending(request: Request, session: Session = Depends(get_session)):
    require_admin(request, session)
    reports = (
        session.query(ShipmentReport)
        .filter_by(status="pending_review")
        .order_by(ShipmentReport.created_at.desc(), ShipmentReport.id.desc())
        .limit(50)
        .all()
    )
    return {
        "reports": [_report_dict(report) for report in reports],
        "work_info_proposals": [_proposal_dict(proposal) for proposal in pending_work_info_proposals(session)],
    }


@router.post("/review/{report_id}/approve")
def api_review_approve(
    request: Request,
    report_id: int,
    note: str = Form(""),
    session: Session = Depends(get_session),
):
    admin = require_admin(request, session)
    from app.services.shipments import approve_report

    try:
        approve_report(session, report_id, admin.id, note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/review/{report_id}/reject")
def api_review_reject(
    request: Request,
    report_id: int,
    note: str = Form(""),
    session: Session = Depends(get_session),
):
    admin = require_admin(request, session)
    from app.services.shipments import reject_report

    try:
        reject_report(session, report_id, admin.id, note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/work-info/proposals/{proposal_id}/approve")
def api_work_info_proposal_approve(
    request: Request,
    proposal_id: int,
    note: str = Form(""),
    session: Session = Depends(get_session),
):
    admin = require_admin(request, session)
    approve_work_info_proposal(session, proposal_id, admin.id, note)
    return {"ok": True}


@router.post("/work-info/proposals/{proposal_id}/reject")
def api_work_info_proposal_reject(
    request: Request,
    proposal_id: int,
    note: str = Form(""),
    session: Session = Depends(get_session),
):
    admin = require_admin(request, session)
    reject_work_info_proposal(session, proposal_id, admin.id, note)
    return {"ok": True}


@router.get("/shipments")
def api_shipments(
    request: Request,
    company: str = "",
    waybill: str = "",
    page: int = 1,
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    query = session.query(ShipmentReport).order_by(ShipmentReport.created_at.desc(), ShipmentReport.id.desc())
    companies = [
        row[0]
        for row in session.query(ShipmentReport.company_name).distinct().order_by(ShipmentReport.company_name).all()
        if row[0]
    ]
    if company:
        query = query.filter(ShipmentReport.company_name == company)
    if waybill.strip():
        query = query.filter(ShipmentReport.waybill_no.contains(waybill.strip()))
    per_page = 10
    total = query.count()
    page = max(1, page)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    reports = query.offset((page - 1) * per_page).limit(per_page).all()
    return {
        "reports": [_report_dict(report) for report in reports],
        "companies": companies,
        "page": page,
        "total_pages": total_pages,
        "total": total,
    }


@router.post("/shipments/{report_id}/photos")
async def api_shipment_photos(
    request: Request,
    report_id: int,
    photos: list[UploadFile] = File([]),
    session: Session = Depends(get_session),
):
    admin = require_admin(request, session)
    report = session.get(ShipmentReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="发货单不存在")
    from datetime import date

    try:
        upload_date = date.fromisoformat(report.ship_date)
    except ValueError:
        upload_date = date.today()
    paths = await save_uploads(
        photos,
        company_name=report.company_name,
        style_name=report.style_name,
        upload_date=upload_date,
    )
    from app.models import ShipmentPhoto

    for path in paths:
        session.add(ShipmentPhoto(report_id=report.id, file_path=path, original_name=path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]))
    session.commit()
    return {"ok": True, "uploaded": len(paths)}


@router.post("/shipments/{report_id}/waybill")
def api_shipment_waybill(
    request: Request,
    report_id: int,
    waybill_no: str = Form(""),
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    report = session.get(ShipmentReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="发货单不存在")
    report.waybill_no = waybill_no.strip()
    session.commit()
    return {"ok": True}


@router.get("/skus")
def api_skus(request: Request, q: str = "", session: Session = Depends(get_session)):
    require_admin(request, session)
    from app.services.skus import list_sku_mappings

    return {
        "mappings": [
            {
                "id": m.id,
                "company": m.company_name,
                "product": m.product_name,
                "style": m.style_name,
                "size": m.size,
                "sku": m.sku,
                "barcode": m.barcode,
            }
            for m in list_sku_mappings(session, q)
        ]
    }


@router.post("/skus/{mapping_id}/update")
def api_sku_update(
    request: Request,
    mapping_id: int,
    company_name: str = Form(...),
    product_name: str = Form(...),
    style_name: str = Form(...),
    size: str = Form(...),
    sku: str = Form(...),
    barcode: str = Form(""),
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    from app.services.skus import upsert_sku_mapping

    upsert_sku_mapping(session, company_name, product_name, style_name, size, sku, barcode)
    return {"ok": True}


@router.post("/skus/import")
async def api_sku_import(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    from app.config import EXPORT_DIR
    from app.services.skus import import_sku_mappings_from_excel

    target = EXPORT_DIR / f"sku_{file.filename}"
    target.write_bytes(await file.read())
    try:
        result = import_sku_mappings_from_excel(session, target)
        return {"imported": result["imported"], "skipped": result["skipped"]}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/daily-stats")
def api_daily_stats(request: Request, ship_date: str = "", session: Session = Depends(get_session)):
    require_admin(request, session)
    from datetime import date

    target = ship_date or date.today().isoformat()
    rows = daily_shipment_stats(session, target)
    return {"ship_date": target, "rows": rows, "total": sum(row["quantity"] for row in rows)}


@router.get("/goals")
def api_goals(request: Request, goal_date: str = "", session: Session = Depends(get_session)):
    require_admin(request, session)
    from datetime import date

    target = goal_date or date.today().isoformat()
    goals = get_daily_goals(session, target)
    return {"goal_date": target, "goal_text": "\n".join(goal.content for goal in goals)}


@router.post("/goals")
def api_save_goals(
    request: Request,
    goal_date: str = Form(...),
    goal_text: str = Form(""),
    session: Session = Depends(get_session),
):
    admin = require_admin(request, session)
    set_daily_goals(session, goal_date, goal_text.splitlines(), admin.id)
    return {"ok": True}


@router.get("/users")
def api_users(request: Request, session: Session = Depends(get_session)):
    require_admin(request, session)
    users = session.query(User).order_by(User.role, User.username).all()
    return {
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "display_name": u.display_name,
                "role": u.role,
                "is_active": u.is_active,
            }
            for u in users
        ]
    }


@router.post("/users")
def api_create_user(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    try:
        create_worker_user(session, username, display_name, password)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/users/{user_id}/password")
def api_user_password(
    request: Request,
    user_id: int,
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    try:
        set_user_password(session, user_id, password)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/users/{user_id}/update")
def api_user_update(
    request: Request,
    user_id: int,
    username: str = Form(...),
    display_name: str = Form(...),
    role: str = Form(...),
    is_active: str = Form("0"),
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    try:
        update_user_profile(
            session,
            user_id,
            username=username,
            display_name=display_name,
            role=role,
            is_active=is_active == "1",
        )
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/logs")
def api_logs(request: Request, session: Session = Depends(get_session)):
    require_admin(request, session)
    return {
        "logs": [
            {
                "id": log.id,
                "created_at": log.created_at.isoformat() if log.created_at else "",
                "actor": log.actor.display_name if log.actor else "",
                "action": log.action,
                "target": log.target,
                "detail": log.detail,
            }
            for log in recent_operation_logs(session)
        ]
    }


@router.get("/logistics/candidates")
def api_logistics_candidates(
    request: Request,
    company: str = "",
    ship_date: str = "",
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    reports = link_candidates(session, company, ship_date)
    return {"reports": [_report_dict(report) for report in reports]}


@router.get("/logistics")
def api_logistics_list(
    request: Request,
    company: str = "",
    ship_date: str = "",
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    return {
        "records": [
            _waybill_dict(record)
            for record in list_waybill_records(session, company, ship_date)
        ]
    }


@router.get("/logistics/unlinked")
def api_logistics_unlinked(
    request: Request,
    company: str = "",
    ship_date: str = "",
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    return {
        "records": list_unlinked_reports(session, company, ship_date),
    }


@router.post("/logistics/quick-link")
def api_logistics_quick_link(
    request: Request,
    report_id: int = Form(...),
    courier: str = Form("中通"),
    waybill_no: str = Form(...),
    weight_kg: float = Form(0),
    package_count: int = Form(0),
    note: str = Form(""),
    session: Session = Depends(get_session),
):
    admin = require_admin(request, session)
    try:
        record = quick_link_waybill(
            session,
            admin.id,
            report_id,
            courier,
            waybill_no,
            weight_kg,
            package_count,
            note,
        )
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _waybill_dict(record)


@router.post("/shipments/{report_id}/unlinked-reason")
def api_shipment_unlinked_reason(
    request: Request,
    report_id: int,
    reason: str = Form(""),
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    set_unlinked_reason(session, report_id, reason)
    return {"ok": True}


@router.post("/logistics")
def api_logistics_create(
    request: Request,
    company_name: str = Form(...),
    ship_date: str = Form(...),
    waybill_no: str = Form(...),
    courier: str = Form("中通"),
    weight_kg: float = Form(0),
    package_count: int = Form(0),
    note: str = Form(""),
    session: Session = Depends(get_session),
):
    admin = require_admin(request, session)
    try:
        record = create_waybill_record(
            session,
            admin.id,
            company_name,
            ship_date,
            waybill_no,
            courier,
            weight_kg,
            package_count,
            note,
        )
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _waybill_dict(record)


@router.get("/logistics/{waybill_id}")
def api_logistics_detail(
    request: Request,
    waybill_id: int,
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    record = session.get(WaybillRecord, waybill_id)
    if record is None:
        raise HTTPException(status_code=404, detail="快递单不存在")
    return {
        **_waybill_dict(record),
        "reports": [_report_dict(report) for report in record.reports],
    }


@router.post("/logistics/{waybill_id}/update")
def api_logistics_update(
    request: Request,
    waybill_id: int,
    company_name: str = Form(...),
    ship_date: str = Form(...),
    waybill_no: str = Form(...),
    courier: str = Form("中通"),
    weight_kg: float = Form(0),
    package_count: int = Form(0),
    note: str = Form(""),
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    try:
        record = update_waybill_record(
            session,
            waybill_id,
            company_name=company_name,
            ship_date=ship_date,
            waybill_no=waybill_no,
            courier=courier,
            weight_kg=weight_kg,
            package_count=package_count,
            note=note,
        )
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _waybill_dict(record)


@router.post("/logistics/{waybill_id}/reports")
def api_logistics_link(
    request: Request,
    waybill_id: int,
    report_ids: list[int] = Form(...),
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    record = link_reports_to_waybill(session, waybill_id, report_ids)
    return {
        **_waybill_dict(record),
        "reports": [_report_dict(report) for report in record.reports],
    }


@router.post("/logistics/{waybill_id}/reports/{report_id}/remove")
def api_logistics_unlink(
    request: Request,
    waybill_id: int,
    report_id: int,
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    unlink_report_from_waybill(session, waybill_id, report_id)
    record = session.get(WaybillRecord, waybill_id)
    if record is None:
        return {"ok": True}
    return {
        **_waybill_dict(record),
        "reports": [_report_dict(report) for report in record.reports],
    }


@router.delete("/logistics/{waybill_id}")
def api_logistics_delete(
    request: Request,
    waybill_id: int,
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    delete_waybill_record(session, waybill_id)
    return {"ok": True}


@router.get("/waybills")
def api_waybills(request: Request, session: Session = Depends(get_session)):
    require_admin(request, session)
    companies = sorted({row.name for row in session.query(Company).filter(Company.is_active.is_(True)).all()})
    counts = [
        {"company": company, "count": count}
        for company, count in session.query(WaybillPhoto.company_name, func.count(WaybillPhoto.id))
        .group_by(WaybillPhoto.company_name)
        .order_by(WaybillPhoto.company_name)
        .all()
    ]
    photos = [
        {
            "id": photo.id,
            "company": photo.company_name,
            "waybill_date": photo.waybill_date,
            "display_name": waybill_display_name(photo),
        }
        for photo in list_waybill_photos(session)
    ]
    return {"companies": companies, "counts": counts, "photos": photos}


@router.post("/waybills/upload")
async def api_waybill_upload(
    request: Request,
    company: str = Form(...),
    waybill_date: str = Form(""),
    files: list[UploadFile] = File([]),
    session: Session = Depends(get_session),
):
    admin = require_admin(request, session)
    result = await save_waybill_uploads(session, company, files, uploaded_by=admin.id, waybill_date=waybill_date)
    return {"imported": result["imported"], "skipped": result["skipped"]}


@router.post("/waybills/{photo_id}/date")
def api_waybill_date(
    request: Request,
    photo_id: int,
    waybill_date: str = Form(""),
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    update_waybill_date(session, photo_id, waybill_date)
    return {"ok": True}


@router.get("/work-info")
def api_work_info(
    request: Request,
    company: str = "",
    product: str = "",
    style: str = "",
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    rows = get_work_info(session, company, product, style)
    return {
        "company": company,
        "product": product,
        "style": style,
        "rows": [
            {
                "id": row["id"],
                "section_key": row["section_key"],
                "section_title": row["section_title"],
                "content": row["content"],
                "photo_path": row["photo_path"] or "",
                "original_name": row["original_name"] or "",
                "is_custom": bool(row["is_custom"]),
            }
            for row in rows
        ],
    }


@router.post("/work-info")
async def api_save_work_info(
    request: Request,
    company_name: str = Form(...),
    product_name: str = Form(...),
    style_name: str = Form(...),
    section_key: list[str] = Form([]),
    section_title: list[str] = Form([]),
    content: list[str] = Form([]),
    existing_photo_path: list[str] = Form([]),
    existing_original_name: list[str] = Form([]),
    remove_photo: list[str] = Form([]),
    photo_accessories: UploadFile | None = File(None),
    photo_bag: UploadFile | None = File(None),
    photo_wash_label: UploadFile | None = File(None),
    photo_sticker: UploadFile | None = File(None),
    custom_photos: list[UploadFile] = File([]),
    photos: list[UploadFile] = File([]),
    session: Session = Depends(get_session),
):
    admin = require_admin(request, session)
    fixed_photos = {
        "accessories": photo_accessories,
        "bag": photo_bag,
        "wash_label": photo_wash_label,
        "sticker": photo_sticker,
    }
    saved_fixed = {
        key: (await save_uploads([file]))[0]
        for key, file in fixed_photos.items()
        if file is not None and file.filename
    }
    saved_custom = await save_uploads(custom_photos)
    fallback_photos = await save_uploads(photos)
    custom_index = 0
    rows = []
    for index, (key, title, value) in enumerate(zip(section_key, section_title, content)):
        is_custom = key == "custom" or key.startswith("custom:")
        photo_path = existing_photo_path[index] if index < len(existing_photo_path) else ""
        original_name = existing_original_name[index] if index < len(existing_original_name) else ""
        if index < len(remove_photo) and remove_photo[index] == "1":
            photo_path = ""
            original_name = ""
        if key in saved_fixed:
            photo_path = saved_fixed[key]
            original_name = fixed_photos[key].filename or ""
        elif is_custom and custom_index < len(saved_custom):
            photo_path = saved_custom[custom_index]
            original_name = custom_photos[custom_index].filename or ""
            custom_index += 1
        elif index < len(fallback_photos):
            photo_path = fallback_photos[index]
            original_name = photos[index].filename if index < len(photos) and photos[index].filename else ""
        rows.append(
            {
                "section_key": key,
                "section_title": title,
                "content": value,
                "photo_path": photo_path,
                "original_name": original_name,
            }
        )
    save_work_info(session, company_name, product_name, style_name, rows, updated_by=admin.id)
    return {"ok": True}
