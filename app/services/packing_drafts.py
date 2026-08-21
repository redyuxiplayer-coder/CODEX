from datetime import date
from pathlib import Path

from sqlalchemy.exc import IntegrityError

from app.models import OrderLine, PackingDraft, PackingDraftLine, PackingDraftPhoto, SalesOrder
from app.services.ledger import recompute_for_report
from app.services.logistics import create_waybill_record, matching_waybill_or_none, shipping_method_label
from app.services.order_archives import get_open_archive
from app.services.quantities import parse_quantity
from app.services.shipments import submit_shipment_report


def _next_package_no(session, pack_date: str) -> str:
    count = session.query(PackingDraft).filter_by(pack_date=pack_date).count()
    compact = str(pack_date or "").replace("-", "")
    return f"PKG-{compact}-{count + 1:03d}"


def _clean_lines(lines: list[dict]) -> list[dict]:
    cleaned = []
    for line in lines:
        size = str(line.get("size", "")).strip()
        quantity = parse_quantity(line.get("quantity"))
        order_line_id = line.get("order_line_id") or None
        if size and quantity > 0:
            cleaned.append({"size": size, "quantity": quantity, "order_line_id": int(order_line_id) if order_line_id else None})
    return cleaned


def _validate_formal_order_lines(session, order: SalesOrder, lines: list[dict]) -> None:
    for line in lines:
        order_line = session.get(OrderLine, line.get("order_line_id")) if line.get("order_line_id") else None
        if order_line is None or order_line.order_id != order.id or order_line.size != line["size"]:
            raise ValueError("包货尺码不属于所选订单")


def _validate_pack_date(pack_date: str) -> str:
    text = str(pack_date or "").strip()
    if not text:
        raise ValueError("请填写发货日期")
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("发货日期格式不正确") from exc
    if parsed > date.today():
        raise ValueError("发货日期不能晚于今天")
    return parsed.isoformat()


def _parse_package_count(value) -> int:
    text = str(value or "").strip()
    if not text:
        raise ValueError("请填写正确的发货件数")
    if not text.isdigit():
        raise ValueError("请填写正确的发货件数")
    count = int(text)
    if count <= 0:
        raise ValueError("请填写正确的发货件数")
    return count


def _parse_weight_kg(value) -> float:
    text = str(value or "").strip()
    if not text:
        raise ValueError("请填写正确的总重量")
    try:
        weight = float(text)
    except ValueError as exc:
        raise ValueError("请填写正确的总重量") from exc
    if weight <= 0:
        raise ValueError("请填写正确的总重量")
    return weight


def _validate_draft_waybill_conflicts(
    session,
    *,
    draft_id: int | None,
    company_name: str,
    ship_date: str,
    waybill_no: str,
    package_count: int,
    weight_kg: float,
) -> None:
    rows = session.query(PackingDraft).filter(PackingDraft.waybill_no == waybill_no).all()
    for row in rows:
        if draft_id is not None and row.id == draft_id:
            continue
        if row.company_name != company_name:
            raise ValueError("同一物流识别号的公司必须一致")
        if row.pack_date != ship_date:
            raise ValueError("同一物流识别号的发货日期必须一致")
        if int(row.package_count or 0) != package_count:
            raise ValueError("同一物流识别号的包裹件数必须一致")
        if abs(float(row.weight_kg or 0) - weight_kg) > 1e-6:
            raise ValueError("同一物流识别号的总重量必须一致")


def validate_shipping_details(
    session,
    *,
    shipping_method,
    company_name,
    ship_date,
    waybill_no,
    package_count,
    weight_kg,
    draft_id: int | None = None,
    allow_empty_waybill_for_new_huolala: bool = False,
) -> tuple[str, str, int, float]:
    normalized_ship_date = _validate_pack_date(ship_date)
    method = str(shipping_method or "").strip()
    shipping_method_label(method)
    count = _parse_package_count(package_count)
    weight = _parse_weight_kg(weight_kg)
    normalized_waybill = str(waybill_no or "").strip()
    if not normalized_waybill:
        if method == "huolala" and allow_empty_waybill_for_new_huolala:
            return method, "", count, weight
        raise ValueError("请填写运单号")
    _validate_draft_waybill_conflicts(
        session,
        draft_id=draft_id,
        company_name=str(company_name or "").strip(),
        ship_date=normalized_ship_date,
        waybill_no=normalized_waybill,
        package_count=count,
        weight_kg=weight,
    )
    matching_waybill_or_none(
        session,
        company_name=str(company_name or "").strip(),
        ship_date=normalized_ship_date,
        waybill_no=normalized_waybill,
        package_count=count,
        weight_kg=weight,
    )
    return method, normalized_waybill, count, weight


