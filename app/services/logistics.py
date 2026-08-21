import math

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import PackingDraft, ShipmentReport, WaybillRecord
from app.services.orders import APPROVED_STATUSES


CHANNEL_KEYWORDS = [
    ("顺丰", "顺丰"),
    ("跨越", "跨越物流"),
    ("货拉拉", "货拉拉"),
    ("中通", "中通"),
    ("京东", "京东"),
    ("圆通", "圆通"),
    ("韵达", "韵达"),
    ("极兔", "极兔"),
    ("申通", "申通"),
]


def shipping_method_label(shipping_method: str) -> str:
    method = (shipping_method or "").strip()
    if method == "courier":
        return "快递"
    if method == "huolala":
        return "货拉拉"
    raise ValueError("请选择发货方式")


def waybill_shipping_method(courier: str) -> str:
    return "huolala" if (courier or "").strip() == "货拉拉" else "courier"


def lock_logistics_identifier(session: Session, waybill_no: str) -> None:
    normalized_waybill = (waybill_no or "").strip()
    if not normalized_waybill:
        return
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(210821, hashtext(:identifier))"),
            {"identifier": normalized_waybill},
        )


def validate_logistics_identifier_channel(
    session: Session,
    *,
    waybill_no: str,
    shipping_method: str,
    exclude_waybill_id: int | None = None,
) -> None:
    normalized_waybill = (waybill_no or "").strip()
    if not normalized_waybill:
        return
    for draft in session.query(PackingDraft).filter(PackingDraft.waybill_no == normalized_waybill).all():
        if draft.shipping_method != shipping_method:
            raise ValueError("物流识别号不能跨发货方式复用")
    records = session.query(WaybillRecord).filter(WaybillRecord.waybill_no == normalized_waybill)
    if exclude_waybill_id is not None:
        records = records.filter(WaybillRecord.id != int(exclude_waybill_id))
    for record in records.all():
        if waybill_shipping_method(record.courier) != shipping_method:
            raise ValueError("物流识别号不能跨发货方式复用")


