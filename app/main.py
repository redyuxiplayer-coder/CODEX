from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import authenticate, current_user, hash_password, require_admin, require_user
from app.api_v1 import router as api_v1_router
from app.config import BASE_DIR, EXPORT_DIR, SESSION_COOKIE
from app.db import SessionLocal, get_session, init_db
from app.models import (
    AuditLog,
    Company,
    OrderAdjustment,
    OrderLine,
    OrderLineClose,
    OrderLineComment,
    OrderLedgerEntry,
    PackingDraft,
    PackingDraftPhoto,
    ReturnRework,
    ReturnReworkPhoto,
    SalesOrder,
    ShipmentLine,
    ShipmentPhoto,
    ShipmentReport,
    User,
    WaybillRecord,
    WorkInfoLine,
    WorkInfoProposal,
)
from app.services.adjustments import create_order_adjustment, create_order_line_close, list_adjustments, list_closes
from app.services.aliases import canonical_item, create_product_alias, list_product_aliases, update_product_alias
from app.services.exports import (
    export_company_workbook,
    export_customer_company_workbook,
    export_customer_total_workbook,
    export_daily_shipments_workbook,
    export_total_workbook,
    export_unshipped_workbook,
)
from app.services.daily_goals import get_daily_goals, set_daily_goals
from app.services.daily_stats import daily_shipment_stats
from app.services.orders import (
    build_structured_note,
    clean_order_lines_from_form,
    create_order_line,
    create_order_lines_batch,
    delete_order_line,
    find_duplicate_order_lines,
    get_order_balances,
    get_order_choices,
    import_excel_orders,
    size_sort_key,
    update_order_line,
)
from app.services.operation_logs import log_operation, recent_operation_logs
from app.services.order_archives import archived_order_ids, get_open_archive, worker_visible_balances
from app.services.packing_drafts import create_packing_draft, delete_packing_draft, submit_packing_draft, update_packing_draft
from app.services.photos import ensure_thumbnail, save_uploads
from app.services.photos import download_file_from_supabase_storage
from app.services.quantities import parse_quantity
from app.services.ledger import order_line_totals, recompute_for_report
from app.services.returns import create_return_rework, list_return_reworks, set_return_rework_status
from app.services.shipments import (
    approve_report,
    delete_own_pending_report,
    ensure_report_not_archived,
    reject_report,
    resolve_order_line_id,
    update_own_pending_report,
)
from app.services.skus import (
    barcode_lookup,
    import_sku_mappings_from_excel,
    list_sku_mappings,
    upsert_sku_mapping,
)
from app.services.users import create_worker_user, set_user_password, update_user_profile
from app.services.waybills import import_waybill_directory, list_waybill_photos, save_waybill_uploads, update_waybill_date, waybill_display_name
from app.services.work_info import (
    approve_work_info_proposal,
    create_work_info_proposal,
    get_work_info,
    pending_work_info_proposals,
    proposal_rows,
    reject_work_info_proposal,
    save_work_info,
)

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def shipment_status_label(status: str) -> str:
    return {
        "pending_review": "待审核",
        "auto_approved": "已通过",
        "approved_after_edit": "已修改通过",
        "rejected": "已驳回",
    }.get(status, status)


def ledger_type_label(movement_type: str) -> str:
    return {
        "shipped": "发货",
        "returned": "退回/返工",
        "adjusted": "核销/调整",
        "closed": "关闭",
    }.get(movement_type, movement_type)


def return_status_label(status: str) -> str:
    return {
        "pending_rework": "待返工",
        "reworked": "已返工",
        "scrapped": "已报废",
    }.get(status, status)


templates.env.globals["shipment_status_label"] = shipment_status_label
templates.env.globals["ledger_type_label"] = ledger_type_label
templates.env.globals["return_status_label"] = return_status_label
templates.env.globals["proposal_rows"] = proposal_rows

LOGIN_FAILURE_LIMIT = 3
LOGIN_LOCK_MINUTES = 15


def login_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{username.strip().lower()}"


def is_login_locked(app: FastAPI, key: str) -> bool:
    record = app.state.login_failures.get(key)
    if not record:
        return False
    locked_until = record.get("locked_until")
    if not locked_until:
        return False
    if locked_until <= datetime.now():
        app.state.login_failures.pop(key, None)
        return False
    return True


def record_failed_login(app: FastAPI, key: str) -> None:
    record = app.state.login_failures.setdefault(key, {"count": 0, "locked_until": None})
    record["count"] += 1
    if record["count"] >= LOGIN_FAILURE_LIMIT:
        record["locked_until"] = datetime.now() + timedelta(minutes=LOGIN_LOCK_MINUTES)


def clear_failed_login(app: FastAPI, key: str) -> None:
    app.state.login_failures.pop(key, None)


def item_choices_from_balances(balances: list[dict]) -> list[str]:
    choices = set()
    for row in balances:
        if row["product"]:
            choices.add(row["product"])
    return sorted(choices)


def item_choices_with_current(balances: list[dict], current: str) -> list[str]:
    choices = item_choices_from_balances(balances)
    if current and current not in choices:
        choices.insert(0, current)
    return choices


def order_choices_from_balances(balances: list[dict]) -> dict:
    companies: dict[str, dict[str, dict[str, set[str]]]] = {}
    for row in balances:
        company = row["company"]
        product = row["product"]
        style = row["style"]
        size = row["size"]
        companies.setdefault(company, {}).setdefault(product, {}).setdefault(style, set()).add(size)
    return {
        company: {
            product: {style: sorted(sizes, key=size_sort_key) for style, sizes in styles.items()}
            for product, styles in products.items()
        }
        for company, products in companies.items()
    }


def sort_balances_for_display(balances: list[dict]) -> list[dict]:
    def status_rank(row: dict) -> int:
        if int(row.get("remaining") or 0) > 0:
            return 0
        if int(row.get("over_shipped") or 0) > 0:
            return 1
        return 2

    return sorted(
        balances,
        key=lambda row: (
            status_rank(row),
            row.get("company", ""),
            row.get("product", ""),
            row.get("style", ""),
            row.get("order_date") or row.get("order_ref") or "",
            size_sort_key(row.get("size", "")),
        ),
    )


def _matches_order_status(row: dict, status: str) -> bool:
    remaining = int(row.get("remaining") or 0)
    over_shipped = int(row.get("over_shipped") or 0)
    if status == "need":
        return remaining > 0
    if status == "over":
        return over_shipped > 0
    if status == "done":
        return remaining <= 0 and over_shipped <= 0
    return True


def balances_for_report_hint_from_balances(balances: list[dict]) -> dict:
    hints: dict[str, dict[str, dict[str, dict[str, dict[str, int]]]]] = {}
    for row in balances:
        hints.setdefault(row["company"], {}).setdefault(row["product"], {}).setdefault(row["style"], {})[row["size"]] = {
            "ordered": int(row["ordered"]) + int(hints.get(row["company"], {}).get(row["product"], {}).get(row["style"], {}).get(row["size"], {}).get("ordered", 0)),
            "shipped": int(row["shipped"]) + int(hints.get(row["company"], {}).get(row["product"], {}).get(row["style"], {}).get(row["size"], {}).get("shipped", 0)),
            "remaining": int(row["remaining"]) + int(hints.get(row["company"], {}).get(row["product"], {}).get(row["style"], {}).get(row["size"], {}).get("remaining", 0)),
            "over_shipped": int(row["over_shipped"]) + int(hints.get(row["company"], {}).get(row["product"], {}).get(row["style"], {}).get(row["size"], {}).get("over_shipped", 0)),
        }
    return hints


def balances_for_report_hint(session: Session) -> dict:
    return balances_for_report_hint_from_balances(worker_visible_balances(session))


def active_order_companies(session: Session) -> list[str]:
    return sorted({row["company"] for row in worker_visible_balances(session) if row["company"]})


def _pending_quantities_by_order_line(session: Session) -> dict[int, int]:
    rows = (
        session.query(ShipmentLine.order_line_id, func.sum(ShipmentLine.quantity))
        .join(ShipmentReport, ShipmentReport.id == ShipmentLine.report_id)
        .filter(
            ShipmentLine.order_line_id.is_not(None),
            ShipmentReport.status == "pending_review",
        )
        .group_by(ShipmentLine.order_line_id)
        .all()
    )
    return {int(order_line_id): int(quantity or 0) for order_line_id, quantity in rows if order_line_id}