def get_or_create_matching_waybill(
    session,
    *,
    user_id: int,
    company_name: str,
    ship_date: str,
    waybill_no: str,
    shipping_method: str,
    package_count: int,
    weight_kg: float,
):
    existing = matching_waybill_or_none(
        session,
        company_name=company_name,
        ship_date=ship_date,
        waybill_no=waybill_no,
        package_count=package_count,
        weight_kg=weight_kg,
    )
    if existing is not None:
        return existing
    try:
        with session.begin_nested():
            return create_waybill_record(
                session,
                user_id,
                company_name,
                ship_date,
                waybill_no,
                courier=shipping_method_label(shipping_method),
                weight_kg=weight_kg,
                package_count=package_count,
                commit=False,
            )
    except IntegrityError:
        existing = matching_waybill_or_none(
            session,
            company_name=company_name,
            ship_date=ship_date,
            waybill_no=waybill_no,
            package_count=package_count,
            weight_kg=weight_kg,
        )
        if existing is not None:
            return existing
        raise


def create_packing_draft(
    session,
    user_id: int,
    pack_date: str,
    company_name: str,
    product_name: str,
    style_name: str,
    lines: list[dict],
    note: str = "",
    photo_paths: list[str] | None = None,
    waybill_no: str = "",
    order_id: int | None = None,
    shipping_method: str = "",
    package_count: int = 0,
    weight_kg: float = 0,
) -> PackingDraft:
    normalized_pack_date = _validate_pack_date(pack_date)
    cleaned_lines = _clean_lines(lines)
    selected_order = (
        session.query(SalesOrder)
        .filter(SalesOrder.id == int(order_id))
        .with_for_update()
        .one_or_none()
        if order_id
        else None
    )
    if order_id and selected_order is None:
        raise ValueError("所选订单不存在")
    if selected_order is not None:
        if get_open_archive(session, selected_order.id):
            raise ValueError("订单已归档，请先恢复")
        if selected_order.status != "active":
            raise ValueError("所选订单已停用")
        _validate_formal_order_lines(session, selected_order, cleaned_lines)
        company_name = selected_order.company.name
        product_name = selected_order.product_name
        style_name = selected_order.style_name
    normalized_method, normalized_waybill, normalized_package_count, normalized_weight = validate_shipping_details(
        session,
        shipping_method=shipping_method,
        company_name=company_name,
        ship_date=normalized_pack_date,
        waybill_no=waybill_no,
        package_count=package_count,
        weight_kg=weight_kg,
        allow_empty_waybill_for_new_huolala=True,
    )
    draft = PackingDraft(
        user_id=user_id,
        order_id=selected_order.id if selected_order else None,
        pack_date=normalized_pack_date,
        company_name=company_name,
        product_name=product_name,
        style_name=style_name,
        package_no=_next_package_no(session, normalized_pack_date),
        shipping_method=normalized_method,
        waybill_no=normalized_waybill,
        package_count=normalized_package_count,
        weight_kg=normalized_weight,
        note=note,
    )
    session.add(draft)
    session.flush()
    if normalized_method == "huolala" and not normalized_waybill:
        normalized_waybill = f"货拉拉-{normalized_pack_date.replace('-', '')}-{draft.id:03d}"
        validate_shipping_details(
            session,
            shipping_method=normalized_method,
            company_name=company_name,
            ship_date=normalized_pack_date,
            waybill_no=normalized_waybill,
            package_count=normalized_package_count,
            weight_kg=normalized_weight,
            draft_id=draft.id,
        )
        draft.waybill_no = normalized_waybill
    for line in cleaned_lines:
        session.add(
            PackingDraftLine(
                draft_id=draft.id,
                order_line_id=line.get("order_line_id"),
                size=line["size"],
                quantity=line["quantity"],
            )
        )
    for path in photo_paths or []:
        session.add(PackingDraftPhoto(draft_id=draft.id, file_path=path, original_name=Path(path).name))
    session.commit()
    session.refresh(draft)
    return draft


def _get_own_draft(session, draft_id: int, user_id: int) -> PackingDraft:
    draft = session.get(PackingDraft, draft_id)
    if draft is None or draft.user_id != user_id:
        raise ValueError("不能修改这条包货记录")
    if draft.submitted_report_id is not None:
        raise ValueError("已提交的包货记录不能修改")
    return draft


