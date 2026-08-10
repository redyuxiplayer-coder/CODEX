from fastapi.testclient import TestClient

from app.db import get_session
from app.main import create_app
from app.models import Company, User


def _client(db_session):
    admin = User(
        username="formal_order_admin",
        display_name="老板",
        password_hash="x",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))
    return client


def test_create_sales_order_api_returns_generated_number(db_session):
    client = _client(db_session)
    company = Company(name="源兴发", code="", next_order_sequence=1)
    db_session.add(company)
    db_session.commit()

    code_response = client.post(f"/api/v1/companies/{company.id}/code", json={"code": "yxf"})
    assert code_response.status_code == 200
    assert code_response.json()["code"] == "YXF"

    spu_response = client.post(
        "/api/v1/spus",
        json={"code": "js", "product_name": "啦啦队", "style_name": "僵尸啦啦队", "note": ""},
    )
    assert spu_response.status_code == 200
    spu_id = spu_response.json()["id"]

    response = client.post(
        "/api/v1/sales-orders",
        json={
            "company_id": company.id,
            "spu_id": spu_id,
            "color_name": "红色",
            "color_code": "RED",
            "order_date": "2026-08-09",
            "customer_order_no": "客户单-88",
            "delivery_date": "2026-08-20",
            "note": "首批",
            "lines": [
                {"size": "S", "quantity": 100, "customer_sku": "FZB1209001-01-red-S"},
                {"size": "M", "quantity": 80, "customer_sku": ""},
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["system_order_no"] == "YXF-00001-JS-RED"
    assert payload["customer_order_no"] == "客户单-88"
    assert payload["spu"]["code"] == "JS"
    assert payload["lines"] == [
        {"id": payload["lines"][0]["id"], "size": "S", "quantity": 100, "customer_sku": "FZB1209001-01-red-S"},
        {"id": payload["lines"][1]["id"], "size": "M", "quantity": 80, "customer_sku": ""},
    ]

    detail = client.get(f"/api/v1/sales-orders/{payload['id']}")
    assert detail.status_code == 200
    assert detail.json()["system_order_no"] == "YXF-00001-JS-RED"


def test_company_and_spu_lists_return_master_data(db_session):
    client = _client(db_session)
    company = Company(name="张鹏", code="ZP", next_order_sequence=3)
    db_session.add(company)
    db_session.commit()
    client.post(
        "/api/v1/spus",
        json={"code": "", "product_name": "裁判服", "style_name": "圆领裁判", "note": ""},
    )

    companies = client.get("/api/v1/companies")
    spus = client.get("/api/v1/spus")

    assert companies.status_code == 200
    assert companies.json()["companies"][0]["next_order_sequence"] == 3
    assert spus.status_code == 200
    assert spus.json()["spus"][0]["code"].startswith("SPU")