def _formal_order_line_payloads(
    order: SalesOrder,
    balance_by_line_id: dict[int, dict],
    pending_by_line_id: dict[int, int] | None = None,
) -> list[dict]:
    lines = []
    pending_by_line_id = pending_by_line_id or {}
    for line in sorted((row for row in order.lines if row.is_active), key=lambda row: size_sort_key(row.size)):
        balance = balance_by_line_id.get(line.id, {})
        ordered = int(balance.get("ordered", line.quantity))
        approved_shipped = int(balance.get("shipped", 0))
        pending_shipped = int(pending_by_line_id.get(line.id, 0))
        shipped = approved_shipped + pending_shipped
        remaining = int(balance.get("remaining", ordered - approved_shipped)) - pending_shipped
        over_shipped = max(int(balance.get("over_shipped", max(0, approved_shipped - ordered))), max(0, shipped - ordered))
        if remaining < 0:
            over_shipped = max(over_shipped, -remaining)
            remaining = 0
        lines.append(
            {
                "order_line_id": line.id,
                "size": line.size,
                "customer_sku": line.customer_sku or "",
                "ordered": ordered,
                "shipped": shipped,
                "remaining": remaining,
                "over_shipped": over_shipped,
            }
        )
    return lines


def _remaining_summary(lines: list[dict]) -> str:
    parts = [f"{row['size']}{row['remaining']}" for row in lines if int(row.get("remaining") or 0) > 0]
    return " / ".join(parts) or "已发完"


def formal_order_options_payload(session: Session) -> list[dict]:
    hidden_order_ids = archived_order_ids(session)
    balance_by_line_id = {int(row["order_id"]): row for row in worker_visible_balances(session) if row.get("order_id")}
    pending_by_line_id = _pending_quantities_by_order_line(session)
    orders = (
        session.query(SalesOrder)
        .join(Company, Company.id == SalesOrder.company_id)
        .filter(SalesOrder.status == "active", Company.is_active.is_(True))
        .order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc())
        .all()
    )
    payload = []
    for order in orders:
        if order.id in hidden_order_ids:
            continue
        lines = _formal_order_line_payloads(order, balance_by_line_id, pending_by_line_id)
        payload.append(
            {
                "id": order.id,
                "system_order_no": order.system_order_no,
                "customer_order_no": order.customer_order_no or "",
                "company_name": order.company.name,
                "product_name": order.product_name,
                "style_name": order.style_name,
                "color_name": order.color_name or "无颜色",
                "order_date": order.order_date,
                "remaining_summary": _remaining_summary(lines),
            }
        )
    return payload


def formal_order_lines_payload(session: Session, order_id: int) -> dict:
    order = session.get(SalesOrder, order_id)
    if order is None or order.status != "active":
        raise ValueError("所选订单不存在或已停用")
    if get_open_archive(session, order.id):
        raise ValueError("订单已归档，请先恢复")
    balances = {int(row["order_id"]): row for row in worker_visible_balances(session, company_name=order.company.name) if row.get("order_id")}
    lines = _formal_order_line_payloads(order, balances, _pending_quantities_by_order_line(session))
    return {
        "order": next(row for row in formal_order_options_payload(session) if row["id"] == order.id),
        "lines": lines,
    }


def mobile_report_options_payload(session: Session, company: str = "", product: str = "", style: str = "") -> dict:
    if not company:
        return {"companies": active_order_companies(session)}
    if not product:
        return {"products": sorted({row["product"] for row in worker_visible_balances(session, company) if row["product"]})}
    if not style:
        return {
            "styles": sorted(
                {row["style"] for row in worker_visible_balances(session, company) if row["product"] == product and row["style"]}
            )
        }
    canonical_product, canonical_style = canonical_item(session, company, product, style)
    balances = [
        row
        for row in worker_visible_balances(session, company_name=company)
        if row["product"] == canonical_product and row["style"] == canonical_style
    ]
    hints = balances_for_report_hint_from_balances(balances).get(company, {}).get(canonical_product, {}).get(canonical_style, {})
    lines = [
        {
            "order_line_id": row["order_id"],
            "order_ref": row["order_ref"] or row["order_date"] or "未写下单日期",
            "order_date": row["order_date"],
            "size": row["size"],
            "ordered": int(row["ordered"]),
            "shipped": int(row["shipped"]),
            "remaining": int(row["remaining"]),
            "over_shipped": int(row["over_shipped"]),
        }
        for row in balances
    ]
    return {"sizes": sorted(hints.keys(), key=size_sort_key), "balances": hints, "lines": lines}


def open_packing_drafts(session: Session, user_id: int) -> list[PackingDraft]:
    return (
        session.query(PackingDraft)
        .filter(
            PackingDraft.user_id == user_id,
            PackingDraft.submitted_report_id.is_(None),
        )
        .order_by(PackingDraft.updated_at.desc(), PackingDraft.created_at.desc())
        .all()
    )


def huolala_trip_options_payload(session: Session, company_name: str, ship_date: str) -> list[dict]:
    company_name = company_name.strip()
    ship_date = ship_date.strip()
    if not company_name or not ship_date:
        return []
    trips: dict[str, dict] = {}
    draft_rows = (
        session.query(PackingDraft)
        .filter(
            PackingDraft.shipping_method == "huolala",
            PackingDraft.waybill_no != "",
            PackingDraft.company_name == company_name,
            PackingDraft.pack_date == ship_date,
        )
        .order_by(PackingDraft.pack_date.desc(), PackingDraft.id.desc())
        .all()
    )
    for draft in draft_rows:
        waybill_no = (draft.waybill_no or "").strip()
        if not waybill_no or waybill_no in trips:
            continue
        trips[waybill_no] = {
            "waybill_no": waybill_no,
            "company_name": draft.company_name,
            "ship_date": draft.pack_date,
            "package_count": int(draft.package_count or 0),
            "weight_kg": float(draft.weight_kg or 0),
        }
    records = (
        session.query(WaybillRecord)
        .filter(
            WaybillRecord.courier == "货拉拉",
            WaybillRecord.company_name == company_name,
            WaybillRecord.ship_date == ship_date,
        )
        .order_by(WaybillRecord.ship_date.desc(), WaybillRecord.id.desc())
        .all()
    )
    for record in records:
        waybill_no = (record.waybill_no or "").strip()
        if not waybill_no or waybill_no in trips:
            continue
        trips[waybill_no] = {
            "waybill_no": waybill_no,
            "company_name": record.company_name,
            "ship_date": record.ship_date,
            "package_count": int(record.package_count or 0),
            "weight_kg": float(record.weight_kg or 0),
        }
    return list(trips.values())


def mobile_report_page_context(request: Request, user: User, session: Session, message: str = "") -> dict:
    today = date.today().isoformat()
    context = {
        "request": request,
        "user": user,
        "today": today,
        "drafts": open_packing_drafts(session, user.id),
        "companies": active_order_companies(session),
        "formal_orders": formal_order_options_payload(session),
    }
    if message:
        context["message"] = message
    return context


def ensure_default_admin() -> None:
    session = SessionLocal()
    try:
        initial_password = os.getenv("ZY_INITIAL_ADMIN_PASSWORD", "").strip()
        if session.query(User).count() == 0 and initial_password:
            username = os.getenv("ZY_INITIAL_ADMIN_USERNAME", "zhangyong").strip() or "zhangyong"
            display_name = os.getenv("ZY_INITIAL_ADMIN_DISPLAY_NAME", "老板").strip() or "老板"
            session.add(User(username=username, display_name=display_name, password_hash=hash_password(initial_password), role="admin", is_active=True))
            session.commit()
        elif initial_password and os.getenv("ZY_SYNC_INITIAL_ADMIN_PASSWORD") == "1":
            username = os.getenv("ZY_INITIAL_ADMIN_USERNAME", "zhangyong").strip() or "zhangyong"
            user = session.query(User).filter_by(username=username).one_or_none()
            if user is not None:
                user.password_hash = hash_password(initial_password)
                session.commit()
    finally:
        session.close()


