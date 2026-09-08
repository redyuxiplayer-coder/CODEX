from fastapi.testclient import TestClient

from app.db import get_session
from app.main import create_app
from app.models import OperationLog, User
from app.services.orders import create_order_line
from app.services.shipments import submit_shipment_report


def _client_and_report(db_session):
    admin = User(username="ship_date_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    worker = User(username="ship_date_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add_all([admin, worker])
    db_session.commit()
    create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)
    report = submit_shipment_report(
        db_session,
        user_id=worker.id,
        ship_date="2026-08-04",
        company_name="源兴发",
        product_name="裁判",
        style_name="圆领裁判",
        lines=[{"size": "M", "quantity": 10}],
        photo_paths=[],
        note="",
    )

    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))
    return client, report


def test_update_shipment_date_succeeds_and_logs(db_session):
    client, report = _client_and_report(db_session)

    response = client.post(
        f"/api/v1/shipments/{report.id}/ship-date",
        json={"ship_date": "2026-08-05"},
    )

    assert response.status_code == 200
    assert response.json()["ship_date"] == "2026-08-05"
    db_session.refresh(report)
    assert report.ship_date == "2026-08-05"
    log = db_session.query(OperationLog).filter(OperationLog.action == "shipment_date_update").one()
    assert log.detail == '{"before": "2026-08-04", "after": "2026-08-05"}'


def test_update_shipment_date_allows_future_date(db_session):
    client, report = _client_and_report(db_session)

    response = client.post(
        f"/api/v1/shipments/{report.id}/ship-date",
        json={"ship_date": "2099-12-31"},
    )

    assert response.status_code == 200
    assert response.json()["ship_date"] == "2099-12-31"


def test_update_shipment_date_rejects_invalid_date(db_session):
    client, report = _client_and_report(db_session)

    response = client.post(
        f"/api/v1/shipments/{report.id}/ship-date",
        json={"ship_date": "不是日期"},
    )

    assert response.status_code == 400


def test_update_shipment_date_missing_report_returns_404(db_session):
    client, _report = _client_and_report(db_session)

    response = client.post(
        "/api/v1/shipments/99999/ship-date",
        json={"ship_date": "2026-08-06"},
    )

    assert response.status_code == 404
