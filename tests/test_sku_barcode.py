from fastapi.testclient import TestClient

from app.db import get_session
from app.main import create_app
from app.models import SkuMapping, User
from app.services.skus import upsert_sku_mapping


def _client_with_user(db_session, role: str = "admin"):
    user = User(username=f"{role}_sku", display_name="用户", password_hash="x", role=role, is_active=True)
    db_session.add(user)
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(user.id))
    return client, user


def test_barcode_scan_returns_company_product_style(db_session):
    upsert_sku_mapping(db_session, "源兴发", "裁判", "圆领裁判", "M", "SKU-REF-M", barcode="6901234567890")
    client, _worker = _client_with_user(db_session, role="worker")

    response = client.get("/mobile/report/scan?code=6901234567890")

    assert response.status_code == 200
    assert response.json() == {"company": "源兴发", "product": "裁判", "style": "圆领裁判"}


def test_barcode_scan_unknown_returns_detail(db_session):
    client, _worker = _client_with_user(db_session, role="worker")

    response = client.get("/mobile/report/scan?code=0000000000000")

    assert response.status_code == 200
    assert response.json() == {"detail": "未找到该条码对应的款式"}


def test_admin_skus_page_lists_and_edits_barcode(db_session):
    upsert_sku_mapping(db_session, "源兴发", "裁判", "圆领裁判", "M", "SKU-REF-M", barcode="")
    client, _admin = _client_with_user(db_session)

    page = client.get("/admin/skus")
    assert page.status_code == 200
    assert "SKU/条码" in page.text
    assert "SKU-REF-M" in page.text

    mapping = db_session.query(SkuMapping).one()
    response = client.post(
        f"/admin/skus/{mapping.id}/update",
        data={"company_name": "源兴发", "product_name": "裁判", "style_name": "圆领裁判", "size": "M", "sku": "SKU-REF-M2", "barcode": "6901234567890"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.refresh(mapping)
    assert mapping.sku == "SKU-REF-M2"
    assert mapping.barcode == "6901234567890"


def test_admin_skus_page_filters_by_barcode(db_session):
    upsert_sku_mapping(db_session, "源兴发", "裁判", "圆领裁判", "M", "SKU-REF-M", barcode="6901234567890")
    upsert_sku_mapping(db_session, "源兴发", "裁判", "儿童裁判", "L", "SKU-KID-L", barcode="6909999999999")
    client, _admin = _client_with_user(db_session)

    page = client.get("/admin/skus?q=6901234567890")

    assert page.status_code == 200
    assert "SKU-REF-M" in page.text
    assert "SKU-KID-L" not in page.text
