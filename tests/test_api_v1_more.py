from fastapi.testclient import TestClient

from app.db import get_session
from app.main import create_app
from app.models import OrderLine, ShipmentReport, User
from app.services.orders import create_order_line
from app.services.packing_drafts import create_packing_draft, submit_packing_draft
from app.services.skus import upsert_sku_mapping
from app.services.shipments import submit_shipment_report

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"a" * 256


def _client(db_session):
    admin = User(username="api_more_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    worker = User(username="api_more_worker", display_name="仓库A", password_hash="x", role="worker", is_active=True)
    db_session.add_all([admin, worker])
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))
    return client, admin, worker


def test_dashboard_returns_stats(db_session):
    client, _admin, worker = _client(db_session)
    create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)
    submit_shipment_report(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "裁判",
        "圆领裁判",
        [{"size": "M", "quantity": 10}],
        [],
        "",
    )

    response = client.get("/api/v1/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["pending"] == 1
    assert len(payload["recent"]) >= 1


def test_orders_options_and_create_order(db_session):
    client, _admin, _worker = _client(db_session)
    create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 50)

    options = client.get("/api/v1/orders/options")
    assert options.status_code == 200
    assert "源兴发" in options.json()["companies"]
    assert options.json()["choices"]["源兴发"]["裁判"]["圆领裁判"] == ["M"]

    created = client.post(
        "/api/v1/orders",
        data={
            "company_name": "源兴发",
            "product_name": "裁判",
            "style_name": "圆领裁判",
            "sizes": ["M", "L"],
            "quantities": ["10", "20"],
            "order_date": "2026-08-05",
            "delivery_date": "",
            "accessories": "帽子",
            "material": "涤纶",
            "spec_size": "110CM",
            "note": "",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["created"] == 2
    assert payload["duplicates"] == []

    duplicate = client.post(
        "/api/v1/orders",
        data={
            "company_name": "源兴发",
            "product_name": "裁判",
            "style_name": "圆领裁判",
            "sizes": ["M"],
            "quantities": ["10"],
            "order_date": "2026-08-05",
            "delivery_date": "",
        },
    )
    assert duplicate.json()["duplicates"]


def test_review_pending_approve_reject(db_session):
    client, _admin, worker = _client(db_session)
    create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)
    report = submit_shipment_report(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "裁判",
        "圆领裁判",
        [{"size": "M", "quantity": 100}],
        [],
        "",
    )
    assert report.status == "pending_review"

    pending = client.get("/api/v1/review/pending")
    assert pending.status_code == 200
    assert len(pending.json()["reports"]) == 1

    response = client.post(f"/api/v1/review/{report.id}/approve", data={"note": "ok"})
    assert response.status_code == 200
    db_session.refresh(report)
    assert report.status == "approved_after_edit"


def test_shipments_list_filter_and_waybill_update(db_session):
    client, _admin, worker = _client(db_session)
    create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)
    report = submit_shipment_report(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "裁判",
        "圆领裁判",
        [{"size": "M", "quantity": 10}],
        [],
        "",
    )
    report.waybill_no = "YT111"
    db_session.commit()

    response = client.get("/api/v1/shipments?waybill=YT111")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["reports"][0]["waybill_no"] == "YT111"

    response = client.post(f"/api/v1/shipments/{report.id}/waybill", data={"waybill_no": "YT999"})
    assert response.status_code == 200
    db_session.refresh(report)
    assert report.waybill_no == "YT999"


