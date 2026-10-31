from fastapi.testclient import TestClient

from app.db import get_session
from app.main import create_app
from app.models import Spu, User


def _client(db_session):
    admin = User(username="stock_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    worker = User(username="stock_worker", display_name="员工", password_hash="x", role="worker", is_active=True)
    spu = Spu(code="SPU-STOCK", product_name="节日服装", style_name="圣诞款", is_active=True)
    db_session.add_all([admin, worker, spu])
    db_session.commit()

    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))
    return client, admin, worker, spu


def test_stock_api_supports_desktop_inventory_workflow(db_session):
    client, _admin, _worker, spu = _client(db_session)

    empty = client.get("/api/v1/stock")
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert empty.json()["spus"][0]["id"] == spu.id

    created = client.post(
        "/api/v1/stock/items",
        json={"spu_id": spu.id, "color_name": "红色", "color_code": "RED", "size": "M"},
    )
    assert created.status_code == 200
    item_id = created.json()["item"]["id"]

    counted = client.post(
        f"/api/v1/stock/items/{item_id}/count",
        json={"quantity": 8, "reason": "首次盘点"},
    )
    assert counted.status_code == 200
    assert counted.json()["item"]["quantity"] == 8

    inbound = client.post(
        f"/api/v1/stock/items/{item_id}/in",
        json={"quantity": 5, "reason": "采购入库"},
    )
    assert inbound.status_code == 200
    assert inbound.json()["item"]["quantity"] == 13

    result = client.get("/api/v1/stock?q=圣诞")
    assert result.status_code == 200
    payload = result.json()
    assert payload["items"][0]["quantity"] == 13
    assert [row["movement_type"] for row in payload["movements"]] == ["in", "count"]
    assert payload["movements"][0]["item_label"] == "节日服装 / 圣诞款 / 红色 / M"


def test_stock_api_rejects_worker(db_session):
    client, _admin, worker, _spu = _client(db_session)
    client.cookies.set("zy_user_id", str(worker.id))

    response = client.get("/api/v1/stock")

    assert response.status_code == 403