def _normalized_waybill_weight(value) -> float:
    try:
        weight = float(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("请填写正确的总重量") from exc
    if not math.isfinite(weight) or weight < 0:
        raise ValueError("请填写正确的总重量")
    return weight


def validate_logistics_identifier_compatibility(
    session: Session,
    *,
    company_name: str,
    ship_date: str,
    waybill_no: str,
    shipping_method: str,
    package_count: int,
    weight_kg: float,
    exclude_draft_id: int | None = None,
    exclude_waybill_id: int | None = None,
) -> None:
    normalized_waybill = (waybill_no or "").strip()
    normalized_company = (company_name or "").strip()
    normalized_ship_date = (ship_date or "").strip()
    normalized_package_count = int(package_count or 0)
    normalized_weight = _normalized_waybill_weight(weight_kg)
    if not normalized_waybill:
        return
    validate_logistics_identifier_channel(
        session,
        waybill_no=normalized_waybill,
        shipping_method=shipping_method,
        exclude_waybill_id=exclude_waybill_id,
    )
    drafts = session.query(PackingDraft).filter(PackingDraft.waybill_no == normalized_waybill)
    if exclude_draft_id is not None:
        drafts = drafts.filter(PackingDraft.id != int(exclude_draft_id))
    sources = [
        (draft.company_name, draft.pack_date, draft.package_count, draft.weight_kg)
        for draft in drafts.all()
    ]
    records = session.query(WaybillRecord).filter(WaybillRecord.waybill_no == normalized_waybill)
    if exclude_waybill_id is not None:
        records = records.filter(WaybillRecord.id != int(exclude_waybill_id))
    sources.extend(
        (record.company_name, record.ship_date, record.package_count, record.weight_kg)
        for record in records.all()
    )
    for source_company, source_date, source_package_count, source_weight_kg in sources:
        if (source_company or "").strip() != normalized_company:
            raise ValueError("同一物流识别号的公司必须一致")
        if (source_date or "").strip() != normalized_ship_date:
            raise ValueError("同一物流识别号的发货日期必须一致")
        if int(source_package_count or 0) != normalized_package_count:
            raise ValueError("同一物流识别号的包裹件数必须一致")
        source_weight = float(source_weight_kg or 0)
        if not math.isfinite(source_weight) or abs(source_weight - normalized_weight) > 1e-6:
            raise ValueError("同一物流识别号的总重量必须一致")


def matching_waybill_or_none(
    session: Session,
    *,
    company_name: str,
    ship_date: str,
    waybill_no: str,
    package_count: int,
    weight_kg: float,
    shipping_method: str | None = None,
) -> WaybillRecord | None:
    normalized_waybill = (waybill_no or "").strip()
    if not normalized_waybill:
        return None
    record = session.query(WaybillRecord).filter_by(waybill_no=normalized_waybill).one_or_none()
    if record is None:
        return None
    validate_logistics_identifier_compatibility(
        session,
        company_name=company_name,
        ship_date=ship_date,
        waybill_no=normalized_waybill,
        shipping_method=shipping_method or waybill_shipping_method(record.courier),
        package_count=package_count,
        weight_kg=weight_kg,
    )
    return record


def classify_channel(note: str, ship_date: str = "") -> str:
    """根据备注关键词判断快递渠道；历史导入无渠道信息。"""
    if ship_date == "历史导入":
        return "历史导入"
    text = note or ""
    for keyword, label in CHANNEL_KEYWORDS:
        if keyword in text:
            return label
    return "待确认"


def create_waybill_record(
    session: Session,
    user_id: int,
    company_name: str,
    ship_date: str,
    waybill_no: str,
    courier: str = "中通",
    weight_kg: float = 0,
    package_count: int = 0,
    note: str = "",
    commit: bool = True,
) -> WaybillRecord:
    normalized_waybill = (waybill_no or "").strip()
    normalized_courier = (courier or "中通").strip()
    normalized_weight = _normalized_waybill_weight(weight_kg)
    lock_logistics_identifier(session, normalized_waybill)
    validate_logistics_identifier_compatibility(
        session,
        company_name=company_name,
        ship_date=ship_date,
        waybill_no=normalized_waybill,
        shipping_method=waybill_shipping_method(normalized_courier),
        package_count=package_count,
        weight_kg=normalized_weight,
    )
    record = WaybillRecord(
        company_name=(company_name or "").strip(),
        ship_date=(ship_date or "").strip(),
        waybill_no=normalized_waybill,
        courier=normalized_courier,
        weight_kg=normalized_weight,
        package_count=int(package_count or 0),
        note=(note or "").strip(),
        created_by=int(user_id),
    )
    session.add(record)
    session.flush()
    if commit:
        session.commit()
        session.refresh(record)
    return record


def update_waybill_record(
    session: Session,
    waybill_id: int,
    *,
    company_name: str | None = None,
    ship_date: str | None = None,
    waybill_no: str | None = None,
    courier: str | None = None,
    weight_kg: float | None = None,
    package_count: int | None = None,
    note: str | None = None,
) -> WaybillRecord:
    record = (
        session.query(WaybillRecord)
        .filter(WaybillRecord.id == int(waybill_id))
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if record is None:
        raise ValueError("快递单不存在")
    normalized_waybill = (waybill_no if waybill_no is not None else record.waybill_no or "").strip()
    normalized_courier = (courier if courier is not None else record.courier or "中通").strip()
    normalized_company = (company_name if company_name is not None else record.company_name or "").strip()
    normalized_ship_date = (ship_date if ship_date is not None else record.ship_date or "").strip()
    normalized_package_count = int(package_count if package_count is not None else record.package_count or 0)
    normalized_weight = _normalized_waybill_weight(weight_kg if weight_kg is not None else record.weight_kg)
    for identifier in sorted({value for value in [(record.waybill_no or "").strip(), normalized_waybill] if value}):
        lock_logistics_identifier(session, identifier)
    validate_logistics_identifier_compatibility(
        session,
        company_name=normalized_company,
        ship_date=normalized_ship_date,
        waybill_no=normalized_waybill,
        shipping_method=waybill_shipping_method(normalized_courier),
        package_count=normalized_package_count,
        weight_kg=normalized_weight,
        exclude_waybill_id=record.id,
    )
    if company_name is not None:
        record.company_name = normalized_company
    if ship_date is not None:
        record.ship_date = normalized_ship_date
    if waybill_no is not None:
        record.waybill_no = normalized_waybill
    if courier is not None:
        record.courier = normalized_courier
    if weight_kg is not None:
        record.weight_kg = normalized_weight
    if package_count is not None:
        record.package_count = normalized_package_count
    if note is not None:
        record.note = note.strip()
    session.commit()
    session.refresh(record)
    return record


def delete_waybill_record(session: Session, waybill_id: int) -> None:
    record = session.get(WaybillRecord, waybill_id)
    if record is None:
        raise ValueError("快递单不存在")
    for report in list(record.reports):
        report.waybill_id = None
    session.delete(record)
    session.commit()


def list_waybill_records(
    session: Session,
    company_name: str = "",
    ship_date: str = "",
) -> list[WaybillRecord]:
    query = session.query(WaybillRecord)
    if company_name.strip():
        query = query.filter(WaybillRecord.company_name == company_name.strip())
    if ship_date.strip():
        query = query.filter(WaybillRecord.ship_date == ship_date.strip())
    return query.order_by(WaybillRecord.ship_date.desc(), WaybillRecord.id.desc()).all()


def link_reports_to_waybill(session: Session, waybill_id: int, report_ids: list[int]) -> WaybillRecord:
    record = session.get(WaybillRecord, waybill_id)
    if record is None:
        raise ValueError("快递单不存在")
    for report_id in report_ids:
        report = session.get(ShipmentReport, int(report_id))
        if report is not None:
            report.waybill_id = record.id
    session.commit()
    session.refresh(record)
    return record


def unlink_report_from_waybill(session: Session, waybill_id: int, report_id: int) -> None:
    report = session.get(ShipmentReport, report_id)
    if report is not None and report.waybill_id == waybill_id:
        report.waybill_id = None
        session.commit()


def link_candidates(session: Session, company_name: str, ship_date: str) -> list[ShipmentReport]:
    """某公司某天尚未关联快递单的发货明细，供勾选。"""
    query = session.query(ShipmentReport).filter(
        ShipmentReport.company_name == company_name.strip(),
        ShipmentReport.ship_date == ship_date.strip(),
        ShipmentReport.waybill_id.is_(None),
    )
    return query.order_by(ShipmentReport.style_name, ShipmentReport.id).all()


def list_unlinked_reports(
    session: Session,
    company_name: str = "",
    ship_date: str = "",
) -> list[dict]:
    """已审核但尚未挂靠快递单的发货单，附渠道判断与未挂原因。"""
    query = session.query(ShipmentReport).filter(
        ShipmentReport.status.in_(APPROVED_STATUSES),
        ShipmentReport.waybill_id.is_(None),
    )
    if company_name.strip():
        query = query.filter(ShipmentReport.company_name == company_name.strip())
    if ship_date.strip():
        query = query.filter(ShipmentReport.ship_date == ship_date.strip())
    rows = query.order_by(ShipmentReport.ship_date, ShipmentReport.id).all()
    result = []
    for report in rows:
        order = report.order
        result.append(
            {
                "id": report.id,
                "order_id": report.order_id,
                "system_order_no": order.system_order_no if order else "",
                "customer_order_no": order.customer_order_no if order else "",
                "order_date": order.order_date if order else "",
                "color_name": order.color_name if order else "",
                "company_name": report.company_name,
                "ship_date": report.ship_date,
                "style_name": report.style_name,
                "quantity": sum(int(line.quantity or 0) for line in report.lines),
                "note": report.note,
                "channel": classify_channel(report.note, report.ship_date),
                "unlinked_reason": report.unlinked_reason or "",
            }
        )
    return result


def set_unlinked_reason(session: Session, report_id: int, reason: str) -> ShipmentReport:
    report = session.get(ShipmentReport, report_id)
    if report is None:
        raise ValueError("发货单不存在")
    report.unlinked_reason = (reason or "").strip()
    session.commit()
    session.refresh(report)
    return report


def quick_link_waybill(
    session: Session,
    user_id: int,
    report_id: int,
    courier: str,
    waybill_no: str,
    weight_kg: float = 0,
    package_count: int = 0,
    note: str = "",
) -> WaybillRecord:
    """给某笔未挂靠发货单直接建单并挂靠（支持顺丰等非中通渠道）。"""
    report = session.get(ShipmentReport, int(report_id))
    if report is None:
        raise ValueError("发货单不存在")
    record = create_waybill_record(
        session,
        user_id,
        report.company_name,
        report.ship_date,
        waybill_no,
        courier=courier,
        weight_kg=weight_kg,
        package_count=package_count,
        note=note,
    )
    report.waybill_id = record.id
    session.commit()
    session.refresh(record)
    return record
