from fastapi.testclient import TestClient

from app.db import get_session
from app.main import create_app
from app.models import Company, Spu, User
from app.services.sales_orders import create_sales_order
from app.services.shipments import submit_shipment_report


def _client_and_report(db_session):
    admin = User(username="order_search_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    worker = User(username="order_search_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    company = Company(name="源兴发搜索", code="YXS", next_order_sequence=1)
    spu = Spu(code="JSP", product_name="裁判", style_name="成人V领", is_active=True)
    db_session.add_all([admin, worker, company, spu])
    db_session.commit()

    order = create_sales_order(
        db_session,
        company.id,
        spu.id,
        "红色",
        "RED",
        "2026-08-09",
        [{"size": "S", "quantity": 100}],
        customer_order_no="客单-A123",
    )
    report = submit_shipment_report(
        db_session,
        user_id=worker.id,
        ship_date="2026-08-10",
        company_name=company.name,
        product_name=order.product_name,
        style_name=order.style_name,
        lines=[{"size": "S", "quantity": 10, "order_line_id": order.lines[0].id}],
        order_id=order.id,
    )
    report.waybill_no = "WB-ORDER-SEARCH"
    second_order = create_sales_order(
        db_session,
        company.id,
        spu.id,
        "蓝色",
        "BLUE",
        "2026-08-09",
        [{"size": "M", "quantity": 60}],
        customer_order_no="客单-B456",
    )
    second_report = submit_shipment_report(
        db_session,
        user_id=worker.id,
        ship_date="2026-08-11",
        company_name=company.name,
        product_name=second_order.product_name,
        style_name=second_order.style_name,
        lines=[{"size": "M", "quantity": 5, "order_line_id": second_order.lines[0].id}],
        order_id=second_order.id,
    )
    second_report.waybill_no = "OTHER-WB"
    db_session.commit()

    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))
    return client, order, report, second_report


def test_shipments_order_no_search_matches_system_order_and_ignores_company(db_session):
    client, order, report, _second = _client_and_report(db_session)
    order_keyword = order.system_order_no.split("-", 2)[0] + "-" + order.system_order_no.split("-")[1]

    response = client.get(
        f"/api/v1/shipments?order_no={order_keyword}&company=完全不存在的公司"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["reports"][0]["id"] == report.id


def test_shipments_order_no_search_matches_customer_order_no(db_session):
    client, _order, report, _second = _client_and_report(db_session)

    response = client.get("/api/v1/shipments?order_no=客单-A")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["reports"][0]["id"] == report.id


def test_shipments_order_no_search_ignores_waybill_filter(db_session):
    client, order, report, _second = _client_and_report(db_session)
    order_keyword = order.system_order_no.split("-", 2)[0] + "-" + order.system_order_no.split("-")[1]

    response = client.get(
        f"/api/v1/shipments?order_no={order_keyword}&waybill=不存在"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["reports"][0]["id"] == report.id


def test_shipments_order_no_search_does_not_match_waybill_text(db_session):
    client, _order, _report, _second = _client_and_report(db_session)

    response = client.get("/api/v1/shipments?order_no=WB-ORDER")

    assert response.status_code == 200
    assert response.json()["total"] == 0
