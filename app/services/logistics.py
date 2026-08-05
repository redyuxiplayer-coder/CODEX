from sqlalchemy.orm import Session

from app.models import ShipmentReport, WaybillRecord


def create_waybill_record(
    session: Session,
    user_id: int,
    company_name: str,
    ship_date: str,
    waybill_no: str,
    weight_kg: float = 0,
    package_count: int = 0,
    note: str = "",
) -> WaybillRecord:
    record = WaybillRecord(
        company_name=(company_name or "").strip(),
        ship_date=(ship_date or "").strip(),
        waybill_no=(waybill_no or "").strip(),
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
