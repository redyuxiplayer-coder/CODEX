from fastapi.testclient import TestClient

from app.db import get_session
from app.main import create_app
from app.models import Company, ShipmentLine, ShipmentReport, Spu, User
from app.services.sales_orders import create_sales_order


def setup_archive_api(db_session, shipped=True):
    admin = User(username="archive_api_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    worker = User(username="archive_api_worker", display_name="员工", password_hash="x", role="worker", is_active=True)
    company = Company(name="源兴发", code="YXF", next_order_sequence=1)
    spu = Spu(code="JS", product_name="啦啦队", style_name="僵尸啦啦队")
    db_session.add_all([admin, worker, company, spu])
    db_session.commit()
    order = create_sales_order(
        db_session,
        company.id,
        spu.id,
        "红色",
        "RED",
        "2026-08-10",
        [{"size": "S", "quantity": 100}, {"size": "M", "quantity": 50}],
    )
    if shipped:
        report = ShipmentReport(
            user_id=worker.id,
            order_id=order.id,
            ship_date="2026-08-10",
            company_name=company.name,
            product_name=order.product_name,
            style_name=order.style_name,
            status="approved_after_edit",
            review_reason="",
            note="",
        )
        db_session.add(report)
        db_session.flush()
        for line in order.lines:
            db_session.add(
                ShipmentLine(
                    report_id=report.id,
                    order_line_id=line.id,
                    size=line.size,
                    quantity=line.quantity,
                )
            )
        db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    admin_client = TestClient(app)
    admin_client.cookies.set("zy_user_id", str(admin.id))
    worker_client = TestClient(app)
    worker_client.cookies.set("zy_user_id", str(worker.id))
    return admin_client, worker_client, order


def order_numbers(response):
    assert response.status_code == 200
    return [row["system_order_no"] for row in response.json()["orders"]]


def test_admin_can_archive_restore_and_filter(db_session):
    client, _, order = setup_archive_api(db_session)

    archived = client.post(f"/api/v1/sales-orders/{order.id}/archive")

    assert archived.status_code == 200
    assert archived.json()["is_archived"] is True
    assert order.system_order_no not in order_numbers(client.get("/api/v1/sales-orders"))
    assert order.system_order_no in order_numbers(client.get("/api/v1/sales-orders?archive_status=archived"))
    assert order.system_order_no in order_numbers(client.get("/api/v1/sales-orders?archive_status=all"))

    restored = client.post(f"/api/v1/sales-orders/{order.id}/restore")
    detail = client.get(f"/api/v1/sales-orders/{order.id}").json()

    assert restored.status_code == 200
    assert restored.json()["is_archived"] is False
    assert len(detail["history"]) == 1
    assert detail["history"][0]["archived_at"]
    assert detail["history"][0]["restored_at"]


def test_archive_api_rejects_worker_and_unfinished_order(db_session):
    admin_client, worker_client, order = setup_archive_api(db_session, shipped=False)

    worker_response = worker_client.post(f"/api/v1/sales-orders/{order.id}/archive")
    admin_response = admin_client.post(f"/api/v1/sales-orders/{order.id}/archive")

    assert worker_response.status_code == 403
    assert admin_response.status_code == 400
    assert "还需" in admin_response.json()["detail"]


def test_archive_filter_rejects_unknown_value(db_session):
    client, _, _ = setup_archive_api(db_session)

    response = client.get("/api/v1/sales-orders?archive_status=unknown")

    assert response.status_code == 400