def create_app() -> FastAPI:
    init_db()
    ensure_default_admin()
    app = FastAPI(title="ZY服装发货管理系统")
    app.include_router(api_v1_router)
    app.state.login_failures = {}
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")
    spa_dir = BASE_DIR / "web" / "dist"
    if spa_dir.exists():
        app.mount("/app", StaticFiles(directory=str(spa_dir), html=True), name="app")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def root():
        return RedirectResponse("/app")

    @app.get("/login")
    def login_page(request: Request, session: Session = Depends(get_session)):
        user = current_user(request, session)
        if user:
            return RedirectResponse("/admin" if user.role == "admin" else "/mobile")
        return templates.TemplateResponse("mobile/login.html", {"request": request, "error": ""})

    @app.post("/login")
    def login(request: Request, username: str = Form(...), password: str = Form(...), session: Session = Depends(get_session)):
        key = login_key(request, username)
        if is_login_locked(request.app, key):
            return templates.TemplateResponse("mobile/login.html", {"request": request, "error": "登录失败过多，请15分钟后再试"})
        user = authenticate(session, username, password)
        if not user:
            record_failed_login(request.app, key)
            return templates.TemplateResponse("mobile/login.html", {"request": request, "error": "账号或密码错误"})
        clear_failed_login(request.app, key)
        response = RedirectResponse("/admin" if user.role == "admin" else "/mobile", status_code=303)
        response.set_cookie(SESSION_COOKIE, str(user.id), httponly=True)
        return response

    @app.get("/logout")
    def logout():
        response = RedirectResponse("/login")
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.get("/photos/shipment/{photo_id}")
    def shipment_photo(photo_id: int, request: Request, thumb: str = "", session: Session = Depends(get_session)):
        user = require_user(request, session)
        photo = session.get(ShipmentPhoto, photo_id)
        if photo is None:
            return RedirectResponse("/admin/shipments", status_code=303)
        report = session.get(ShipmentReport, photo.report_id)
        if report is None:
            return RedirectResponse("/admin/shipments", status_code=303)
        if user.role != "admin" and report.user_id != user.id:
            return RedirectResponse("/mobile/my-reports", status_code=303)
        if photo.file_path.startswith("storage://"):
            content, media_type = download_file_from_supabase_storage(photo.file_path)
            return Response(content=content, media_type=media_type)
        path = Path(photo.file_path)
        if not path.exists():
            return RedirectResponse("/admin/shipments" if user.role == "admin" else "/mobile/my-reports", status_code=303)
        if thumb == "1" and not photo.file_path.startswith("storage://"):
            return FileResponse(ensure_thumbnail(photo.file_path), filename=photo.original_name or path.name)
        return FileResponse(path, filename=photo.original_name or path.name)

    @app.get("/photos/draft/{photo_id}")
    def draft_photo(photo_id: int, request: Request, thumb: str = "", session: Session = Depends(get_session)):
        user = require_user(request, session)
        photo = session.get(PackingDraftPhoto, photo_id)
        if photo is None:
            return RedirectResponse("/mobile/report", status_code=303)
        draft = session.get(PackingDraft, photo.draft_id)
        if draft is None:
            return RedirectResponse("/mobile/report", status_code=303)
        if user.role != "admin" and draft.user_id != user.id:
            return RedirectResponse("/mobile/report", status_code=303)
        path = Path(photo.file_path)
        if not path.exists():
            return RedirectResponse("/mobile/report", status_code=303)
        if thumb == "1":
            return FileResponse(ensure_thumbnail(photo.file_path), filename=photo.original_name or path.name)
        return FileResponse(path, filename=photo.original_name or path.name)

    @app.get("/photos/return/{photo_id}")
    def return_photo(photo_id: int, request: Request, thumb: str = "", session: Session = Depends(get_session)):
        user = require_user(request, session)
        photo = session.get(ReturnReworkPhoto, photo_id)
        if photo is None:
            return RedirectResponse("/admin/orders", status_code=303)
        path = Path(photo.file_path)
        if not path.exists():
            return RedirectResponse("/admin/orders", status_code=303)
        if thumb == "1":
            return FileResponse(ensure_thumbnail(photo.file_path), filename=photo.original_name or path.name)
        return FileResponse(path, filename=photo.original_name or path.name)

    @app.get("/photos/work-info/{line_id}")
    def work_info_photo(line_id: int, request: Request, thumb: str = "", session: Session = Depends(get_session)):
        user = require_user(request, session)
        line = session.get(WorkInfoLine, line_id)
        if line is None or not line.photo_path:
            return RedirectResponse("/admin/orders" if user.role == "admin" else "/mobile/orders", status_code=303)
        path = Path(line.photo_path)
        if not path.exists():
            return RedirectResponse("/admin/orders" if user.role == "admin" else "/mobile/orders", status_code=303)
        if thumb == "1":
            return FileResponse(ensure_thumbnail(line.photo_path), filename=line.original_name or path.name)
        return FileResponse(path, filename=line.original_name or path.name)

    @app.get("/photos/work-info/proposal/{proposal_id}/{row_index}")
    def work_info_proposal_photo(proposal_id: int, row_index: int, request: Request, thumb: str = "", session: Session = Depends(get_session)):
        user = require_user(request, session)
        proposal = session.get(WorkInfoProposal, proposal_id)
        if proposal is None:
            return RedirectResponse("/admin/review" if user.role == "admin" else "/mobile/orders", status_code=303)
        rows = proposal_rows(proposal)
        if row_index < 0 or row_index >= len(rows) or not rows[row_index].get("photo_path"):
            return RedirectResponse("/admin/review" if user.role == "admin" else "/mobile/orders", status_code=303)
        path = Path(rows[row_index]["photo_path"])
        if not path.exists():
            return RedirectResponse("/admin/review" if user.role == "admin" else "/mobile/orders", status_code=303)
        if thumb == "1":
            return FileResponse(ensure_thumbnail(rows[row_index]["photo_path"]), filename=rows[row_index].get("original_name") or path.name)
        return FileResponse(path, filename=rows[row_index].get("original_name") or path.name)

    @app.get("/admin")
    def admin_dashboard(request: Request, session: Session = Depends(get_session)):
        admin = current_user(request, session)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        if admin.role != "admin":
            return RedirectResponse("/mobile/report", status_code=303)
        today = date.today().isoformat()
        balances = get_order_balances(session)
        pending = session.query(ShipmentReport).filter_by(status="pending_review").count()
        today_reports = session.query(ShipmentReport).filter_by(ship_date=today).all()
        today_total = sum(line.quantity for report in today_reports if report.status in {"auto_approved", "approved_after_edit"} for line in report.lines)
        return templates.TemplateResponse("admin/dashboard.html", {
            "request": request,
            "user": admin,
            "today": today,
            "today_total": today_total,
            "pending": pending,
            "unshipped_total": sum(max(0, row["remaining"]) for row in balances),
            "over_total": sum(row["over_shipped"] for row in balances),
            "recent": session.query(ShipmentReport).order_by(ShipmentReport.created_at.desc()).limit(12).all(),
        })

    @app.get("/admin/orders")
    def admin_orders(request: Request, company: str = "", item: str = "", edit: str = "", session: Session = Depends(get_session)):
        admin = current_user(request, session)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        if admin.role != "admin":
            return RedirectResponse("/mobile/report", status_code=303)
        all_balances = get_order_balances(session)
        companies = sorted({row["company"] for row in all_balances})
        item_text = item.strip()
        balances = [
            row
            for row in all_balances
            if (not company or row["company"] == company)
            and (not item_text or item_text == row["product"])
        ]
        balances = sort_balances_for_display(balances)
        return templates.TemplateResponse(
            "admin/orders.html",
            {
                "request": request,
                "user": admin,
                "balances": balances,
                "companies": companies,
                "selected_company": company,
                "item": item_text,
                "edit_mode": edit == "1",
                "item_choices": item_choices_with_current(all_balances, item_text),
                "recent_orders": session.query(OrderLine)
                .filter(OrderLine.is_active.is_(True))
                .order_by(OrderLine.created_at.desc(), OrderLine.id.desc())
                .limit(20)
                .all(),
            },
        )

    @app.get("/admin/work-info")
    def admin_work_info(
        request: Request,
        company: str,
        product: str,
        style: str,
        session: Session = Depends(get_session),
    ):
        admin = current_user(request, session)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        if admin.role != "admin":
            return RedirectResponse("/mobile/report", status_code=303)
        return templates.TemplateResponse(
            "admin/work_info.html",
            {
                "request": request,
                "user": admin,
                "company": company,
                "product": product,
                "style": style,
                "rows": get_work_info(session, company, product, style),
            },
        )

    @app.post("/admin/work-info")
    async def admin_save_work_info(
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
        log_operation(session, admin.id, "work_info_save", company_name, f"{product_name}/{style_name}")
        return RedirectResponse(
            f"/admin/work-info?company={company_name}&product={product_name}&style={style_name}",
            status_code=303,
        )

    @app.get("/admin/aliases")
    def admin_aliases(request: Request, session: Session = Depends(get_session)):
        admin = current_user(request, session)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        if admin.role != "admin":
            return RedirectResponse("/mobile/report", status_code=303)
        companies = [row.name for row in session.query(Company).filter(Company.is_active.is_(True)).order_by(Company.name).all()]
        return templates.TemplateResponse(
            "admin/aliases.html",
            {"request": request, "user": admin, "aliases": list_product_aliases(session), "companies": companies},
        )

    @app.get("/admin/skus")
    def admin_skus(
        request: Request,
        q: str = "",
        message: str = "",
        error: str = "",
        session: Session = Depends(get_session),
    ):
        admin = current_user(request, session)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        if admin.role != "admin":
            return RedirectResponse("/mobile/report", status_code=303)
        return templates.TemplateResponse(
            "admin/skus.html",
            {
                "request": request,
                "user": admin,
                "mappings": list_sku_mappings(session, q),
                "q": q.strip(),
                "message": message,
                "error": error,
            },
        )

    @app.post("/admin/skus/{mapping_id}/update")
    def admin_sku_update(
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
        admin = require_admin(request, session)
        upsert_sku_mapping(session, company_name, product_name, style_name, size, sku, barcode)
        log_operation(session, admin.id, "sku_update", str(mapping_id), f"{product_name}/{style_name} {size} => {sku}")
        return RedirectResponse("/admin/skus?message=SKU已保存", status_code=303)

    @app.post("/admin/skus/import")
    async def admin_sku_import(
        request: Request,
        file: UploadFile = File(...),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        target = EXPORT_DIR / f"sku_{file.filename}"
        target.write_bytes(await file.read())
        try:
            result = import_sku_mappings_from_excel(session, target)
            log_operation(session, admin.id, "sku_import", file.filename or "", f"导入{result['imported']}条，跳过{result['skipped']}条")
            return RedirectResponse(f"/admin/skus?message=已导入{result['imported']}条，跳过{result['skipped']}条", status_code=303)
        except ValueError as exc:
            return RedirectResponse(f"/admin/skus?error={exc}", status_code=303)

    @app.post("/admin/aliases/new")
    def admin_create_alias(
        request: Request,
        company_name: str = Form(...),
        alias_product: str = Form(...),
        alias_style: str = Form(...),
        canonical_product: str = Form(...),
        canonical_style: str = Form(...),
        note: str = Form(""),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        admin_id = admin.id
        create_product_alias(session, company_name, alias_product, alias_style, canonical_product, canonical_style, note)
        log_operation(session, admin_id, "alias_create", company_name, f"{alias_product}/{alias_style} => {canonical_product}/{canonical_style}")
        return RedirectResponse("/admin/aliases", status_code=303)

    @app.post("/admin/aliases/{alias_id}/update")
    def admin_update_alias(
        request: Request,
        alias_id: int,
        company_name: str = Form(...),
        alias_product: str = Form(...),
        alias_style: str = Form(...),
        canonical_product: str = Form(...),
        canonical_style: str = Form(...),
        note: str = Form(""),
        is_active: str = Form("1"),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        admin_id = admin.id
        update_product_alias(
            session,
            alias_id,
            company_name=company_name,
            alias_product=alias_product,
            alias_style=alias_style,
            canonical_product=canonical_product,
            canonical_style=canonical_style,
            note=note,
            is_active=is_active == "1",
        )
        log_operation(session, admin_id, "alias_update", company_name, f"{alias_product}/{alias_style} => {canonical_product}/{canonical_style}")
        return RedirectResponse("/admin/aliases", status_code=303)

    @app.post("/admin/orders/new")
    def admin_new_order(
        request: Request,
        company_name: str = Form(...),
        product_name: str = Form(...),
        style_name: str = Form(...),
        sizes: list[str] = Form([]),
        quantities: list[str] = Form([]),
        order_date: str = Form(""),
        delivery_date: str | None = Form(None),
        accessories: str = Form(""),
        material: str = Form(""),
        spec_size: str = Form(""),
        note: str = Form(""),
        confirm_duplicate: str = Form("0"),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        admin_id = admin.id
        lines = clean_order_lines_from_form(sizes, quantities)
        structured_note = build_structured_note(accessories, material, spec_size, note)
        duplicates = find_duplicate_order_lines(session, company_name, product_name, style_name, order_date, lines)
        if duplicates and confirm_duplicate != "1":
            choices = get_order_choices(session)
            balances = get_order_balances(session)
            companies = sorted({row["company"] for row in balances})
            return templates.TemplateResponse(
                "admin/new_order.html",
                {
                    "request": request,
                    "user": admin,
                    "choices": choices,
                    "companies": companies,
                    "duplicates": duplicates,
                    "today": date.today().isoformat(),
                    "form_data": {
                        "company_name": company_name,
                        "product_name": product_name,
                        "style_name": style_name,
                        "sizes": sizes,
                        "quantities": quantities,
                        "order_date": order_date,
                        "delivery_date": delivery_date,
                        "accessories": accessories,
                        "material": material,
                        "spec_size": spec_size,
                        "note": note,
                    },
                },
            )
        created = create_order_lines_batch(session, company_name, product_name, style_name, lines, order_date, delivery_date, structured_note)
        log_operation(session, admin_id, "order_create_batch", company_name, f"{style_name} {len(created)}个尺码 合计{sum(line['quantity'] for line in lines)}")
        return RedirectResponse("/admin/orders", status_code=303)

    @app.get("/admin/orders/new")
    def admin_new_order_page(request: Request, session: Session = Depends(get_session)):
        admin = current_user(request, session)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        if admin.role != "admin":
            return RedirectResponse("/mobile", status_code=303)
        balances = get_order_balances(session)
        companies = sorted({row["company"] for row in balances})
        return templates.TemplateResponse(
            "admin/new_order.html",
            {
                "request": request,
                "user": admin,
                "choices": get_order_choices(session),
                "companies": companies,
                "duplicates": [],
                "today": date.today().isoformat(),
                "form_data": {},
            },
        )

    @app.post("/admin/orders/{order_id}/update")
    def admin_update_order(
        request: Request,
        order_id: int,
        product_name: str = Form(...),
        style_name: str = Form(...),
        size: str = Form(...),
        quantity: int = Form(...),
        order_date: str = Form(""),
        delivery_date: str = Form(""),
        note: str = Form(""),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        update_order_line(
            session,
            order_id,
            product_name=product_name,
            style_name=style_name,
            size=size,
            quantity=quantity,
            order_date=order_date,
            delivery_date=delivery_date,
            note=note,
        )
        log_operation(session, admin.id, "order_update", str(order_id), f"{style_name} {size} {quantity}")
        return RedirectResponse("/admin/orders", status_code=303)

    @app.post("/admin/orders/batch-update")
    def admin_batch_update_orders(
        request: Request,
        order_ids: list[int] = Form(...),
        company_names: list[str] = Form(...),
        product_names: list[str] = Form(...),
        style_names: list[str] = Form(...),
        order_dates: list[str] = Form(...),
        sizes: list[str] = Form(...),
        skus: list[str] = Form([]),
        quantities: list[int] = Form(...),
        notes: list[str] = Form(...),
        return_company: str = Form(""),
        return_item: str = Form(""),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        updated = 0
        for index, order_id in enumerate(order_ids):
            update_order_line(
                session,
                order_id,
                company_name=company_names[index],
                product_name=product_names[index],
                style_name=style_names[index],
                order_date=order_dates[index],
                size=sizes[index],
                quantity=quantities[index],
                note=notes[index],
                sku=skus[index] if index < len(skus) else None,
            )
            sku = skus[index] if index < len(skus) else ""
            upsert_sku_mapping(session, company_names[index], product_names[index], style_names[index], sizes[index], sku)
            updated += 1
        log_operation(session, admin.id, "order_batch_update", "订单查询", f"批量修改{updated}条")
        query = urlencode({key: value for key, value in {"company": return_company, "item": return_item}.items() if value})
        target = f"/admin/orders?{query}" if query else "/admin/orders"
        return RedirectResponse(target, status_code=303)

    @app.post("/admin/orders/{order_id}/delete")
    def admin_delete_order(request: Request, order_id: int, session: Session = Depends(get_session)):
        admin = require_admin(request, session)
        delete_order_line(session, order_id)
        log_operation(session, admin.id, "order_delete", str(order_id), "")
        return RedirectResponse("/admin/orders", status_code=303)

    @app.get("/admin/order-lines/{line_id}")
    def admin_order_line_detail(request: Request, line_id: int, session: Session = Depends(get_session)):
        admin = current_user(request, session)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        if admin.role != "admin":
            return RedirectResponse("/mobile/report", status_code=303)
        order = session.get(OrderLine, line_id)
        if order is None or not order.is_active:
            return RedirectResponse("/admin/orders", status_code=303)
        shipments = (
            session.query(ShipmentReport, ShipmentLine)
            .join(ShipmentLine, ShipmentLine.report_id == ShipmentReport.id)
            .filter(
                ShipmentLine.order_line_id == line_id,
                ShipmentReport.status.in_(("auto_approved", "approved_after_edit")),
            )
            .order_by(ShipmentReport.ship_date.desc(), ShipmentReport.id.desc())
            .all()
        )
        return templates.TemplateResponse(
            "admin/order_line.html",
            {
                "request": request,
                "user": admin,
                "order": order,
                "totals": order_line_totals(session, line_id),
                "ledger": session.query(OrderLedgerEntry)
                .filter_by(order_line_id=line_id)
                .order_by(OrderLedgerEntry.created_at.desc(), OrderLedgerEntry.id.desc())
                .all(),
                "returns": list_return_reworks(session, line_id),
                "adjustments": list_adjustments(session, line_id),
                "closes": list_closes(session, line_id),
                "comments": session.query(OrderLineComment)
                .filter_by(order_line_id=line_id)
                .order_by(OrderLineComment.created_at.desc(), OrderLineComment.id.desc())
                .all(),
                "shipments": shipments,
            },
        )

    @app.post("/admin/order-lines/{line_id}/returns")
    async def admin_order_line_add_return(
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
        paths = await save_uploads(photos)
        create_return_rework(session, line_id, admin.id, quantity, reason_type, reason, status, photo_paths=paths)
        log_operation(session, admin.id, "return_create", str(line_id), f"{reason_type} {quantity}件 {reason}")
        return RedirectResponse(f"/admin/order-lines/{line_id}", status_code=303)

    @app.post("/admin/order-lines/{line_id}/returns/{return_id}/status")
    def admin_order_line_return_status(
        request: Request,
        line_id: int,
        return_id: int,
        status: str = Form(...),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        set_return_rework_status(session, return_id, status)
        log_operation(session, admin.id, "return_status", str(line_id), f"返工状态改为 {status}")
        return RedirectResponse(f"/admin/order-lines/{line_id}", status_code=303)

    @app.post("/admin/order-lines/{line_id}/adjustments")
    def admin_order_line_add_adjustment(
        request: Request,
        line_id: int,
        quantity: int = Form(...),
        reason: str = Form(""),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        create_order_adjustment(session, line_id, admin.id, quantity, reason)
        log_operation(session, admin.id, "adjustment_create", str(line_id), f"调整 {quantity}件 {reason}")
        return RedirectResponse(f"/admin/order-lines/{line_id}", status_code=303)

    @app.post("/admin/order-lines/{line_id}/closes")
    def admin_order_line_add_close(
        request: Request,
        line_id: int,
        quantity: int = Form(...),
        reason: str = Form(""),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        create_order_line_close(session, line_id, admin.id, quantity, reason)
        log_operation(session, admin.id, "close_create", str(line_id), f"关闭 {quantity}件 {reason}")
        return RedirectResponse(f"/admin/order-lines/{line_id}", status_code=303)

    @app.post("/admin/order-lines/{line_id}/comments")
    def admin_order_line_add_comment(
        request: Request,
        line_id: int,
        content: str = Form(...),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        content = content.strip()
        if content:
            session.add(OrderLineComment(order_line_id=line_id, user_id=admin.id, content=content))
            session.commit()
            log_operation(session, admin.id, "comment_create", str(line_id), content)
        return RedirectResponse(f"/admin/order-lines/{line_id}", status_code=303)

    @app.post("/admin/orders/import")
    async def admin_import_orders(request: Request, file: UploadFile = File(...), session: Session = Depends(get_session)):
        admin = require_admin(request, session)
        target = EXPORT_DIR / f"import_{file.filename}"
        target.write_bytes(await file.read())
        result = import_excel_orders(session, target)
        log_operation(session, admin.id, "order_import", file.filename or "", f"导入{result['imported']}条，错误{len(result['errors'])}条")
        return templates.TemplateResponse("admin/import_result.html", {"request": request, "result": result})

    @app.get("/admin/review")
    def admin_review(request: Request, page: int = 1, session: Session = Depends(get_session)):
        admin = current_user(request, session)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        if admin.role != "admin":
            return RedirectResponse("/mobile/report", status_code=303)
        query = session.query(ShipmentReport).filter_by(status="pending_review").order_by(ShipmentReport.created_at.desc(), ShipmentReport.id.desc())
        per_page = 10
        total = query.count()
        page = max(1, page)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)
        reports = query.offset((page - 1) * per_page).limit(per_page).all()
        return templates.TemplateResponse(
            "admin/review.html",
            {
                "request": request,
                "user": admin,
                "reports": reports,
                "work_info_proposals": pending_work_info_proposals(session),
                "page": page,
                "total_pages": total_pages,
                "total": total,
            },
        )

    @app.post("/admin/review/{report_id}/approve")
    def admin_approve(request: Request, report_id: int, note: str = Form(""), session: Session = Depends(get_session)):
        admin = require_admin(request, session)
        try:
            approve_report(session, report_id, admin.id, note)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        log_operation(session, admin.id, "shipment_approve", str(report_id), note)
        return RedirectResponse("/admin/review", status_code=303)

    @app.post("/admin/review/{report_id}/reject")
    def admin_reject(request: Request, report_id: int, note: str = Form(""), session: Session = Depends(get_session)):
        admin = require_admin(request, session)
        try:
            reject_report(session, report_id, admin.id, note)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        log_operation(session, admin.id, "shipment_reject", str(report_id), note)
        return RedirectResponse("/admin/review", status_code=303)

    @app.post("/admin/work-info/proposals/{proposal_id}/approve")
    def admin_approve_work_info_proposal(request: Request, proposal_id: int, note: str = Form(""), session: Session = Depends(get_session)):
        admin = require_admin(request, session)
        proposal = approve_work_info_proposal(session, proposal_id, admin.id, note)
        log_operation(session, admin.id, "work_info_approve", str(proposal_id), f"{proposal.company_name}/{proposal.style_name}")
        return RedirectResponse("/admin/review", status_code=303)

    @app.post("/admin/work-info/proposals/{proposal_id}/reject")
    def admin_reject_work_info_proposal(request: Request, proposal_id: int, note: str = Form(""), session: Session = Depends(get_session)):
        admin = require_admin(request, session)
        proposal = reject_work_info_proposal(session, proposal_id, admin.id, note)
        log_operation(session, admin.id, "work_info_reject", str(proposal_id), f"{proposal.company_name}/{proposal.style_name}")
        return RedirectResponse("/admin/review", status_code=303)

    @app.get("/admin/shipments")
    def admin_shipments(
        request: Request,
        company: str = "",
        waybill: str = "",
        page: int = 1,
        session: Session = Depends(get_session),
    ):
        admin = current_user(request, session)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        if admin.role != "admin":
            return RedirectResponse("/mobile/report", status_code=303)
        query = session.query(ShipmentReport).order_by(ShipmentReport.created_at.desc(), ShipmentReport.id.desc())
        companies = [
            row[0]
            for row in session.query(ShipmentReport.company_name)
            .distinct()
            .order_by(ShipmentReport.company_name)
            .all()
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
        return templates.TemplateResponse(
            "admin/shipments.html",
            {
                "request": request,
                "user": admin,
                "reports": reports,
                "companies": companies,
                "selected_company": company,
                "waybill": waybill.strip(),
                "page": page,
                "total_pages": total_pages,
                "total": total,
            },
        )

    @app.post("/admin/shipments/{report_id}/waybill")
    def admin_update_shipment_waybill(
        request: Request,
        report_id: int,
        waybill_no: str = Form(""),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        report = session.get(ShipmentReport, report_id)
        if report is None:
            return RedirectResponse("/admin/shipments", status_code=303)
        report.waybill_no = waybill_no.strip()
        session.commit()
        log_operation(session, admin.id, "waybill_update", str(report_id), waybill_no.strip())
        return RedirectResponse("/admin/shipments", status_code=303)

    @app.post("/admin/shipments/{report_id}/photos")
    async def admin_upload_shipment_photos(
        request: Request,
        report_id: int,
        photos: list[UploadFile] = File([]),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        report = session.get(ShipmentReport, report_id)
        if report is None:
            return RedirectResponse("/admin/shipments", status_code=303)
        try:
            upload_date = date.fromisoformat(report.ship_date)
        except ValueError:
            upload_date = date.today()
        try:
            paths = await save_uploads(
                photos,
                company_name=report.company_name,
                style_name=report.style_name,
                upload_date=upload_date,
            )
        except ValueError as exc:
            return RedirectResponse(f"/admin/shipments?error={exc}", status_code=303)
        for path in paths:
            session.add(ShipmentPhoto(report_id=report.id, file_path=path, original_name=Path(path).name))
        session.commit()
        log_operation(session, admin.id, "shipment_photo_upload", str(report_id), f"补传{len(paths)}张照片")
        return RedirectResponse("/admin/shipments", status_code=303)

    @app.get("/admin/daily-stats")
    def admin_daily_stats(request: Request, ship_date: str = "", session: Session = Depends(get_session)):
        admin = current_user(request, session)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        if admin.role != "admin":
            return RedirectResponse("/mobile/report", status_code=303)
        target_date = ship_date or date.today().isoformat()
        rows = daily_shipment_stats(session, target_date)
        return templates.TemplateResponse(
            "admin/daily_stats.html",
            {
                "request": request,
                "user": admin,
                "ship_date": target_date,
                "rows": rows,
                "total": sum(row["quantity"] for row in rows),
            },
        )

    @app.get("/mobile/daily-stats")
    def mobile_daily_stats(request: Request, ship_date: str = "", session: Session = Depends(get_session)):
        user = current_user(request, session)
        if not user:
            return RedirectResponse("/login", status_code=303)
        target_date = ship_date or date.today().isoformat()
        rows = daily_shipment_stats(session, target_date)
        return templates.TemplateResponse(
            "mobile/daily_stats.html",
            {
                "request": request,
                "user": user,
                "ship_date": target_date,
                "rows": rows,
                "total": sum(row["quantity"] for row in rows),
            },
        )

    @app.get("/admin/logs")
    def admin_operation_logs(request: Request, session: Session = Depends(get_session)):
        admin = current_user(request, session)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        if admin.role != "admin":
            return RedirectResponse("/mobile/report", status_code=303)
        return templates.TemplateResponse(
            "admin/logs.html",
            {"request": request, "user": admin, "logs": recent_operation_logs(session)},
        )

    @app.get("/admin/export")
    def admin_export_page(request: Request, session: Session = Depends(get_session)):
        admin = current_user(request, session)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        if admin.role != "admin":
            return RedirectResponse("/mobile/report", status_code=303)
        companies = sorted({row["company"] for row in get_order_balances(session)})
        return templates.TemplateResponse("admin/export.html", {"request": request, "user": admin, "companies": companies, "today": date.today().isoformat()})

    @app.get("/admin/waybills")
    def admin_waybills(request: Request, message: str = "", error: str = "", session: Session = Depends(get_session)):
        admin = current_user(request, session)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        if admin.role != "admin":
            return RedirectResponse("/mobile", status_code=303)
        from app.models import Company, WaybillPhoto
        from sqlalchemy import func

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
        return templates.TemplateResponse(
            "admin/waybills.html",
            {
                "request": request,
                "user": admin,
                "companies": companies,
                "counts": counts,
                "photos": photos,
                "message": message,
                "error": error,
                "default_folder": r"C:\Users\Administrator\Desktop\中通快递单",
                "today": date.today().isoformat(),
            },
        )

    @app.post("/admin/waybills/import-folder")
    def admin_import_waybill_folder(
        request: Request,
        folder_path: str = Form(...),
        waybill_date: str = Form(""),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        try:
            result = import_waybill_directory(session, Path(folder_path), uploaded_by=admin.id, waybill_date=waybill_date)
            log_operation(session, admin.id, "waybill_import_folder", folder_path, f"导入{result['imported']}张，跳过{result['skipped']}张")
            return RedirectResponse(
                f"/admin/waybills?message=已导入{result['imported']}张，跳过{result['skipped']}张",
                status_code=303,
            )
        except ValueError as exc:
            return RedirectResponse(f"/admin/waybills?error={exc}", status_code=303)

    @app.post("/admin/waybills/upload")
    async def admin_upload_waybills(
        request: Request,
        company: str = Form(...),
        waybill_date: str = Form(""),
        files: list[UploadFile] = File([]),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        result = await save_waybill_uploads(session, company, files, uploaded_by=admin.id, waybill_date=waybill_date)
        log_operation(session, admin.id, "waybill_upload", company, f"上传{result['imported']}张，跳过{result['skipped']}张")
        return RedirectResponse(
            f"/admin/waybills?message=已上传{result['imported']}张，跳过{result['skipped']}张",
            status_code=303,
        )

    @app.post("/admin/waybills/{photo_id}/date")
    def admin_update_waybill_date(
        request: Request,
        photo_id: int,
        waybill_date: str = Form(""),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        photo = update_waybill_date(session, photo_id, waybill_date)
        log_operation(session, admin.id, "waybill_update_date", photo.company_name, f"面单日期改为{photo.waybill_date or '空'}")
        return RedirectResponse("/admin/waybills?message=面单日期已保存", status_code=303)

    @app.get("/admin/goals")
    def admin_goals(request: Request, goal_date: str = "", session: Session = Depends(get_session)):
        admin = current_user(request, session)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        if admin.role != "admin":
            return RedirectResponse("/mobile", status_code=303)
        target_date = goal_date or date.today().isoformat()
        goals = get_daily_goals(session, target_date)
        return templates.TemplateResponse(
            "admin/goals.html",
            {
                "request": request,
                "user": admin,
                "goal_date": target_date,
                "goal_text": "\n".join(goal.content for goal in goals),
            },
        )

    @app.post("/admin/goals")
    def admin_save_goals(
        request: Request,
        goal_date: str = Form(...),
        goal_text: str = Form(""),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        set_daily_goals(session, goal_date, goal_text.splitlines(), admin.id)
        log_operation(session, admin.id, "daily_goal_update", goal_date, goal_text)
        return RedirectResponse(f"/admin/goals?goal_date={goal_date}", status_code=303)

    @app.get("/admin/users")
    def admin_users(request: Request, message: str = "", error: str = "", session: Session = Depends(get_session)):
        admin = current_user(request, session)
        if not admin:
            return RedirectResponse("/login", status_code=303)
        if admin.role != "admin":
            return RedirectResponse("/mobile/report", status_code=303)
        users = session.query(User).order_by(User.role, User.username).all()
        return templates.TemplateResponse("admin/users.html", {"request": request, "user": admin, "users": users, "message": message, "error": error})

    @app.post("/admin/users/new")
    def admin_create_user(
        request: Request,
        username: str = Form(...),
        display_name: str = Form(...),
        password: str = Form(...),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        try:
            create_worker_user(session, username, display_name, password)
            log_operation(session, admin.id, "user_create", username, display_name)
            return RedirectResponse("/admin/users?message=账号已新增", status_code=303)
        except ValueError as exc:
            return RedirectResponse(f"/admin/users?error={exc}", status_code=303)

    @app.post("/admin/users/{user_id}/password")
    def admin_change_password(
        request: Request,
        user_id: int,
        password: str = Form(...),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        try:
            set_user_password(session, user_id, password)
            log_operation(session, admin.id, "user_password", str(user_id), "修改密码")
            return RedirectResponse("/admin/users?message=密码已修改", status_code=303)
        except ValueError as exc:
            return RedirectResponse(f"/admin/users?error={exc}", status_code=303)

    @app.post("/admin/users/{user_id}/update")
    def admin_update_user(
        request: Request,
        user_id: int,
        username: str = Form(...),
        display_name: str = Form(...),
        role: str = Form(...),
        is_active: str = Form("0"),
        session: Session = Depends(get_session),
    ):
        admin = require_admin(request, session)
        try:
            update_user_profile(
                session,
                user_id,
                username=username,
                display_name=display_name,
                role=role,
                is_active=is_active == "1",
            )
            log_operation(session, admin.id, "user_update", str(user_id), f"{username} {display_name} {role} active={is_active}")
            return RedirectResponse("/admin/users?message=账号资料已修改", status_code=303)
        except ValueError as exc:
            return RedirectResponse(f"/admin/users?error={exc}", status_code=303)

    @app.post("/admin/export")
    def admin_export(request: Request, export_type: str = Form("company"), company: str = Form(""), ship_date: str = Form(""), template: str = Form("customer"), session: Session = Depends(get_session)):
        admin = require_admin(request, session)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if company == "__all__":
            if template == "internal":
                path = export_total_workbook(session, EXPORT_DIR / f"ZY服装内部版发货总表_{stamp}.xlsx")
            else:
                path = export_customer_total_workbook(session, EXPORT_DIR / f"ZY服装客户版发货总表_{stamp}.xlsx")
        elif export_type == "unshipped":
            path = export_unshipped_workbook(session, EXPORT_DIR / f"未发货表_{stamp}.xlsx")
        elif export_type == "company":
            if template == "internal":
                path = export_company_workbook(session, company, EXPORT_DIR / f"{company}_内部版订单发货表_{stamp}.xlsx")
            else:
                path = export_customer_company_workbook(session, company, EXPORT_DIR / f"{company}_客户版发货表_{stamp}.xlsx")
        elif export_type == "daily":
            path = export_daily_shipments_workbook(session, ship_date, EXPORT_DIR / f"{ship_date}_发货明细.xlsx")
        else:
            path = export_total_workbook(session, EXPORT_DIR / f"ZY服装发货总表_{stamp}.xlsx")
        target = "全部公司" if company == "__all__" else (company or ship_date or "导出")
        log_operation(session, admin.id, f"export_{template}", target, Path(path).name)
        return FileResponse(path, filename=Path(path).name)

    @app.get("/mobile/login")
    def mobile_login(request: Request):
        return templates.TemplateResponse("mobile/login.html", {"request": request, "error": ""})

    @app.get("/mobile")
    def mobile_home(request: Request, session: Session = Depends(get_session)):
        user = current_user(request, session)
        if not user:
            return RedirectResponse("/login", status_code=303)
        today = date.today().isoformat()
        previous_day = (date.today() - timedelta(days=1)).isoformat()
        goals = get_daily_goals(session, today)
        previous_reports = (
            session.query(ShipmentReport)
            .filter(
                ShipmentReport.ship_date == previous_day,
                ShipmentReport.status.in_(("auto_approved", "approved_after_edit")),
            )
            .order_by(ShipmentReport.created_at.desc())
            .all()
        )
        return templates.TemplateResponse(
            "mobile/home.html",
            {
                "request": request,
                "user": user,
                "today": today,
                "previous_day": previous_day,
                "goals": goals,
                "previous_reports": previous_reports,
            },
        )

    @app.get("/mobile/today")
    def mobile_today(request: Request, session: Session = Depends(get_session)):
        return RedirectResponse("/mobile/report", status_code=303)

    @app.get("/mobile/report")
    def mobile_report(request: Request, session: Session = Depends(get_session)):
        user = current_user(request, session)
        if not user:
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse("mobile/report.html", mobile_report_page_context(request, user, session))

    @app.get("/mobile/report/options")
    def mobile_report_options(
        request: Request,
        company: str = "",
        product: str = "",
        style: str = "",
        order_id: int | None = None,
        session: Session = Depends(get_session),
    ):
        user = current_user(request, session)
        if not user:
            return JSONResponse({"detail": "请先登录"}, status_code=401)
        if order_id:
            try:
                return formal_order_lines_payload(session, order_id)
            except ValueError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=404)
        return mobile_report_options_payload(session, company.strip(), product.strip(), style.strip())

    @app.get("/mobile/report/huolala-trips")
    def mobile_report_huolala_trips(
        request: Request,
        company: str = "",
        ship_date: str = "",
        session: Session = Depends(get_session),
    ):
        user = current_user(request, session)
        if not user:
            return JSONResponse({"detail": "请先登录"}, status_code=401)
        return JSONResponse({"trips": huolala_trip_options_payload(session, company, ship_date)})

    @app.get("/mobile/report/scan")
    def mobile_report_scan(
        request: Request,
        code: str = "",
        session: Session = Depends(get_session),
    ):
        user = require_user(request, session)
        mapping = barcode_lookup(session, code)
        if mapping is None:
            return JSONResponse({"detail": "未找到该条码对应的款式"})
        return JSONResponse(
            {
                "company": mapping.company_name,
                "product": mapping.product_name,
                "style": mapping.style_name,
            }
        )

    @app.post("/mobile/today/new")
    async def mobile_today_new(
        request: Request,
        pack_date: str = Form(...),
        order_id: int | None = Form(None),
        company_name: str = Form(""),
        product_name: str = Form(""),
        style_name: str = Form(""),
        sizes: list[str] = Form([]),
        order_line_ids: list[str] = Form([]),
        quantities: list[str] = Form([]),
        note: str = Form(""),
        shipping_method: str = Form(""),
        trip_mode: str = Form("new"),
        waybill_no: str = Form(""),
        package_count: str = Form(""),
        weight_kg: str = Form(""),
        session: Session = Depends(get_session),
    ):
        user = require_user(request, session)
        if order_id is None and session.query(SalesOrder.id).filter(SalesOrder.status == "active").first():
            raise HTTPException(status_code=400, detail="请选择订单号")
        lines = [
            {"size": size, "quantity": qty, "order_line_id": order_line_ids[index] if index < len(order_line_ids) else ""}
            for index, (size, qty) in enumerate(zip(sizes, quantities))
            if size and qty
        ]
        try:
            create_packing_draft(
                session,
                user.id,
                pack_date,
                company_name,
                product_name,
                style_name,
                lines,
                note,
                [],
                waybill_no,
                order_id=order_id,
                shipping_method=shipping_method,
                package_count=package_count,
                weight_kg=weight_kg,
                trip_mode=trip_mode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse("/mobile/today", status_code=303)

    @app.post("/mobile/today/{report_id}/update")
    async def mobile_today_update(
        request: Request,
        report_id: int,
        pack_date: str = Form(""),
        sizes: list[str] = Form([]),
        order_line_ids: list[str] = Form([]),
        quantities: list[str] = Form([]),
        note: str = Form(""),
        shipping_method: str = Form(""),
        trip_mode: str = Form("new"),
        waybill_no: str = Form(""),
        package_count: str = Form(""),
        weight_kg: str = Form(""),
        session: Session = Depends(get_session),
    ):
        user = require_user(request, session)
        lines = [
            {"size": size, "quantity": qty, "order_line_id": order_line_ids[index] if index < len(order_line_ids) else ""}
            for index, (size, qty) in enumerate(zip(sizes, quantities))
            if size and qty
        ]
        try:
            update_packing_draft(
                session,
                report_id,
                user.id,
                lines,
                note,
                [],
                waybill_no,
                shipping_method=shipping_method,
                package_count=package_count,
                weight_kg=weight_kg,
                pack_date=pack_date,
                trip_mode=trip_mode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse("/mobile/today", status_code=303)

    @app.post("/mobile/today/{report_id}/delete")
    def mobile_today_delete(request: Request, report_id: int, session: Session = Depends(get_session)):
        user = require_user(request, session)
        delete_packing_draft(session, report_id, user.id)
        return RedirectResponse("/mobile/today", status_code=303)

    @app.post("/mobile/today/{report_id}/submit")
    def mobile_today_submit(request: Request, report_id: int, session: Session = Depends(get_session)):
        user = require_user(request, session)
        try:
            submit_packing_draft(session, report_id, user.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse("/mobile/today", status_code=303)

    @app.get("/admin/packing/{draft_id}/print")
    def admin_packing_print(request: Request, draft_id: int, session: Session = Depends(get_session)):
        admin = require_admin(request, session)
        draft = session.get(PackingDraft, draft_id)
        if draft is None:
            return RedirectResponse("/admin/shipments", status_code=303)
        return templates.TemplateResponse("packing_print.html", {"request": request, "draft": draft})

    @app.get("/mobile/packing/{draft_id}/print")
    def mobile_packing_print(request: Request, draft_id: int, session: Session = Depends(get_session)):
        user = require_user(request, session)
        draft = session.get(PackingDraft, draft_id)
        if draft is None:
            return RedirectResponse("/mobile/report", status_code=303)
        if user.role != "admin" and draft.user_id != user.id:
            return RedirectResponse("/mobile/report", status_code=303)
        return templates.TemplateResponse("packing_print.html", {"request": request, "draft": draft})

    @app.get("/mobile/orders")
    def mobile_orders(
        request: Request,
        company: str = "",
        item: str = "",
        style: str = "",
        status: str = "",
        page: int = 1,
        partial: str = "",
        session: Session = Depends(get_session),
    ):
        user = current_user(request, session)
        if not user:
            return RedirectResponse("/login", status_code=303)
        all_balances = worker_visible_balances(session)
        companies = sorted({row["company"] for row in all_balances})
        item_text = item.strip()
        style_text = style.strip()
        status_text = status.strip() or "all"
        balances = [
            row
            for row in all_balances
            if (not company or row["company"] == company)
            and (not item_text or item_text == row["product"])
            and (not style_text or style_text == row["style"])
            and _matches_order_status(row, status_text)
        ]
        balances = sort_balances_for_display(balances)
        reports_query = session.query(ShipmentReport).order_by(ShipmentReport.created_at.desc(), ShipmentReport.id.desc())
        reports_per_page = 10
        reports_total = reports_query.count()
        reports_page = max(1, page)
        has_more_reports = reports_page * reports_per_page < reports_total
        reports = reports_query.offset((reports_page - 1) * reports_per_page).limit(reports_per_page).all()
        style_choices = sorted({row["style"] for row in all_balances if (not company or row["company"] == company) and (not item_text or item_text == row["product"])})
        context = {
            "request": request,
            "user": user,
            "companies": companies,
            "selected_company": company,
            "balances": balances,
            "reports": reports,
            "item": item_text,
            "style": style_text,
            "style_choices": style_choices,
            "status": status_text,
            "item_choices": item_choices_with_current(all_balances, item_text),
            "reports_page": reports_page,
            "has_more_reports": has_more_reports,
        }
        if partial == "1":
            response = templates.TemplateResponse("mobile/orders_reports_items.html", context)
            response.headers["X-Has-More"] = "1" if has_more_reports else "0"
            return response
        return templates.TemplateResponse("mobile/orders.html", context)

    @app.get("/mobile/work-info")
    def mobile_work_info(
        request: Request,
        company: str,
        product: str,
        style: str,
        session: Session = Depends(get_session),
    ):
        user = current_user(request, session)
        if not user:
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(
            "mobile/work_info.html",
            {
                "request": request,
                "user": user,
                "company": company,
                "product": product,
                "style": style,
                "rows": get_work_info(session, company, product, style),
                "message": "",
            },
        )

    @app.post("/mobile/work-info")
    async def mobile_submit_work_info_proposal(
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
        user = require_user(request, session)
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
        create_work_info_proposal(session, user.id, company_name, product_name, style_name, rows)
        return templates.TemplateResponse(
            "mobile/work_info.html",
            {
                "request": request,
                "user": user,
                "company": company_name,
                "product": product_name,
                "style": style_name,
                "rows": get_work_info(session, company_name, product_name, style_name),
                "message": "已提交老板审核",
            },
        )

    @app.post("/mobile/report")
    def mobile_submit_report(request: Request, session: Session = Depends(get_session)):
        require_user(request, session)
        raise HTTPException(status_code=410, detail="该提交入口已停用，请先保存包货草稿再提交")

    @app.get("/mobile/my-reports")
    def mobile_my_reports(request: Request, page: int = 1, partial: str = "", session: Session = Depends(get_session)):
        user = current_user(request, session)
        if not user:
            return RedirectResponse("/login", status_code=303)
        query = session.query(ShipmentReport).filter_by(user_id=user.id).order_by(ShipmentReport.created_at.desc(), ShipmentReport.id.desc())
        per_page = 10
        total = query.count()
        page = max(1, page)
        has_more = page * per_page < total
        reports = query.offset((page - 1) * per_page).limit(per_page).all()
        context = {"request": request, "user": user, "reports": reports, "page": page, "has_more": has_more}
        if partial == "1":
            response = templates.TemplateResponse("mobile/my_reports_items.html", context)
            response.headers["X-Has-More"] = "1" if has_more else "0"
            return response
        return templates.TemplateResponse("mobile/my_reports.html", context)

    @app.post("/mobile/my-reports/{report_id}/update")
    async def mobile_update_my_report(
        request: Request,
        report_id: int,
        line_ids: list[str] = Form([]),
        sizes: list[str] = Form([]),
        quantities: list[str] = Form([]),
        note: str = Form(""),
        photos: list[UploadFile] = File([]),
        session: Session = Depends(get_session),
    ):
        user = current_user(request, session)
        if not user:
            return RedirectResponse("/login", status_code=303)
        report = session.get(ShipmentReport, report_id)
        if report is None or report.user_id != user.id:
            return RedirectResponse("/mobile/my-reports", status_code=303)
        try:
            ensure_report_not_archived(session, report)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        updates = []
        for index, (size, quantity_text) in enumerate(zip(sizes, quantities)):
            clean_size = str(size or "").strip()
            quantity = parse_quantity(quantity_text)
            if not clean_size or quantity <= 0:
                continue
            line_id = line_ids[index] if index < len(line_ids) else ""
            updates.append({"line_id": line_id, "size": clean_size, "quantity": quantity})
        if not updates:
            return RedirectResponse("/mobile/my-reports", status_code=303)

        try:
            upload_date = date.fromisoformat(report.ship_date)
        except ValueError:
            upload_date = date.today()
        try:
            paths = await save_uploads(
                photos,
                company_name=report.company_name,
                style_name=report.style_name,
                upload_date=upload_date,
            )
        except ValueError as exc:
            reports = session.query(ShipmentReport).filter_by(user_id=user.id).order_by(ShipmentReport.created_at.desc()).limit(100).all()
            return templates.TemplateResponse("mobile/my_reports.html", {"request": request, "user": user, "reports": reports, "error": str(exc)})

        before_lines = [{"size": line.size, "quantity": line.quantity} for line in report.lines]
        existing_lines = {line.id: line for line in report.lines}
        for update in updates:
            try:
                parsed_line_id = int(update["line_id"] or 0)
            except ValueError:
                parsed_line_id = 0
            line = existing_lines.get(parsed_line_id)
            if line is None:
                order_line_id = resolve_order_line_id(
                    session,
                    report.company_name,
                    report.product_name,
                    report.style_name,
                    update["size"],
                )
                session.add(ShipmentLine(report_id=report.id, order_line_id=order_line_id, size=update["size"], quantity=update["quantity"]))
            else:
                if str(line.size or "").strip() != update["size"]:
                    line.order_line_id = resolve_order_line_id(
                        session,
                        report.company_name,
                        report.product_name,
                        report.style_name,
                        update["size"],
                        preferred=line.order_line_id,
                    )
                line.size = update["size"]
                line.quantity = update["quantity"]
        for path in paths:
            session.add(ShipmentPhoto(report_id=report.id, file_path=path, original_name=Path(path).name))
        report.note = note.strip()
        report.status = "pending_review"
        report.review_reason = "员工提交更新，等待老板审核"
        after_lines = [{"size": line.size, "quantity": line.quantity} for line in report.lines]
        session.add(
            AuditLog(
                report_id=report.id,
                admin_id=user.id,
                action="worker_update",
                before_text=json.dumps(before_lines, ensure_ascii=False),
                after_text=json.dumps(after_lines, ensure_ascii=False),
                note=f"员工更新，补录{len(paths)}张照片",
            )
        )
        session.commit()
        recompute_for_report(session, report.id)
        log_operation(session, user.id, "shipment_worker_update", str(report_id), f"更新发货记录，补录{len(paths)}张照片")
        return RedirectResponse("/mobile/my-reports", status_code=303)

    return app


app = create_app()