def test_shipments_photos_upload(db_session, tmp_path):
    client, _admin, worker = _client(db_session)
    create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)
    report = submit_shipment_report(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "裁判",
        "圆领裁判",
        [{"size": "M", "quantity": 10}],
        [],
        "",
    )

    response = client.post(
        f"/api/v1/shipments/{report.id}/photos",
        files={"photos": ("a.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200
    assert response.json()["uploaded"] == 1


def test_skus_list_update(db_session):
    client, _admin, _worker = _client(db_session)
    upsert_sku_mapping(db_session, "源兴发", "裁判", "圆领裁判", "M", "SKU-1", "6901")

    response = client.get("/api/v1/skus?q=SKU-1")
    assert response.status_code == 200
    mapping = response.json()["mappings"][0]
    assert mapping["barcode"] == "6901"

    response = client.post(
        f"/api/v1/skus/{mapping['id']}/update",
        data={
            "company_name": "源兴发",
            "product_name": "裁判",
            "style_name": "圆领裁判",
            "size": "M",
            "sku": "SKU-2",
            "barcode": "6902",
        },
    )
    assert response.status_code == 200
    response = client.get("/api/v1/skus?q=SKU-2")
    assert response.json()["mappings"][0]["sku"] == "SKU-2"


def test_daily_stats_and_goals(db_session):
    client, _admin, worker = _client(db_session)
    create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)
    report = submit_shipment_report(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "裁判",
        "圆领裁判",
        [{"size": "M", "quantity": 10}],
        [],
        "",
    )
    report.status = "auto_approved"
    db_session.commit()

    stats = client.get("/api/v1/daily-stats?ship_date=2026-08-04")
    assert stats.status_code == 200
    assert stats.json()["total"] == 10

    goals = client.get("/api/v1/goals?goal_date=2026-08-04")
    assert goals.status_code == 200
    saved = client.post("/api/v1/goals", data={"goal_date": "2026-08-04", "goal_text": "先补M码\n再清点库存"})
    assert saved.status_code == 200
    goals = client.get("/api/v1/goals?goal_date=2026-08-04")
    assert goals.json()["goal_text"] == "先补M码\n再清点库存"


def test_users_list_create_update_password(db_session):
    client, _admin, _worker = _client(db_session)

    users = client.get("/api/v1/users")
    assert users.status_code == 200
    assert len(users.json()["users"]) == 2

    created = client.post(
        "/api/v1/users",
        data={"username": "ck99", "display_name": "仓库99", "password": "pass123"},
    )
    assert created.status_code == 200
    new_user = db_session.query(User).filter_by(username="ck99").one()

    updated = client.post(
        f"/api/v1/users/{new_user.id}/update",
        data={"username": "ck99", "display_name": "仓库九九", "role": "worker", "is_active": "1"},
    )
    assert updated.status_code == 200
    assert new_user.display_name == "仓库九九"

    password = client.post(f"/api/v1/users/{new_user.id}/password", data={"password": "newpass"})
    assert password.status_code == 200


def test_logs_and_waybills(db_session, tmp_path):
    client, _admin, _worker = _client(db_session)

    logs = client.get("/api/v1/logs")
    assert logs.status_code == 200
    assert "logs" in logs.json()

    waybills = client.get("/api/v1/waybills")
    assert waybills.status_code == 200
    assert "companies" in waybills.json()

    upload = client.post(
        "/api/v1/waybills/upload",
        data={"company": "源兴发", "waybill_date": "2026-08-04"},
        files={"files": ("w.png", PNG_BYTES, "image/png")},
    )
    assert upload.status_code == 200
    assert upload.json()["imported"] == 1


def test_export_route_returns_xlsx(db_session):
    client, _admin, _worker = _client(db_session)
    create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)

    response = client.post(
        "/admin/export",
        data={"export_type": "company", "company": "源兴发", "template": "customer"},
    )

    assert response.status_code == 200
    assert "spreadsheetml" in response.headers.get("content-type", "")


def test_work_info_get_and_save(db_session):
    client, _admin, _worker = _client(db_session)

    page = client.get("/api/v1/work-info?company=源兴发&product=裁判&style=圆领裁判")
    assert page.status_code == 200
    assert len(page.json()["rows"]) == 4

    saved = client.post(
        "/api/v1/work-info",
        data={
            "company_name": "源兴发",
            "product_name": "裁判",
            "style_name": "圆领裁判",
            "section_key": ["accessories", "bag"],
            "section_title": ["产品配件信息", "包装袋信息"],
            "content": ["帽子*1", "透明袋"],
            "existing_photo_path": ["", ""],
            "existing_original_name": ["", ""],
            "remove_photo": ["0", "0"],
        },
    )
    assert saved.status_code == 200
    page = client.get("/api/v1/work-info?company=源兴发&product=裁判&style=圆领裁判")
    assert page.json()["rows"][0]["content"] == "帽子*1"
