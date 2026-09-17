import json

from fastapi.testclient import TestClient

from app.db import get_session
from app.main import create_app
from app.models import Company, OperationLog, SalesOrder, SalesOrderArchive, Spu, User
from app.services.sales_orders import create_sales_order
from app.services.shipments import submit_shipment_report


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


def _seed_formal_order(db_session, customer_order_no=""):
    company = Company(name="优衣库测试", code="YQX", next_order_sequence=2)
    spu = Spu(code="JSP", product_name="裁判", style_name="成人V领", is_active=True)
    db_session.add_all([company, spu])
    db_session.flush()
    order = SalesOrder(
        system_order_no="YQX-00001-JSP",
        customer_order_no=customer_order_no,
        company_id=company.id,
        company_sequence=1,
        spu_id=spu.id,
        product_name=spu.product_name,
        style_name=spu.style_name,
        color_name="",
        color_code="",
        order_date="2026-08-09",
        delivery_date="",
        note="",
        status="active",
    )
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)
    return order


def test_formal_order_detail_includes_each_size_fulfillment_and_customer_order_no(db_session):
    client = _client(db_session)
    company = Company(name="艾润特", code="ART", next_order_sequence=1)
    spu = Spu(code="CPLL", product_name="裁判", style_name="成人拉链", is_active=True)
    db_session.add_all([company, spu])
    db_session.commit()
    order = create_sales_order(
        db_session,
        company.id,
        spu.id,
        "",
        "",
        "2026-09-03",
        [
            {"size": "S", "quantity": 400, "customer_sku": "CUSTOM-S"},
            {"size": "L", "quantity": 400, "customer_sku": "CUSTOM-L"},
        ],
        customer_order_no="P0260903116",
    )
    admin = db_session.query(User).filter_by(username="formal_order_admin").one()
    submit_shipment_report(
        db_session,
        admin.id,
        "2026-09-06",
        "",
        "",
        "",
        [{"size": "S", "quantity": 103, "order_line_id": order.lines[0].id}],
        order_id=order.id,
    )

    response = client.get(f"/api/v1/sales-orders/{order.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["system_order_no"] == order.system_order_no
    assert payload["customer_order_no"] == "P0260903116"
    assert [(line["size"], line["customer_sku"]) for line in payload["lines"]] == [
        ("S", "CUSTOM-S"),
        ("L", "CUSTOM-L"),
    ]
    assert payload["lines"][0]["totals"] == {
        "ordered": 400,
        "shipped": 103,
        "returned": 0,
        "adjusted": 0,
        "closed": 0,
        "remaining": 297,
        "over_shipped": 0,
    }
    assert payload["lines"][1]["totals"]["remaining"] == 400


def test_balance_row_identifies_formal_order_for_detail_link(db_session):
    client = _client(db_session)
    company = Company(name="艾润特", code="ART", next_order_sequence=1)
    spu = Spu(code="CPLL", product_name="裁判", style_name="成人拉链", is_active=True)
    db_session.add_all([company, spu])
    db_session.commit()
    order = create_sales_order(
        db_session, company.id, spu.id, "", "", "2026-09-03",
        [{"size": "S", "quantity": 400}], customer_order_no="P0260903116",
    )

    response = client.get("/api/v1/orders/balances?company=艾润特")

    assert response.status_code == 200
    row = response.json()["balances"][0]
    assert row["system_order_no"] == order.system_order_no
    assert row["customer_order_no"] == "P0260903116"
    assert row["sales_order_id"] == order.id
    assert row["order_id"] == order.lines[0].id


def test_update_customer_order_no_trims_and_logs(db_session):
    client = _client(db_session)
    order = _seed_formal_order(db_session)

    response = client.post(
        f"/api/v1/sales-orders/{order.id}/customer-order-no",
        json={"customer_order_no": "   ABC-123  "},
    )

    assert response.status_code == 200
    assert response.json()["customer_order_no"] == "ABC-123"
    log = (
        db_session.query(OperationLog)
        .filter(OperationLog.action == "sales_order_customer_no_update")
        .one()
    )
    assert log.target == order.system_order_no
    assert json.loads(log.detail)["after"] == "ABC-123"


def test_update_customer_order_no_rejects_more_than_160_chars(db_session):
    client = _client(db_session)
    order = _seed_formal_order(db_session)

    response = client.post(
        f"/api/v1/sales-orders/{order.id}/customer-order-no",
        json={"customer_order_no": "长" * 161},
    )

    assert response.status_code == 400


def test_update_customer_order_no_allowed_for_archived_order(db_session):
    client = _client(db_session)
    order = _seed_formal_order(db_session)
    admin = db_session.query(User).filter_by(username="formal_order_admin").one()
    db_session.add(SalesOrderArchive(order_id=order.id, archived_by=admin.id))
    db_session.commit()

    response = client.post(
        f"/api/v1/sales-orders/{order.id}/customer-order-no",
        json={"customer_order_no": "ARCHIVED-OK"},
    )

    assert response.status_code == 200
    assert response.json()["is_archived"] is True
    assert response.json()["customer_order_no"] == "ARCHIVED-OK"


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
