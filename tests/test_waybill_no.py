from fastapi.testclient import TestClient

from app.db import get_session
from app.main import create_app
from app.models import ShipmentReport, User
from app.services.orders import create_order_line
from app.services.packing_drafts import create_packing_draft, submit_packing_draft


def _client(db_session, user: User):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(user.id))
    return client


def _users(db_session):
    admin = User(username="wb_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    worker = User(username="wb_worker", display_name="仓库A", password_hash="x", role="worker", is_active=True)
    db_session.add_all([admin, worker])
    db_session.commit()
    return admin, worker


def test_draft_submit_copies_waybill_to_report(db_session):
    _admin, worker = _users(db_session)
    create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)
    draft = create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "裁判",
        "圆领裁判",
        [{"size": "M", "quantity": 10}],
        "",
        waybill_no="YT1234567890",
        shipping_method="courier",
        package_count=2,
        weight_kg=8.8,
    )

    report = submit_packing_draft(db_session, draft.id, worker.id)
    assert report.waybill_no == "YT1234567890"


def test_admin_shipments_filters_and_edits_waybill(db_session):
    admin, worker = _users(db_session)
    create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)
    first = create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "L", 100)
    report_a = ShipmentReport(
        user_id=worker.id,
        ship_date="2026-08-04",
        company_name="源兴发",
        product_name="裁判",
        style_name="圆领裁判",
        waybill_no="YT111",
        status="auto_approved",
    )
    report_b = ShipmentReport(
        user_id=worker.id,
        ship_date="2026-08-04",
        company_name="源兴发",
        product_name="裁判",
        style_name="圆领裁判",
        waybill_no="YT222",
        status="auto_approved",
    )
    db_session.add_all([report_a, report_b])
    db_session.commit()
    client = _client(db_session, admin)

    page = client.get("/admin/shipments?waybill=YT111")
    assert page.status_code == 200
    assert "YT111" in page.text
    assert "YT222" not in page.text

    response = client.post(
        f"/admin/shipments/{report_a.id}/waybill",
        data={"waybill_no": "YT999"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.refresh(report_a)
    assert report_a.waybill_no == "YT999"


def test_worker_my_reports_update_saves_waybill(db_session):
    _admin, worker = _users(db_session)
    create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)
    report = ShipmentReport(
        user_id=worker.id,
        ship_date="2026-08-04",
        company_name="源兴发",
        product_name="裁判",
        style_name="圆领裁判",
        status="auto_approved",
    )
    db_session.add(report)
    db_session.commit()
    client = _client(db_session, worker)

    response = client.post(
        f"/mobile/my-reports/{report.id}/update",
        data={
            "line_ids": [""],
            "sizes": ["M"],
            "quantities": ["10"],
            "note": "",
            "waybill_no": "YT555",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.refresh(report)
    assert report.waybill_no == "YT555"
    assert report.status == "pending_review"
