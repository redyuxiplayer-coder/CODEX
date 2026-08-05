from fastapi.testclient import TestClient

from app.db import get_session
from app.main import create_app
from app.models import ShipmentReport, User, WaybillRecord
from app.services.logistics import (
    create_waybill_record,
    delete_waybill_record,
    link_reports_to_waybill,
    list_waybill_records,
    update_waybill_record,
)


def _admin(db_session) -> User:
    admin = User(username="logistics_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    return admin


def _reports(db_session, user: User) -> list[ShipmentReport]:
    reports = [
        ShipmentReport(
            user_id=user.id,
            ship_date="2026-07-17",
            company_name="广东茉莉",
            product_name="小红帽",
            style_name="小红帽女款",
            status="auto_approved",
        ),
        ShipmentReport(
            user_id=user.id,
            ship_date="2026-07-17",
            company_name="广东茉莉",
            product_name="赛车服",
            style_name="女士赛车服",
            status="auto_approved",
        ),
    ]
    db_session.add_all(reports)
    db_session.commit()
    return reports


def test_create_and_list_waybill_records(db_session):
    admin = _admin(db_session)

    record = create_waybill_record(
        db_session,
        admin.id,
        "广东茉莉",
        "2026-07-17",
        "800209579798",
        weight_kg=262.3,
        package_count=9,
        note="整车",
    )

    assert record.waybill_no == "800209579798"
    assert record.weight_kg == 262.3
    assert record.package_count == 9
    rows = list_waybill_records(db_session)
    assert len(rows) == 1
    assert rows[0].company_name == "广东茉莉"


def test_update_and_delete_waybill_record(db_session):
    admin = _admin(db_session)
    record = create_waybill_record(db_session, admin.id, "广东茉莉", "2026-07-17", "800209579798", weight_kg=100, package_count=2)

    update_waybill_record(db_session, record.id, weight_kg=262.3, package_count=9, waybill_no="800209579799")

    db_session.refresh(record)
    assert record.weight_kg == 262.3
    assert record.waybill_no == "800209579799"

    delete_waybill_record(db_session, record.id)
    assert db_session.get(WaybillRecord, record.id) is None


def test_link_and_unlink_reports(db_session):
    admin = _admin(db_session)
    reports = _reports(db_session, admin)
    record = create_waybill_record(db_session, admin.id, "广东茉莉", "2026-07-17", "800209579798", weight_kg=262.3, package_count=9)

    link_reports_to_waybill(db_session, record.id, [report.id for report in reports])

    db_session.refresh(record)
    assert len(record.reports) == 2
    for report in reports:
        db_session.refresh(report)
        assert report.waybill_id == record.id

    from app.services.logistics import unlink_report_from_waybill

    unlink_report_from_waybill(db_session, record.id, reports[0].id)
    db_session.refresh(reports[0])
    assert reports[0].waybill_id is None
    db_session.refresh(record)
    assert len(record.reports) == 1


def test_logistics_api_create_list_link(db_session):
    admin = _admin(db_session)
    reports = _reports(db_session, admin)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))

    response = client.post(
        "/api/v1/logistics",
        data={
            "company_name": "广东茉莉",
            "ship_date": "2026-07-17",
            "waybill_no": "800209579798",
            "weight_kg": "262.3",
            "package_count": "9",
            "note": "整车",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["waybill_no"] == "800209579798"
    record_id = payload["id"]

    listed = client.get("/api/v1/logistics?company=广东茉莉")
    assert listed.status_code == 200
    assert len(listed.json()["records"]) == 1

    linked = client.post(
        f"/api/v1/logistics/{record_id}/reports",
        data={"report_ids": [str(report.id) for report in reports]},
    )
    assert linked.status_code == 200
    detail = client.get(f"/api/v1/logistics/{record_id}")
    assert len(detail.json()["reports"]) == 2

    removed = client.post(f"/api/v1/logistics/{record_id}/reports/{reports[0].id}/remove")
    assert removed.status_code == 200
    detail = client.get(f"/api/v1/logistics/{record_id}")
    assert len(detail.json()["reports"]) == 1
