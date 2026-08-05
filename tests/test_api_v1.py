from fastapi.testclient import TestClient

from app.db import get_session
from app.main import create_app
from app.models import User
from app.services.orders import create_order_line, get_order_balances
from app.services.skus import upsert_sku_mapping


def _client(db_session):
    admin = User(username="api_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))
    return client, admin


def test_api_me_requires_login(db_session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)

    response = client.get("/api/v1/me")

    assert response.status_code == 401


def test_api_orders_balances_requires_login(db_session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)

    response = client.get("/api/v1/orders/balances")

    assert response.status_code == 401


def test_api_orders_balances_returns_rows_with_filters(db_session):
    client, _admin = _client(db_session)
    upsert_sku_mapping(db_session, "源兴发", "裁判", "圆领裁判", "S", "SKU-REF-S")
    create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "S", 100, "2026-08-04")
    create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 50, "2026-08-04")

    response = client.get("/api/v1/orders/balances?company=源兴发&status=need")

    assert response.status_code == 200
    payload = response.json()
    assert payload["companies"] == ["源兴发"]
    assert len(payload["balances"]) == 2
    assert all(row["remaining"] > 0 for row in payload["balances"])
    sizes = {row["size"] for row in payload["balances"]}
    assert sizes == {"S", "M"}


def test_api_order_line_detail_includes_totals_ledger_and_returns(db_session):
    client, _admin = _client(db_session)
    order = create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)
    from app.services.returns import create_return_rework

    create_return_rework(db_session, order.id, 1, 3, reason_type="质量问题", reason="演示")

    response = client.get(f"/api/v1/order-lines/{order.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["order"]["product"] == "裁判"
    assert payload["totals"]["returned"] == 3
    assert payload["totals"]["remaining"] == 103
    assert [(entry["movement_type"], entry["quantity"]) for entry in payload["ledger"]] == [("returned", 3)]
    assert payload["returns"][0]["reason"] == "演示"


def test_api_write_endpoints_create_records_and_affect_balance(db_session):
    client, _admin = _client(db_session)
    order = create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)

    response = client.post(
        f"/api/v1/order-lines/{order.id}/returns",
        data={"quantity": "3", "reason_type": "退回返工", "reason": "返工", "status": "pending_rework"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["totals"]["returned"] == 3

    response = client.post(
        f"/api/v1/order-lines/{order.id}/returns/{payload['returns'][0]['id']}/status",
        data={"status": "scrapped"},
    )
    assert response.status_code == 200
    assert response.json()["totals"]["adjusted"] == 3

    response = client.post(f"/api/v1/order-lines/{order.id}/adjustments", data={"quantity": "1", "reason": "盘点"})
    assert response.status_code == 200
    assert response.json()["totals"]["adjusted"] == 4

    response = client.post(f"/api/v1/order-lines/{order.id}/closes", data={"quantity": "2", "reason": "客户不要"})
    assert response.status_code == 200
    assert response.json()["totals"]["closed"] == 2

    response = client.post(f"/api/v1/order-lines/{order.id}/comments", data={"content": "客户说明天再补"})
    assert response.status_code == 200
    assert response.json()["comments"][0]["content"] == "客户说明天再补"

    row = get_order_balances(db_session, "源兴发")[0]
    assert row["remaining"] == 100 + 3 - 4 - 2


def test_api_order_line_detail_includes_unbound_history_shipment(db_session):
    from app.models import ShipmentLine, ShipmentReport
    from app.services.aliases import create_product_alias

    client, admin = _client(db_session)
    create_product_alias(db_session, "源兴发", "小偷", "小偷COS", "小偷", "小偷女款", "统一")
    order = create_order_line(db_session, "源兴发", "小偷", "小偷女款", "XL", 100)
    history = ShipmentReport(
        user_id=admin.id,
        ship_date="2026-07-13",
        company_name="源兴发",
        product_name="小偷",
        style_name="小偷COS",
        status="auto_approved",
    )
    db_session.add(history)
    db_session.flush()
    db_session.add(ShipmentLine(report_id=history.id, order_line_id=None, size="XL", quantity=46))
    db_session.commit()

    response = client.get(f"/api/v1/order-lines/{order.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["totals"]["shipped"] == 46
    assert payload["totals"]["remaining"] == 54
    assert any(not s["bound"] and s["quantity"] == 46 for s in payload["shipments"])
