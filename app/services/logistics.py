from sqlalchemy.orm import Session

from app.models import ShipmentReport, WaybillRecord
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
) -> WaybillRecord:
    record = WaybillRecord(
        company_name=(company_name or "").strip(),
        ship_date=(ship_date or "").strip(),
        waybill_no=(waybill_no or "").strip(),
        courier=(courier or "中通").strip(),
        weight_kg=float(weight_kg or 0),
        package_count=int(package_count or 0),
        note=(note or "").strip(),
        created_by=int(user_id),
    )
    session.add(record)
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
    record = session.get(WaybillRecord, waybill_id)
    if record is None:
        raise ValueError("快递单不存在")
    if company_name is not None:
        record.company_name = company_name.strip()
    if ship_date is not None:
        record.ship_date = ship_date.strip()
    if waybill_no is not None:
        record.waybill_no = waybill_no.strip()
    if courier is not None:
        record.courier = (courier or "中通").strip()
    if weight_kg is not None:
        record.weight_kg = float(weight_kg)
    if package_count is not None:
        record.package_count = int(package_count)
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