def update_packing_draft(
    session,
    draft_id: int,
    user_id: int,
    lines: list[dict],
    note: str = "",
    photo_paths: list[str] | None = None,
    waybill_no: str | None = None,
    shipping_method: str | None = None,
    package_count: int | None = None,
    weight_kg: float | None = None,
    pack_date: str | None = None,
) -> PackingDraft:
    draft = _get_own_draft(session, draft_id, user_id)
    cleaned_lines = _clean_lines(lines)
    if draft.order_id:
        selected_order = (
            session.query(SalesOrder)
            .filter(SalesOrder.id == draft.order_id)
            .with_for_update()
            .one_or_none()
        )
        if selected_order is None:
            raise ValueError("所选订单不存在")
        if get_open_archive(session, selected_order.id):
            raise ValueError("订单已归档，请先恢复")
        _validate_formal_order_lines(session, selected_order, cleaned_lines)
    normalized_pack_date = _validate_pack_date(pack_date if pack_date is not None else draft.pack_date)
    normalized_method, normalized_waybill, normalized_package_count, normalized_weight = validate_shipping_details(
        session,
        shipping_method=shipping_method if shipping_method is not None else draft.shipping_method,
        company_name=draft.company_name,
        ship_date=normalized_pack_date,
        waybill_no=waybill_no if waybill_no is not None else draft.waybill_no,
        package_count=package_count if package_count is not None else draft.package_count,
        weight_kg=weight_kg if weight_kg is not None else draft.weight_kg,
        draft_id=draft.id,
    )
    for line in list(draft.lines):
        session.delete(line)
    session.flush()
    for line in cleaned_lines:
        session.add(
            PackingDraftLine(
                draft_id=draft.id,
                order_line_id=line.get("order_line_id"),
                size=line["size"],
                quantity=line["quantity"],
            )
        )
    for path in photo_paths or []:
        session.add(PackingDraftPhoto(draft_id=draft.id, file_path=path, original_name=Path(path).name))
    draft.pack_date = normalized_pack_date
    draft.note = note
    draft.shipping_method = normalized_method
    draft.waybill_no = normalized_waybill
    draft.package_count = normalized_package_count
    draft.weight_kg = normalized_weight
    session.commit()
    session.refresh(draft)
    return draft


def delete_packing_draft(session, draft_id: int, user_id: int) -> None:
    draft = _get_own_draft(session, draft_id, user_id)
    session.delete(draft)
    session.commit()


def submit_packing_draft(session, draft_id: int, user_id: int):
    draft = _get_own_draft(session, draft_id, user_id)
    lines = [{"size": line.size, "quantity": line.quantity, "order_line_id": line.order_line_id} for line in draft.lines]
    try:
        normalized_pack_date = _validate_pack_date(draft.pack_date)
        normalized_method, normalized_waybill, normalized_package_count, normalized_weight = validate_shipping_details(
            session,
            shipping_method=draft.shipping_method,
            company_name=draft.company_name,
            ship_date=normalized_pack_date,
            waybill_no=draft.waybill_no,
            package_count=draft.package_count,
            weight_kg=draft.weight_kg,
            draft_id=draft.id,
        )
        report = submit_shipment_report(
            session,
            user_id=user_id,
            ship_date=normalized_pack_date,
            company_name=draft.company_name,
            product_name=draft.product_name,
            style_name=draft.style_name,
            lines=lines,
            photo_paths=[photo.file_path for photo in draft.photos],
            note=draft.note,
            waybill_no=normalized_waybill,
            order_id=draft.order_id,
            commit=False,
        )
        waybill = get_or_create_matching_waybill(
            session,
            user_id=user_id,
            company_name=draft.company_name,
            ship_date=normalized_pack_date,
            waybill_no=normalized_waybill,
            shipping_method=normalized_method,
            package_count=normalized_package_count,
            weight_kg=normalized_weight,
        )
        report.waybill_id = waybill.id
        draft.pack_date = normalized_pack_date
        draft.shipping_method = normalized_method
        draft.waybill_no = normalized_waybill
        draft.package_count = normalized_package_count
        draft.weight_kg = normalized_weight
        draft.submitted_report_id = report.id
        for photo in report.photos:
            photo.draft_id = draft.id
        recompute_for_report(session, report.id, commit=False)
        session.commit()
        session.refresh(report)
        return report
    except Exception:
        session.rollback()
        raise
