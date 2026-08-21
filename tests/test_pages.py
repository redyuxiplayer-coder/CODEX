import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

BASE_DIR = Path(__file__).resolve().parents[1]
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"a" * 128


def test_pages_render():
    client = TestClient(create_app())
    assert client.get("/health").status_code == 200
    assert "员工登录" in client.get("/mobile/login").text


def test_admin_spa_served_when_built():
    import pytest

    spa_dir = BASE_DIR / "web" / "dist"
    if not spa_dir.exists():
        pytest.skip("web/dist 尚未构建")
    client = TestClient(create_app())
    response = client.get("/app/")
    assert response.status_code == 200
    assert 'id="app"' in response.text


def test_root_redirects_to_new_admin_spa():
    import pytest

    if not (BASE_DIR / "web" / "dist").exists():
        pytest.skip("web/dist 尚未构建")
    client = TestClient(create_app())
    response = client.get("/", follow_redirects=False)
    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/app"


def test_login_locks_after_three_failed_attempts():
    client = TestClient(create_app())

    for _ in range(3):
        response = client.post("/login", data={"username": "zhangyong", "password": "wrong"})
        assert response.status_code == 200

    locked = client.post("/login", data={"username": "zhangyong", "password": "test-admin-password"})

    assert locked.status_code == 200
    assert "登录失败过多" in locked.text
    assert "zy_user_id" not in locked.cookies


def test_mobile_home_page_renders_daily_goals():
    client = TestClient(create_app())
    client.post("/login", data={"username": "zhangyong", "password": "test-admin-password"}, follow_redirects=True)

    response = client.get("/mobile")

    assert response.status_code == 200
    assert "今日优先目标" in response.text
    assert "发货上报" in response.text


def test_admin_new_order_page_and_nav_link_render():
    client = TestClient(create_app())
    client.post("/login", data={"username": "zhangyong", "password": "test-admin-password"}, follow_redirects=True)

    page = client.get("/admin/orders/new")

    assert page.status_code == 200
    assert "新增订单" in page.text
    assert "保存订单" in page.text
    assert "window.ORDER_CHOICES" in page.text
    assert 'name="sizes"' in page.text
    assert 'name="quantities"' in page.text
    assert 'name="accessories"' in page.text
    assert 'name="material"' in page.text
    assert 'name="spec_size"' in page.text

    dashboard = client.get("/admin")
    assert dashboard.text.index("首页") < dashboard.text.index("新增订单") < dashboard.text.index("订单查询")


def test_admin_nav_hides_aliases_link_but_page_still_works():
    client = TestClient(create_app())
    client.post("/login", data={"username": "zhangyong", "password": "test-admin-password"}, follow_redirects=True)

    dashboard = client.get("/admin")

    assert dashboard.status_code == 200
    assert 'href="/admin/aliases"' not in dashboard.text
    assert "款式统一" not in dashboard.text

    page = client.get("/admin/aliases")
    assert page.status_code == 200
    assert "款式统一" in page.text


def test_admin_orders_page_uses_batch_edit_mode(db_session):
    from app.db import get_session
    from app.models import User
    from app.services.orders import create_order_line

    admin = User(username="batch_mode_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "S", 100, "2026-07-20")
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))

    response = client.get("/admin/orders")

    assert response.status_code == 200
    assert "最近新增订单修改" not in response.text
    assert 'class="inline-order-form"' not in response.text
    assert "编辑当前页面" in response.text
    assert "批量保存" not in response.text
    assert "删除" in response.text
    app.dependency_overrides.clear()


def test_admin_orders_batch_update_saves_multiple_rows_once(db_session):
    from app.db import get_session
    from app.models import OrderLine, SkuMapping, User
    from app.services.orders import create_order_line

    admin = User(username="batch_edit_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    first = create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "S", 100, "2026-07-20", "", "旧备注")
    second = create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 200, "2026-07-20", "", "旧备注")
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))

    response = client.post(
        "/admin/orders/batch-update",
        data={
            "order_ids": [str(first.id), str(second.id)],
            "company_names": ["源兴发", "高裕（源）"],
            "product_names": ["裁判", "裁判"],
            "style_names": ["圆领裁判", "儿童裁判"],
            "order_dates": ["2026-07-21", "2026-07-22"],
            "sizes": ["S", "L"],
            "skus": ["SKU-REF-S", "SKU-KID-L"],
            "quantities": ["150", "250"],
            "notes": ["第一条改好", "第二条改好"],
            "return_company": "",
            "return_item": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    saved_first = db_session.get(OrderLine, first.id)
    saved_second = db_session.get(OrderLine, second.id)
    assert saved_first.company.name == "源兴发"
    assert saved_first.quantity == 150
    assert saved_first.order_date == "2026-07-21"
    assert saved_first.note == "第一条改好"
    assert saved_second.company.name == "高裕（源）"
    assert saved_second.style_name == "儿童裁判"
    assert saved_second.size == "L"
    assert saved_second.quantity == 250
    saved_skus = {
        (row.company_name, row.product_name, row.style_name, row.size): row.sku
        for row in db_session.query(SkuMapping).all()
    }
    assert saved_skus[("源兴发", "裁判", "圆领裁判", "S")] == "SKU-REF-S"
    assert saved_skus[("高裕（源）", "裁判", "儿童裁判", "L")] == "SKU-KID-L"
    app.dependency_overrides.clear()


def test_admin_new_order_batch_creates_multiple_sizes(db_session):
    from app.db import get_session
    from app.models import OrderLine, User

    admin = User(username="order_batch_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))

    response = client.post(
        "/admin/orders/new",
        data={
            "company_name": "源兴发",
            "product_name": "小红帽",
            "style_name": "小红帽男款",
            "sizes": ["S", "M", "L"],
            "quantities": ["100", "200", "0"],
            "order_date": "2026-07-18",
            "delivery_date": "7月底",
            "accessories": "帽子*1-眼镜*1",
            "material": "涤纶",
            "spec_size": "",
            "note": "测试备注",
            "confirm_duplicate": "0",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    orders = db_session.query(OrderLine).order_by(OrderLine.size).all()
    assert [(o.size, o.quantity) for o in orders] == [("M", 200), ("S", 100)]
    assert all(o.product_name == "小红帽" and o.style_name == "小红帽男款" for o in orders)
    assert "配件：帽子*1-眼镜*1" in orders[0].note
    assert "材质：涤纶" in orders[0].note
    app.dependency_overrides.clear()


def test_admin_new_order_duplicate_requires_confirmation(db_session):
    from app.db import get_session
    from app.models import OrderLine, User
    from app.services.orders import create_order_line

    admin = User(username="duplicate_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    create_order_line(db_session, "福建", "小红帽", "小红帽男款", "M", 300, "2026-07-18")
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))

    response = client.post(
        "/admin/orders/new",
        data={
            "company_name": "福建",
            "product_name": "小红帽",
            "style_name": "小红帽男款",
            "sizes": ["M"],
            "quantities": ["100"],
            "order_date": "2026-07-18",
            "delivery_date": "",
            "accessories": "",
            "material": "",
            "spec_size": "",
            "note": "",
            "confirm_duplicate": "0",
        },
    )

    assert response.status_code == 200
    assert "可能重复" in response.text
    assert db_session.query(OrderLine).count() == 1

    confirmed = client.post(
        "/admin/orders/new",
        data={
            "company_name": "福建",
            "product_name": "小红帽",
            "style_name": "小红帽男款",
            "sizes": ["M"],
            "quantities": ["100"],
            "order_date": "2026-07-18",
            "delivery_date": "",
            "accessories": "",
            "material": "",
            "spec_size": "",
            "note": "",
            "confirm_duplicate": "1",
        },
        follow_redirects=False,
    )

    assert confirmed.status_code == 303
    assert db_session.query(OrderLine).count() == 2
    app.dependency_overrides.clear()


def test_worker_can_open_mobile_order_status_page():
    client = TestClient(create_app())
    client.post("/login", data={"username": "zhangyong", "password": "test-admin-password"}, follow_redirects=True)

    response = client.get("/mobile/orders")

    assert response.status_code == 200
    assert "补货查看" in response.text


def test_worker_can_filter_mobile_order_status_by_item_keyword():
    client = TestClient(create_app())
    client.post("/login", data={"username": "zhangyong", "password": "test-admin-password"}, follow_redirects=True)

    response = client.get("/mobile/orders?item=小偷")

    assert response.status_code == 200
    assert '<label>货物</label>' in response.text
    assert 'value="小偷"' in response.text


def test_mobile_order_status_uses_item_dropdown_not_text_input():
    client = TestClient(create_app())
    client.post("/login", data={"username": "zhangyong", "password": "test-admin-password"}, follow_redirects=True)

    response = client.get("/mobile/orders")

    assert response.status_code == 200
    assert '<select name="item"' in response.text
    assert 'placeholder="货物查询"' not in response.text


def test_mobile_orders_filters_by_status(db_session):
    from app.db import get_session
    from app.models import User
    from app.services.orders import create_order_line

    worker = User(username="orders_status_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_order_line(db_session, "源兴发", "小红帽", "小红帽男款", "M", 500)
    create_order_line(db_session, "源兴发", "小红帽", "小红帽男款", "L", 100)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    all_page = client.get("/mobile/orders?company=源兴发")
    assert "源兴发 · 小红帽男款" in all_page.text

    # 全部未发时，status=need 应显示，status=over 应为空
    need_page = client.get("/mobile/orders?company=源兴发&status=need")
    assert "源兴发 · 小红帽男款" in need_page.text
    over_page = client.get("/mobile/orders?company=源兴发&status=over")
    assert "源兴发 · 小红帽男款" not in over_page.text
    app.dependency_overrides.clear()


def test_mobile_orders_filters_by_style(db_session):
    from app.db import get_session
    from app.models import User
    from app.services.orders import create_order_line

    worker = User(username="orders_style_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_order_line(db_session, "源兴发", "小红帽", "小红帽男款", "M", 500)
    create_order_line(db_session, "源兴发", "小红帽", "小红帽女款", "L", 300)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    page = client.get("/mobile/orders?company=源兴发&item=小红帽&style=小红帽男款")

    assert page.status_code == 200
    assert "源兴发 · 小红帽男款" in page.text
    assert "源兴发 · 小红帽女款" not in page.text
    assert 'selected' in page.text
    app.dependency_overrides.clear()


def test_admin_can_save_product_work_instructions(db_session):
    from app.db import get_session
    from app.models import User
    from app.services.orders import create_order_line

    admin = User(username="work_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    create_order_line(db_session, "源兴发", "小红帽", "小红帽男款", "M", 500)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))

    page = client.get("/admin/work-info?company=源兴发&product=小红帽&style=小红帽男款")

    assert page.status_code == 200
    assert "产品配件信息" in page.text
    assert "包装袋信息" in page.text
    assert "水洗标信息" in page.text
    assert "贴标信息" in page.text

    response = client.post(
        "/admin/work-info",
        data={
            "company_name": "源兴发",
            "product_name": "小红帽",
            "style_name": "小红帽男款",
            "section_key": ["accessories", "bag", "wash_label", "sticker", "custom"],
            "section_title": ["产品配件信息", "包装袋信息", "水洗标信息", "贴标信息", "装箱备注"],
            "content": ["帽子*1-眼镜*1", "28*35透明袋", "左侧缝水洗标", "外袋右上角贴SKU", "XL用大袋"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    saved = client.get("/admin/work-info?company=源兴发&product=小红帽&style=小红帽男款")
    assert "帽子*1-眼镜*1" in saved.text
    assert "XL用大袋" in saved.text
    app.dependency_overrides.clear()


def test_worker_can_open_product_work_info_from_mobile_orders(db_session):
    from app.db import get_session
    from app.models import User
    from app.services.orders import create_order_line
    from app.services.work_info import save_work_info

    worker = User(username="work_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_order_line(db_session, "源兴发", "小红帽", "小红帽男款", "M", 500)
    save_work_info(
        db_session,
        "源兴发",
        "小红帽",
        "小红帽男款",
        [
            {"section_key": "accessories", "section_title": "产品配件信息", "content": "帽子*1"},
            {"section_key": "bag", "section_title": "包装袋信息", "content": "透明袋"},
        ],
    )
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    orders = client.get("/mobile/orders")
    assert "包装/贴标" in orders.text

    page = client.get("/mobile/work-info?company=源兴发&product=小红帽&style=小红帽男款")
    assert page.status_code == 200
    assert "产品配件信息" in page.text
    assert "帽子*1" in page.text
    assert "包装袋信息" in page.text
    assert "透明袋" in page.text
    assert "保存" not in page.text
    app.dependency_overrides.clear()


def test_shipment_photo_route_returns_thumbnail_when_requested(db_session, tmp_path, monkeypatch):
    from PIL import Image

    from app.db import get_session
    from app.models import ShipmentPhoto, ShipmentReport, User
    from app.services import photos as photo_service

    monkeypatch.setattr(photo_service, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(photo_service, "THUMBNAIL_DIR", tmp_path / "thumbs")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    worker = User(username="thumb_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.flush()
    source = tmp_path / "box.jpg"
    Image.new("RGB", (1000, 700), (120, 60, 60)).save(source, "JPEG")
    report = ShipmentReport(
        user_id=worker.id,
        ship_date="2026-07-17",
        company_name="源兴发",
        product_name="小红帽",
        style_name="小红帽男款",
        status="auto_approved",
        review_reason="",
    )
    db_session.add(report)
    db_session.flush()
    photo = ShipmentPhoto(report_id=report.id, file_path=str(source), original_name="box.jpg")
    db_session.add(photo)
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    response = client.get(f"/photos/shipment/{photo.id}?thumb=1")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    thumb_file = tmp_path / "thumbs" / "box_thumb.jpg"
    assert thumb_file.exists()
    app.dependency_overrides.clear()


def test_admin_shipments_paginates_ten_per_page(db_session):
    from datetime import datetime, timedelta

    from app.db import get_session
    from app.models import ShipmentReport, User

    admin = User(username="page_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    base = datetime(2026, 7, 1, 8, 0, 0)
    for index in range(12):
        db_session.add(
            ShipmentReport(
                user_id=admin.id,
                ship_date=f"2026-07-{index + 1:02d}",
                company_name="源兴发",
                product_name="小红帽",
                style_name=f"款式{index + 1}",
                status="auto_approved",
                review_reason="",
                created_at=base + timedelta(minutes=index),
            )
        )
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))

    page1 = client.get("/admin/shipments")
    page2 = client.get("/admin/shipments?page=2")

    assert page1.status_code == 200
    assert "款式12</td>" in page1.text
    assert "款式1</td>" not in page1.text
    assert "下一页" in page1.text
    assert page2.status_code == 200
    assert "款式1</td>" in page2.text
    assert "款式12</td>" not in page2.text
    app.dependency_overrides.clear()


def test_mobile_my_reports_loads_more_pages(db_session):
    from datetime import datetime, timedelta

    from app.db import get_session
    from app.models import ShipmentReport, User

    worker = User(username="load_more_worker", display_name="小杰", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    base = datetime(2026, 7, 1, 8, 0, 0)
    for index in range(12):
        db_session.add(
            ShipmentReport(
                user_id=worker.id,
                ship_date=f"2026-07-{index + 1:02d}",
                company_name="源兴发",
                product_name="小红帽",
                style_name=f"款式{index + 1}",
                status="auto_approved",
                review_reason="",
                created_at=base + timedelta(minutes=index),
            )
        )
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    page1 = client.get("/mobile/my-reports")

    assert page1.status_code == 200
    assert "小红帽 / 款式12 /" in page1.text
    assert "小红帽 / 款式1 /" not in page1.text
    assert "小红帽 / 款式2 /" not in page1.text
    assert "加载更多" in page1.text
    app.dependency_overrides.clear()


def test_mobile_orders_recent_shipments_loads_more(db_session):
    from datetime import datetime, timedelta

    from app.db import get_session
    from app.models import ShipmentReport, User

    worker = User(username="orders_recent_worker", display_name="小杰", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    base = datetime(2026, 7, 1, 8, 0, 0)
    for index in range(12):
        db_session.add(
            ShipmentReport(
                user_id=worker.id,
                ship_date=f"2026-07-{index + 1:02d}",
                company_name="源兴发",
                product_name="小红帽",
                style_name=f"款式{index + 1}",
                status="auto_approved",
                review_reason="",
                created_at=base + timedelta(minutes=index),
            )
        )
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    page = client.get("/mobile/orders")

    assert page.status_code == 200
    assert "款式12 / 小杰 /" in page.text
    assert "款式1 / 小杰 /" not in page.text
    assert "加载更多" in page.text

    partial = client.get("/mobile/orders?page=2&partial=1")
    assert partial.status_code == 200
    assert "款式1 / 小杰 /" in partial.text
    app.dependency_overrides.clear()


def test_worker_work_info_proposal_requires_admin_approval(db_session):
    from app.db import get_session
    from app.models import User
    from app.services.orders import create_order_line

    admin = User(username="work_review_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    worker = User(username="work_review_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add_all([admin, worker])
    db_session.commit()
    create_order_line(db_session, "源兴发", "小红帽", "小红帽男款", "M", 500)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)

    client.cookies.set("zy_user_id", str(worker.id))
    response = client.post(
        "/mobile/work-info",
        data={
            "company_name": "源兴发",
            "product_name": "小红帽",
            "style_name": "小红帽男款",
            "section_key": ["accessories", "bag", "wash_label", "sticker"],
            "section_title": ["产品配件信息", "包装袋信息", "水洗标信息", "贴标信息"],
            "content": ["帽子*1", "透明袋", "", ""],
        },
    )
    assert response.status_code == 200
    assert "已提交老板审核" in response.text

    before = client.get("/mobile/work-info?company=源兴发&product=小红帽&style=小红帽男款")
    assert "帽子*1" not in before.text

    client.cookies.set("zy_user_id", str(admin.id))
    review = client.get("/admin/review")
    assert "作业信息待审核" in review.text
    assert "帽子*1" in review.text

    approved = client.post("/admin/work-info/proposals/1/approve", follow_redirects=False)
    assert approved.status_code == 303

    after = client.get("/admin/work-info?company=源兴发&product=小红帽&style=小红帽男款")
    assert "帽子*1" in after.text
    app.dependency_overrides.clear()


def test_work_info_proposal_can_include_photo(db_session, tmp_path):
    from app.db import get_session
    from app.models import User, WorkInfoLine
    from app.services.orders import create_order_line

    admin = User(username="work_photo_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    worker = User(username="work_photo_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add_all([admin, worker])
    db_session.commit()
    create_order_line(db_session, "源兴发", "小红帽", "小红帽男款", "M", 500)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    response = client.post(
        "/mobile/work-info",
        data={
            "company_name": "源兴发",
            "product_name": "小红帽",
            "style_name": "小红帽男款",
            "section_key": ["accessories", "bag", "wash_label", "sticker"],
            "section_title": ["产品配件信息", "包装袋信息", "水洗标信息", "贴标信息"],
            "content": ["帽子*1", "", "", ""],
        },
        files={
            "photos": ("accessories.png", PNG_BYTES, "image/png"),
        },
    )
    assert response.status_code == 200

    client.cookies.set("zy_user_id", str(admin.id))
    review = client.get("/admin/review")
    assert "/photos/work-info/proposal/" in review.text

    approved = client.post("/admin/work-info/proposals/1/approve", follow_redirects=False)
    assert approved.status_code == 303
    line = db_session.query(WorkInfoLine).filter_by(section_key="accessories").one()
    assert line.photo_path
    assert line.original_name == "accessories.png"

    page = client.get("/admin/work-info?company=源兴发&product=小红帽&style=小红帽男款")
    assert "/photos/work-info/" in page.text
    app.dependency_overrides.clear()


def test_work_info_photo_can_be_removed_through_review(db_session, tmp_path):
    from app.db import get_session
    from app.models import User, WorkInfoLine
    from app.services.orders import create_order_line
    from app.services.work_info import save_work_info

    admin = User(username="work_remove_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    worker = User(username="work_remove_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add_all([admin, worker])
    db_session.commit()
    photo = tmp_path / "wrong.png"
    photo.write_bytes(b"wrong")
    create_order_line(db_session, "源兴发", "小红帽", "小红帽男款", "M", 500)
    save_work_info(
        db_session,
        "源兴发",
        "小红帽",
        "小红帽男款",
        [
            {
                "section_key": "accessories",
                "section_title": "产品配件信息",
                "content": "帽子*1",
                "photo_path": str(photo),
                "original_name": "wrong.png",
            },
        ],
    )
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)

    client.cookies.set("zy_user_id", str(worker.id))
    page = client.get("/mobile/work-info?company=源兴发&product=小红帽&style=小红帽男款")
    assert "删除这张图片" in page.text
    response = client.post(
        "/mobile/work-info",
        data={
            "company_name": "源兴发",
            "product_name": "小红帽",
            "style_name": "小红帽男款",
            "section_key": ["accessories", "bag", "wash_label", "sticker"],
            "section_title": ["产品配件信息", "包装袋信息", "水洗标信息", "贴标信息"],
            "content": ["帽子*1", "", "", ""],
            "existing_photo_path": [str(photo), "", "", ""],
            "existing_original_name": ["wrong.png", "", "", ""],
            "remove_photo": ["1", "0", "0", "0"],
        },
    )
    assert response.status_code == 200

    client.cookies.set("zy_user_id", str(admin.id))
    approved = client.post("/admin/work-info/proposals/1/approve", follow_redirects=False)
    assert approved.status_code == 303
    line = db_session.query(WorkInfoLine).filter_by(section_key="accessories").one()
    assert line.photo_path == ""
    assert line.original_name == ""

    after = client.get("/admin/work-info?company=源兴发&product=小红帽&style=小红帽男款")
    assert "wrong.png" not in after.text
    app.dependency_overrides.clear()


def test_mobile_today_packed_page_renders():
    client = TestClient(create_app())
    client.post("/login", data={"username": "zhangyong", "password": "test-admin-password"}, follow_redirects=True)

    response = client.get("/mobile/report")

    assert response.status_code == 200
    assert "发货上报" in response.text
    assert "保存草稿" in response.text
    assert "确认无误，提交上报" in response.text or "还没有未提交包货草稿" in response.text


def test_mobile_report_page_does_not_upload_photos():
    client = TestClient(create_app())
    client.post("/login", data={"username": "zhangyong", "password": "test-admin-password"}, follow_redirects=True)

    response = client.get("/mobile/report")

    assert response.status_code == 200
    assert "单包照片" not in response.text
    assert 'type="file"' not in response.text
    assert 'name="photos"' not in response.text
    assert "先保存草稿，确认无误后提交老板审核" in response.text
    assert "照片" not in response.text


def test_mobile_report_page_does_not_build_full_balance_payload(monkeypatch):
    import app.main as main_module

    calls = {"count": 0}

    def fake_balances(session):
        calls["count"] += 1
        return [
            {
                "company": "源兴发",
                "product": "小红帽",
                "style": "小红帽男款",
                "size": "M",
                "ordered": 300,
                "shipped": 100,
                "remaining": 200,
                "over_shipped": 0,
            }
        ]

    monkeypatch.setattr(main_module, "get_order_balances", fake_balances)
    client = TestClient(create_app())
    client.post("/login", data={"username": "zhangyong", "password": "test-admin-password"}, follow_redirects=True)
    calls["count"] = 0

    response = client.get("/mobile/report")

    assert response.status_code == 200
    assert calls["count"] == 0
    assert "ORDER_BALANCES" not in response.text


def test_mobile_report_options_load_in_steps(db_session):
    from app.db import get_session
    from app.models import User
    from app.services.orders import create_order_line

    worker = User(username="step_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_order_line(db_session, "源兴发", "小红帽", "小红帽男款", "M", 300)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    companies = client.get("/mobile/report/options").json()
    products = client.get("/mobile/report/options?company=源兴发").json()
    styles = client.get("/mobile/report/options?company=源兴发&product=小红帽").json()
    sizes = client.get("/mobile/report/options?company=源兴发&product=小红帽&style=小红帽男款").json()

    assert companies == {"companies": ["源兴发"]}
    assert products == {"products": ["小红帽"]}
    assert styles == {"styles": ["小红帽男款"]}
    assert sizes["sizes"] == ["M"]
    assert sizes["balances"]["M"]["ordered"] == 300
    app.dependency_overrides.clear()


def test_mobile_report_options_resolve_alias_before_loading_sizes(db_session):
    from app.db import get_session
    from app.models import User
    from app.services.aliases import create_product_alias
    from app.services.orders import create_order_line

    worker = User(username="alias_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_order_line(db_session, "广东茉莉", "啤酒节背心", "啤酒节", "S", 100)
    create_order_line(db_session, "广东茉莉", "啤酒节背心", "啤酒节", "M", 450)
    create_product_alias(db_session, "广东茉莉", "啤酒节背心", "啤酒节", "啤酒节", "啤酒节男款")

    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    sizes = client.get("/mobile/report/options?company=广东茉莉&product=啤酒节背心&style=啤酒节").json()

    assert sizes["sizes"] == ["S", "M"]
    assert sizes["balances"]["S"]["ordered"] == 100
    assert sizes["balances"]["M"]["ordered"] == 450
    app.dependency_overrides.clear()


def test_mobile_report_options_keep_duplicate_order_lines_separate(db_session):
    from app.db import get_session
    from app.models import User
    from app.services.orders import create_order_line

    worker = User(username="split_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    first = create_order_line(db_session, "艾润特", "裁判", "圆领裁判", "L", 1100, "2026-06-02")
    second = create_order_line(db_session, "艾润特", "裁判", "圆领裁判", "L", 2000, "2026-06-17")

    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    payload = client.get("/mobile/report/options?company=艾润特&product=裁判&style=圆领裁判").json()

    assert [line["order_line_id"] for line in payload["lines"]] == [first.id, second.id]
    assert [line["ordered"] for line in payload["lines"]] == [1100, 2000]
    assert payload["balances"]["L"]["ordered"] == 3100
    app.dependency_overrides.clear()


def test_mobile_packing_draft_preserves_order_line_id(db_session):
    from app.db import get_session
    from app.models import PackingDraft, User
    from app.services.orders import create_order_line

    worker = User(username="draft_order_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    order = create_order_line(db_session, "艾润特", "裁判", "圆领裁判", "L", 1100, "2026-06-02")

    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    response = client.post(
        "/mobile/today/new",
        data={
            "pack_date": "2026-07-31",
            "company_name": "艾润特",
            "product_name": "裁判",
            "style_name": "圆领裁判",
            "order_line_ids": [str(order.id)],
            "sizes": ["L"],
            "quantities": ["60+40"],
            "note": "按单上报",
            "shipping_method": "courier",
            "waybill_no": "YT-PAGE-ORDERLINE-001",
            "package_count": "2",
            "weight_kg": "8.5",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    draft = db_session.query(PackingDraft).one()
    assert draft.lines[0].order_line_id == order.id
    assert draft.lines[0].quantity == 100
    app.dependency_overrides.clear()


def test_mobile_packing_draft_submit_keeps_order_line_id_on_shipment(db_session):
    from app.db import get_session
    from app.models import ShipmentReport, User
    from app.services.orders import create_order_line
    from app.services.packing_drafts import create_packing_draft

    worker = User(username="submit_order_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    order = create_order_line(db_session, "艾润特", "裁判", "圆领裁判", "L", 1100, "2026-06-02")
    draft = create_packing_draft(
        db_session,
        worker.id,
        "2026-07-31",
        "艾润特",
        "裁判",
        "圆领裁判",
        [{"order_line_id": order.id, "size": "L", "quantity": "100"}],
        "按单提交",
        [],
        "YT-PAGE-SUBMIT-001",
        None,
        "courier",
        1,
        2.0,
    )

    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    response = client.post(f"/mobile/today/{draft.id}/submit", follow_redirects=False)

    assert response.status_code == 303
    report = db_session.query(ShipmentReport).one()
    assert report.lines[0].order_line_id == order.id
    assert report.lines[0].quantity == 100
    app.dependency_overrides.clear()


def test_mobile_report_hides_submitted_package_draft(db_session):
    from app.db import get_session
    from app.models import User
    from app.services.orders import create_order_line
    from app.services.packing_drafts import create_packing_draft, submit_packing_draft

    worker = User(username="hidden_draft_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_order_line(db_session, "艾润特", "裁判", "圆领裁判", "L", 1100)
    draft = create_packing_draft(
        db_session,
        worker.id,
        "2026-07-31",
        "艾润特",
        "裁判",
        "圆领裁判",
        [{"size": "L", "quantity": "100"}],
        "待提交",
        [],
        "YT-PAGE-HIDE-001",
        None,
        "courier",
        1,
        2.1,
    )
    submit_packing_draft(db_session, draft.id, worker.id)

    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    page = client.get("/mobile/report")

    assert page.status_code == 200
    assert f"/mobile/today/{draft.id}/update" not in page.text
    assert f"/mobile/today/{draft.id}/submit" not in page.text
    app.dependency_overrides.clear()


def test_mobile_report_draft_rows_have_plus_button(db_session):
    from datetime import date

    from app.db import get_session
    from app.models import User
    from app.services.orders import create_order_line
    from app.services.packing_drafts import create_packing_draft

    worker = User(username="plus_draft_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_order_line(db_session, "艾润特", "裁判", "圆领裁判", "L", 1100)
    create_packing_draft(
        db_session,
        worker.id,
        date.today().isoformat(),
        "艾润特",
        "裁判",
        "圆领裁判",
        [{"size": "L", "quantity": "100"}],
        "待提交",
        [],
        "YT-PAGE-PLUS-001",
        None,
        "courier",
        1,
        2.2,
    )

    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    page = client.get("/mobile/report")

    assert page.status_code == 200
    assert 'class="plus-btn"' in page.text or 'plus-btn' in page.text
    app.dependency_overrides.clear()


def test_mobile_my_reports_rows_have_plus_button_and_lightbox(db_session, tmp_path):
    from app.db import get_session
    from app.models import ShipmentLine, ShipmentPhoto, ShipmentReport, User

    worker = User(username="plus_report_worker", display_name="小杰", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.flush()
    photo = tmp_path / "package.png"
    photo.write_bytes(b"photo")
    report = ShipmentReport(
        user_id=worker.id,
        ship_date="2026-07-17",
        company_name="源兴发",
        product_name="小红帽",
        style_name="小红帽男",
        status="pending_review",
        review_reason="等待老板审核",
    )
    db_session.add(report)
    db_session.flush()
    db_session.add(ShipmentLine(report_id=report.id, size="S", quantity=50))
    db_session.add(ShipmentPhoto(report_id=report.id, file_path=str(photo), original_name="package.png"))
    db_session.commit()

    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    page = client.get("/mobile/my-reports")

    assert page.status_code == 200
    assert "plus-btn" in page.text
    assert "data-lightbox" in page.text
    app.dependency_overrides.clear()


def test_admin_can_upload_photos_to_shipment_report(db_session, tmp_path, monkeypatch):
    from app.db import get_session
    from app.models import ShipmentLine, ShipmentPhoto, ShipmentReport, User
    from app.services import photos as photo_service

    monkeypatch.setattr(photo_service, "UPLOAD_DIR", tmp_path)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    admin = User(username="photo_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.flush()
    report = ShipmentReport(
        user_id=admin.id,
        ship_date="2026-07-18",
        company_name="源兴发",
        product_name="小红帽",
        style_name="小红帽男款",
        status="pending_review",
        review_reason="员工上报，等待老板审核",
    )
    db_session.add(report)
    db_session.flush()
    db_session.add(ShipmentLine(report_id=report.id, size="M", quantity=100))
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))

    page = client.get("/admin/shipments")
    assert 'name="photos"' in page.text
    assert "补传照片" in page.text

    response = client.post(
        f"/admin/shipments/{report.id}/photos",
        files=[
            ("photos", ("box-1.png", PNG_BYTES, "image/png")),
            ("photos", ("box-2.png", PNG_BYTES, "image/png")),
        ],
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert db_session.query(ShipmentPhoto).count() == 2
    assert len(list(tmp_path.glob("源兴发/2026-07-18_源兴发_小红帽男款_*.png"))) == 2
    app.dependency_overrides.clear()


def test_admin_shipments_filters_by_company_not_review_status(db_session):
    from app.db import get_session
    from app.models import ShipmentLine, ShipmentReport, User

    admin = User(username="shipment_filter_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.flush()
    first = ShipmentReport(
        user_id=admin.id,
        ship_date="2026-07-18",
        company_name="源兴发",
        product_name="小红帽",
        style_name="小红帽男款",
        status="pending_review",
        review_reason="等待老板审核",
    )
    second = ShipmentReport(
        user_id=admin.id,
        ship_date="2026-07-18",
        company_name="福建",
        product_name="小偷",
        style_name="小偷女款",
        status="auto_approved",
        review_reason="",
    )
    db_session.add_all([first, second])
    db_session.flush()
    db_session.add_all(
        [
            ShipmentLine(report_id=first.id, size="M", quantity=100),
            ShipmentLine(report_id=second.id, size="L", quantity=80),
        ]
    )
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))

    page = client.get("/admin/shipments?company=源兴发")

    assert page.status_code == 200
    assert "全部公司" in page.text
    assert "全部审核状态" not in page.text
    assert "源兴发" in page.text
    assert "小红帽男款" in page.text
    assert "小偷女款" not in page.text
    app.dependency_overrides.clear()


def test_mobile_report_draft_ignores_uploaded_photos(db_session):
    from app.db import get_session
    from app.models import PackingDraft, User
    from app.services.orders import create_order_line

    worker = User(username="no_photo_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_order_line(db_session, "源兴发", "小红帽", "小红帽男款", "L", 500)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    response = client.post(
        "/mobile/today/new",
        data={
            "pack_date": "2026-07-18",
            "company_name": "源兴发",
            "product_name": "小红帽",
            "style_name": "小红帽男款",
            "sizes": ["L"],
            "quantities": ["225"],
            "note": "",
            "shipping_method": "courier",
            "waybill_no": "YT-PAGE-NOPHOTO-001",
            "package_count": "2",
            "weight_kg": "10.5",
        },
        files=[("photos", (f"box-{index}.png", b"box", "image/png")) for index in range(7)],
        follow_redirects=False,
    )

    assert response.status_code == 303
    draft = db_session.query(PackingDraft).one()
    assert len(draft.photos) == 0
    app.dependency_overrides.clear()


def test_mobile_report_quantity_accepts_addition_expression(db_session):
    from app.db import get_session
    from app.models import PackingDraft, User
    from app.services.orders import create_order_line

    worker = User(username="quantity_expr_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_order_line(db_session, "源兴发", "小红帽", "小红帽男款", "M", 500)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    response = client.post(
        "/mobile/today/new",
        data={
            "pack_date": "2026-07-18",
            "company_name": "源兴发",
            "product_name": "小红帽",
            "style_name": "小红帽男款",
            "sizes": ["M"],
            "quantities": ["60+60+60+45"],
            "note": "",
            "shipping_method": "courier",
            "waybill_no": "YT-PAGE-QTY-001",
            "package_count": "2",
            "weight_kg": "10.6",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    draft = db_session.query(PackingDraft).one()
    assert draft.lines[0].quantity == 225
    app.dependency_overrides.clear()


def test_mobile_report_page_uses_lazy_order_balance_hint_data():
    client = TestClient(create_app())
    client.post("/login", data={"username": "zhangyong", "password": "test-admin-password"}, follow_redirects=True)

    response = client.get("/mobile/report")

    assert response.status_code == 200
    assert "window.ORDER_COMPANIES" in response.text
    assert "window.ORDER_BALANCES" not in response.text


def test_mobile_report_shows_editable_required_date_and_all_open_drafts(db_session):
    from datetime import date, timedelta

    from app.db import get_session
    from app.models import User
    from app.services.packing_drafts import create_packing_draft

    worker = User(username="route_old_draft_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    old_date = (date.today() - timedelta(days=2)).isoformat()
    old_draft = create_packing_draft(
        db_session,
        worker.id,
        old_date,
        "源兴发",
        "小红帽",
        "小红帽男款",
        [{"size": "L", "quantity": 15}],
        "前天草稿",
        waybill_no="YT-OLD-DRAFT-001",
        shipping_method="courier",
        package_count=1,
        weight_kg=2.5,
    )
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    page = client.get("/mobile/report")

    assert page.status_code == 200
    assert 'name="pack_date"' in page.text
    assert 'type="date"' in page.text
    assert "required" in page.text
    assert f'max="{date.today().isoformat()}"' in page.text
    assert old_draft.package_no in page.text
    app.dependency_overrides.clear()


def test_mobile_report_renders_order_filters_and_existing_huolala_choices(db_session):
    from app.db import get_session
    from app.models import Company, Spu, User
    from app.services.logistics import create_waybill_record
    from app.services.packing_drafts import create_packing_draft
    from app.services.sales_orders import create_sales_order

    worker = User(username="route_filter_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    other = User(username="route_filter_other", display_name="同事", password_hash="x", role="worker", is_active=True)
    company = Company(name="源兴发", code="YXF", next_order_sequence=1)
    spu = Spu(code="LALD", product_name="啦啦队", style_name="亮片啦啦队")
    db_session.add_all([worker, other, company, spu])
    db_session.commit()
    create_sales_order(
        db_session,
        company.id,
        spu.id,
        "红色",
        "RED",
        "2026-08-09",
        [{"size": "L", "quantity": 100}, {"size": "XL", "quantity": 70}],
    )
    create_packing_draft(
        db_session,
        other.id,
        "2026-08-09",
        "源兴发",
        "啦啦队",
        "亮片啦啦队",
        [{"size": "L", "quantity": 2}],
        "共享车次",
        waybill_no="HL-SHARED-001",
        shipping_method="huolala",
        package_count=3,
        weight_kg=12.5,
    )
    create_packing_draft(
        db_session,
        other.id,
        "2026-08-10",
        "别家公司",
        "啦啦队",
        "亮片啦啦队",
        [{"size": "L", "quantity": 2}],
        "不应复用",
        waybill_no="HL-OTHER-001",
        shipping_method="huolala",
        package_count=4,
        weight_kg=13.5,
    )
    create_waybill_record(
        db_session,
        other.id,
        "源兴发",
        "2026-08-09",
        "HL-REC-001",
        courier="货拉拉",
        weight_kg=12.8,
        package_count=5,
    )
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    page = client.get("/mobile/report")
    trips = client.get("/mobile/report/huolala-trips?company=源兴发&ship_date=2026-08-09")

    assert page.status_code == 200
    assert 'id="order-company-filter"' in page.text
    assert 'id="order-style-color-filter"' in page.text
    assert 'id="order-search-filter"' in page.text
    assert "订单号｜下单日期｜颜色｜还差摘要" in page.text
    assert "HL-SHARED-001" not in page.text
    assert "HL-OTHER-001" not in page.text
    assert "HL-REC-001" not in page.text
    assert "新建车次" in page.text
    assert "已有车次" in page.text
    assert trips.status_code == 200
    assert [row["waybill_no"] for row in trips.json()["trips"]] == ["HL-SHARED-001", "HL-REC-001"]
    app.dependency_overrides.clear()


def test_mobile_report_huolala_trip_endpoint_requires_exact_company_and_date(db_session):
    from app.db import get_session
    from app.models import User
    from app.services.logistics import create_waybill_record
    from app.services.packing_drafts import create_packing_draft

    worker = User(username="route_trip_api_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    other = User(username="route_trip_api_other", display_name="同事", password_hash="x", role="worker", is_active=True)
    db_session.add_all([worker, other])
    db_session.commit()
    create_packing_draft(
        db_session,
        other.id,
        "2026-08-09",
        "源兴发",
        "啦啦队",
        "亮片啦啦队",
        [{"size": "L", "quantity": 2}],
        "共享车次",
        waybill_no="HL-MATCH-001",
        shipping_method="huolala",
        package_count=3,
        weight_kg=12.5,
    )
    create_packing_draft(
        db_session,
        other.id,
        "2026-08-10",
        "源兴发",
        "啦啦队",
        "亮片啦啦队",
        [{"size": "L", "quantity": 2}],
        "不同日期",
        waybill_no="HL-WRONG-DATE-001",
        shipping_method="huolala",
        package_count=4,
        weight_kg=13.5,
    )
    create_waybill_record(
        db_session,
        other.id,
        "别家公司",
        "2026-08-09",
        "HL-WRONG-COMPANY-001",
        courier="货拉拉",
        weight_kg=9.5,
        package_count=2,
    )
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    anon = TestClient(app)
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    unauthorized = anon.get("/mobile/report/huolala-trips?company=源兴发&ship_date=2026-08-09")
    matched = client.get("/mobile/report/huolala-trips?company=源兴发&ship_date=2026-08-09")
    missing = client.get("/mobile/report/huolala-trips?company=&ship_date=2026-08-09")

    assert unauthorized.status_code == 401
    assert matched.status_code == 200
    assert [row["waybill_no"] for row in matched.json()["trips"]] == ["HL-MATCH-001"]
    assert missing.status_code == 200
    assert missing.json()["trips"] == []
    app.dependency_overrides.clear()


def test_mobile_report_form_renders_basic_logistics_fields(db_session):
    from app.db import get_session
    from app.models import User

    worker = User(username="route_fields_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    page = client.get("/mobile/report")

    assert page.status_code == 200
    for field_name in ['name="shipping_method"', 'name="package_count"', 'name="weight_kg"', 'name="pack_date"']:
        assert field_name in page.text
    assert 'name="waybill_no"' in page.text
    assert 'name="waybill_no" placeholder="例如 YT1234567890" required' not in page.text
    assert "货拉拉可留空自动生成车次号" in page.text
    app.dependency_overrides.clear()


def test_mobile_new_requires_complete_logistics(db_session):
    from app.db import get_session
    from app.models import Company, Spu, User
    from app.services.sales_orders import create_sales_order

    worker = User(username="route_requires_logistics_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    company = Company(name="源兴发", code="YXF", next_order_sequence=1)
    spu = Spu(code="REQL", product_name="裁判", style_name="圆领裁判")
    db_session.add_all([worker, company, spu])
    db_session.commit()
    order = create_sales_order(
        db_session,
        company.id,
        spu.id,
        "红色",
        "RED",
        "2026-08-09",
        [{"size": "L", "quantity": 100}],
    )
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set("zy_user_id", str(worker.id))

    response = client.post(
        "/mobile/today/new",
        data={
            "pack_date": "2026-08-09",
            "order_id": str(order.id),
            "order_line_ids": [str(order.lines[0].id)],
            "sizes": ["L"],
            "quantities": ["20"],
            "shipping_method": "",
            "waybill_no": "",
            "package_count": "2",
            "weight_kg": "9.5",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "请选择发货方式"
    app.dependency_overrides.clear()


def test_mobile_route_create_update_and_submit_packing_draft_with_logistics(db_session):
    from app.db import get_session
    from app.models import PackingDraft, ShipmentReport, User, WaybillRecord
    from app.services.orders import create_order_line

    worker = User(username="route_logistics_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_order_line(db_session, "源兴发", "小红帽", "小红帽男款", "L", 500)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    created = client.post(
        "/mobile/today/new",
        data={
            "pack_date": "2026-07-18",
            "company_name": "源兴发",
            "product_name": "小红帽",
            "style_name": "小红帽男款",
            "sizes": ["L"],
            "quantities": ["225"],
            "note": "首包",
            "shipping_method": "courier",
            "waybill_no": "YT-ROUTE-001",
            "package_count": "2",
            "weight_kg": "11.5",
        },
        follow_redirects=False,
    )

    assert created.status_code == 303
    draft = db_session.query(PackingDraft).one()
    assert draft.shipping_method == "courier"
    assert draft.package_count == 2
    assert draft.weight_kg == 11.5

    updated = client.post(
        f"/mobile/today/{draft.id}/update",
        data={
            "pack_date": "2026-07-18",
            "sizes": ["L"],
            "order_line_ids": [""],
            "quantities": ["230"],
            "note": "改成230",
            "shipping_method": "courier",
            "waybill_no": "YT-ROUTE-001",
            "package_count": "3",
            "weight_kg": "12.5",
        },
        follow_redirects=False,
    )

    assert updated.status_code == 303
    db_session.refresh(draft)
    assert draft.lines[0].quantity == 230
    assert draft.package_count == 3
    assert draft.weight_kg == 12.5

    submitted = client.post(f"/mobile/today/{draft.id}/submit", follow_redirects=False)

    assert submitted.status_code == 303
    report = db_session.query(ShipmentReport).one()
    assert report.waybill_no == "YT-ROUTE-001"
    assert report.waybill_id is not None
    waybill = db_session.query(WaybillRecord).one()
    assert waybill.package_count == 3
    assert waybill.weight_kg == 12.5
    app.dependency_overrides.clear()


def test_mobile_route_create_huolala_draft_without_waybill_no(db_session):
    from app.db import get_session
    from app.models import PackingDraft, User
    from app.services.orders import create_order_line

    worker = User(username="route_huolala_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_order_line(db_session, "源兴发", "小红帽", "小红帽男款", "L", 500)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    created = client.post(
        "/mobile/today/new",
        data={
            "pack_date": "2026-07-18",
            "company_name": "源兴发",
            "product_name": "小红帽",
            "style_name": "小红帽男款",
            "sizes": ["L"],
            "quantities": ["225"],
            "note": "货拉拉首包",
            "shipping_method": "huolala",
            "waybill_no": "",
            "package_count": "2",
            "weight_kg": "11.5",
        },
        follow_redirects=False,
    )

    assert created.status_code == 303
    draft = db_session.query(PackingDraft).one()
    assert draft.shipping_method == "huolala"
    assert draft.waybill_no == "货拉拉-20260718-001"
    app.dependency_overrides.clear()


def test_mobile_huolala_route_requires_explicit_existing_trip_provenance(db_session):
    from app.db import get_session
    from app.models import PackingDraft, User
    from app.services.orders import create_order_line

    worker = User(username="route_huolala_provenance", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_order_line(db_session, "源兴发", "小红帽", "小红帽男款", "L", 500)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    response = client.post(
        "/mobile/today/new",
        data={
            "pack_date": "2026-07-18",
            "company_name": "源兴发",
            "product_name": "小红帽",
            "style_name": "小红帽男款",
            "sizes": ["L"],
            "quantities": ["225"],
            "shipping_method": "huolala",
            "trip_mode": "existing",
            "waybill_no": "",
            "package_count": "2",
            "weight_kg": "11.5",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "同公司同日期" in response.json()["detail"]
    assert db_session.query(PackingDraft).count() == 0
    app.dependency_overrides.clear()


def test_mobile_report_form_submits_trip_mode_under_one_server_field(db_session):
    from app.db import get_session
    from app.models import User

    worker = User(username="route_trip_mode_field", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    page = client.get("/mobile/report")

    assert page.status_code == 200
    assert page.text.count('name="trip_mode"') >= 2
    assert 'name="trip_mode_new"' not in page.text
    app.dependency_overrides.clear()


def test_mobile_report_submit_script_does_not_reenter_submit_event():
    script = (BASE_DIR / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert "HTMLFormElement.prototype.submit.call(form)" in script
    assert "requestSubmit()" not in script
    assert "readyToSubmit" not in script


def test_admin_export_page_only_shows_company_export_controls():
    client = TestClient(create_app())
    client.post("/login", data={"username": "zhangyong", "password": "test-admin-password"}, follow_redirects=True)

    response = client.get("/admin/export")

    assert response.status_code == 200
    assert '<select name="company"' in response.text
    assert '<select name="template"' in response.text
    assert 'value="__all__"' in response.text
    assert "全部公司" in response.text
    assert "客户版" in response.text
    assert "内部版" in response.text
    assert 'name="ship_date"' not in response.text
    assert 'name="export_type"' not in response.text
    assert "某日期发货表" not in response.text


def test_admin_export_all_companies_downloads_total_workbook():
    client = TestClient(create_app())
    client.post("/login", data={"username": "zhangyong", "password": "test-admin-password"}, follow_redirects=True)

    response = client.post("/admin/export", data={"company": "__all__"})

    assert response.status_code == 200
    content_disposition = response.headers["content-disposition"]
    assert "__all__" not in content_disposition
    assert "ZY%E6%9C%8D%E8%A3%85%E5%AE%A2%E6%88%B7%E7%89%88%E5%8F%91%E8%B4%A7%E6%80%BB%E8%A1%A8" in content_disposition
    assert re.search(r"_20\d{6}_\d{6}", content_disposition)


def test_admin_export_writes_operation_log(db_session):
    from app.db import get_session
    from app.models import OperationLog, User

    admin = User(username="log_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))

    response = client.post("/admin/export", data={"company": "__all__", "template": "customer"})

    assert response.status_code == 200
    log = db_session.query(OperationLog).one()
    assert log.actor_id == admin.id
    assert log.action == "export_customer"
    assert log.target == "全部公司"
    app.dependency_overrides.clear()


def test_admin_operation_logs_page_renders(db_session):
    from app.db import get_session
    from app.models import OperationLog, User

    admin = User(username="logs_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.flush()
    db_session.add(OperationLog(actor_id=admin.id, action="export_customer", target="全部公司", detail="客户版导出"))
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))

    response = client.get("/admin/logs")

    assert response.status_code == 200
    assert "操作日志" in response.text
    assert "老板" in response.text
    assert "客户版导出" in response.text
    app.dependency_overrides.clear()


def test_admin_daily_stats_page_groups_approved_shipments(db_session):
    from app.db import get_session
    from app.models import ShipmentLine, ShipmentReport, User

    admin = User(username="stats_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.flush()
    approved = ShipmentReport(
        user_id=admin.id,
        ship_date="2026-07-18",
        company_name="福建",
        product_name="小偷",
        style_name="小偷女款",
        status="auto_approved",
        review_reason="",
    )
    rejected = ShipmentReport(
        user_id=admin.id,
        ship_date="2026-07-18",
        company_name="福建",
        product_name="小偷",
        style_name="小偷女款",
        status="rejected",
        review_reason="驳回",
    )
    db_session.add_all([approved, rejected])
    db_session.flush()
    db_session.add_all([
        ShipmentLine(report_id=approved.id, size="M", quantity=120),
        ShipmentLine(report_id=rejected.id, size="M", quantity=999),
    ])
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))

    response = client.get("/admin/daily-stats?ship_date=2026-07-18")

    assert response.status_code == 200
    assert "每日发货统计" in response.text
    assert "福建" in response.text
    assert "小偷女款" in response.text
    assert ">M<" in response.text
    assert ">120<" in response.text
    assert ">999<" not in response.text
    app.dependency_overrides.clear()


def test_worker_can_view_daily_stats_page(db_session):
    from app.db import get_session
    from app.models import ShipmentLine, ShipmentReport, User

    worker = User(username="worker_daily_stats", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.flush()
    report = ShipmentReport(
        user_id=worker.id,
        ship_date="2026-07-18",
        company_name="福建",
        product_name="小偷",
        style_name="小偷女款",
        status="approved_after_edit",
        review_reason="",
    )
    db_session.add(report)
    db_session.flush()
    db_session.add(ShipmentLine(report_id=report.id, size="M", quantity=120))
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    home = client.get("/mobile")
    assert "/mobile/daily-stats" in home.text

    response = client.get("/mobile/daily-stats?ship_date=2026-07-18")

    assert response.status_code == 200
    assert "每日发货统计" in response.text
    assert "福建" in response.text
    assert "小偷女款" in response.text
    assert "M <b>120</b>" in response.text
    app.dependency_overrides.clear()


def test_admin_aliases_page_can_create_alias(db_session):
    from app.db import get_session
    from app.models import ProductAlias, User

    admin = User(username="alias_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))

    page = client.get("/admin/aliases")
    assert page.status_code == 200
    assert "款式统一" in page.text

    response = client.post(
        "/admin/aliases/new",
        data={
            "company_name": "源兴发",
            "alias_product": "僵尸拉拉队红色",
            "alias_style": "僵尸拉拉队红色",
            "canonical_product": "僵尸啦啦队红色",
            "canonical_style": "僵尸啦啦队红色",
            "note": "错别字统一",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    alias = db_session.query(ProductAlias).one()
    assert alias.alias_product == "僵尸拉拉队红色"
    assert alias.canonical_product == "僵尸啦啦队红色"
    app.dependency_overrides.clear()


def test_admin_waybill_import_page_renders_for_admin():
    client = TestClient(create_app())
    client.post("/login", data={"username": "zhangyong", "password": "test-admin-password"}, follow_redirects=True)

    response = client.get("/admin/waybills")

    assert response.status_code == 200
    assert "快递面单导入" in response.text
    assert "批量导入文件夹" in response.text
    assert "手动上传面单" in response.text
    assert 'name="waybill_date"' in response.text


def test_admin_waybill_page_can_edit_existing_waybill_date(db_session, tmp_path):
    from app.db import get_session
    from app.models import User, WaybillPhoto

    admin = User(username="admin_waybill", display_name="老板", password_hash="x", role="admin", is_active=True)
    photo_path = tmp_path / "old.png"
    photo_path.write_bytes(b"photo")
    db_session.add(admin)
    db_session.flush()
    db_session.add(
        WaybillPhoto(
            company_name="张鹏",
            stored_path=str(photo_path),
            original_name="old.png",
            source_path=str(photo_path),
            waybill_date="2026-07-13",
            uploaded_by=admin.id,
        )
    )
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))

    page = client.get("/admin/waybills")

    assert page.status_code == 200
    assert "已上传面单明细" in page.text
    assert 'value="2026-07-13"' in page.text
    assert "2026-07-13 面单" in page.text
    app.dependency_overrides.clear()


def test_admin_waybill_date_update_route_changes_existing_photo(db_session, tmp_path):
    from app.db import get_session
    from app.models import User, WaybillPhoto

    admin = User(username="admin_waybill_update", display_name="老板", password_hash="x", role="admin", is_active=True)
    photo_path = tmp_path / "old.png"
    photo_path.write_bytes(b"photo")
    db_session.add(admin)
    db_session.flush()
    photo = WaybillPhoto(
        company_name="张鹏",
        stored_path=str(photo_path),
        original_name="old.png",
        source_path=str(photo_path),
        waybill_date="2026-07-13",
        uploaded_by=admin.id,
    )
    db_session.add(photo)
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))

    response = client.post(f"/admin/waybills/{photo.id}/date", data={"waybill_date": "2026-07-18"}, follow_redirects=False)

    assert response.status_code == 303
    db_session.refresh(photo)
    assert photo.waybill_date == "2026-07-18"
    app.dependency_overrides.clear()


def test_admin_users_page_can_edit_account_fields():
    client = TestClient(create_app())
    client.post("/login", data={"username": "zhangyong", "password": "test-admin-password"}, follow_redirects=True)

    response = client.get("/admin/users")

    assert response.status_code == 200
    assert "保存资料" in response.text
    assert 'name="display_name"' in response.text
    assert 'name="role"' in response.text
    assert 'name="is_active"' in response.text


def test_admin_shipments_page_shows_internal_photo_links(db_session, tmp_path):
    from app.models import ShipmentLine, ShipmentPhoto, ShipmentReport, User
    from app.db import get_session

    admin = User(username="admin_test", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    photo = tmp_path / "package.png"
    photo.write_bytes(b"photo")
    report = ShipmentReport(
        user_id=admin.id,
        ship_date="2026-07-17",
        company_name="源兴发",
        product_name="小红帽",
        style_name="小红帽男",
        status="pending_review",
        review_reason="等待老板审核",
    )
    db_session.add(report)
    db_session.flush()
    db_session.add(ShipmentLine(report_id=report.id, size="M", quantity=10))
    db_session.add(ShipmentPhoto(report_id=report.id, file_path=str(photo), original_name="package.png"))
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))

    page = client.get("/admin/shipments")

    assert page.status_code == 200
    assert "/photos/shipment/" in page.text
    assert 'src="/photos/shipment/' in page.text
    assert "package.png" not in page.text
    app.dependency_overrides.clear()


def test_mobile_my_reports_shows_size_details_and_photo_thumbnails(db_session, tmp_path):
    from app.models import ShipmentLine, ShipmentPhoto, ShipmentReport, User
    from app.db import get_session

    worker = User(username="worker_photo", display_name="小杰", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    photo = tmp_path / "package.png"
    photo.write_bytes(b"photo")
    report = ShipmentReport(
        user_id=worker.id,
        ship_date="2026-07-17",
        company_name="源兴发",
        product_name="小红帽",
        style_name="小红帽男",
        status="pending_review",
        review_reason="等待老板审核",
    )
    db_session.add(report)
    db_session.flush()
    db_session.add_all([
        ShipmentLine(report_id=report.id, size="S", quantity=50),
        ShipmentLine(report_id=report.id, size="M", quantity=80),
        ShipmentPhoto(report_id=report.id, file_path=str(photo), original_name="package.png"),
    ])
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    page = client.get("/mobile/my-reports")

    assert page.status_code == 200
    assert "S <b>50</b>" in page.text
    assert "M <b>80</b>" in page.text
    assert 'src="/photos/shipment/' in page.text
    assert "package.png" not in page.text
    app.dependency_overrides.clear()


def test_worker_can_append_photos_to_own_submitted_report(db_session, tmp_path, monkeypatch):
    from app.db import get_session
    from app.models import ShipmentLine, ShipmentPhoto, ShipmentReport, User
    from app.services import photos as photo_service

    monkeypatch.setattr(photo_service, "UPLOAD_DIR", tmp_path)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    worker = User(username="worker_append_photo", display_name="小杰", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.flush()
    report = ShipmentReport(
        user_id=worker.id,
        ship_date="2026-07-17",
        company_name="源兴发",
        product_name="小红帽",
        style_name="小红帽男",
        status="auto_approved",
        review_reason="",
        note="原备注",
    )
    db_session.add(report)
    db_session.flush()
    db_session.add(ShipmentLine(report_id=report.id, size="S", quantity=50))
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    response = client.post(
        f"/mobile/my-reports/{report.id}/update",
        data={
            "line_ids": [str(report.lines[0].id)],
            "sizes": ["S"],
            "quantities": ["50"],
            "note": "原备注",
        },
        files={"photos": ("package.png", PNG_BYTES, "image/png")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.refresh(report)
    assert report.status == "pending_review"
    assert report.review_reason == "员工提交更新，等待老板审核"
    photos = db_session.query(ShipmentPhoto).filter_by(report_id=report.id).all()
    assert len(photos) == 1
    assert Path(photos[0].file_path).read_bytes() == PNG_BYTES
    app.dependency_overrides.clear()


def test_worker_update_report_keeps_existing_photos_and_sets_pending_review(db_session, tmp_path):
    from app.db import get_session
    from app.models import ShipmentLine, ShipmentPhoto, ShipmentReport, User

    worker = User(username="worker_update_report", display_name="小杰", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.flush()
    old_photo = tmp_path / "old.png"
    old_photo.write_bytes(b"old-photo")
    report = ShipmentReport(
        user_id=worker.id,
        ship_date="2026-07-17",
        company_name="源兴发",
        product_name="小红帽",
        style_name="小红帽男",
        status="approved_after_edit",
        review_reason="已通过",
        note="原备注",
    )
    db_session.add(report)
    db_session.flush()
    line = ShipmentLine(report_id=report.id, size="M", quantity=80)
    db_session.add(line)
    db_session.add(ShipmentPhoto(report_id=report.id, file_path=str(old_photo), original_name="old.png"))
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    response = client.post(
        f"/mobile/my-reports/{report.id}/update",
        data={
            "line_ids": [str(line.id)],
            "sizes": ["M"],
            "quantities": ["120"],
            "note": "改后备注",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.refresh(report)
    db_session.refresh(line)
    assert report.status == "pending_review"
    assert report.note == "改后备注"
    assert line.quantity == 120
    assert db_session.query(ShipmentPhoto).filter_by(report_id=report.id).count() == 1
    assert old_photo.exists()
    app.dependency_overrides.clear()


def test_worker_update_my_report_backfills_order_line_id_for_new_size(db_session):
    from app.db import get_session
    from app.models import ShipmentLine, ShipmentReport, User
    from app.services.orders import create_order_line

    worker = User(username="worker_backfill_route", display_name="小杰", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.flush()
    order = create_order_line(db_session, "源兴发", "小红帽", "小红帽男", "M", 200)
    report = ShipmentReport(
        user_id=worker.id,
        ship_date="2026-07-17",
        company_name="源兴发",
        product_name="小红帽",
        style_name="小红帽男",
        status="auto_approved",
        review_reason="",
        note="原备注",
    )
    db_session.add(report)
    db_session.flush()
    existing = ShipmentLine(report_id=report.id, size="S", quantity=50)
    db_session.add(existing)
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    response = client.post(
        f"/mobile/my-reports/{report.id}/update",
        data={
            "line_ids": [str(existing.id), ""],
            "sizes": ["S", "M"],
            "quantities": ["50", "30"],
            "note": "补一个新尺码",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.refresh(report)
    new_line = next(line for line in report.lines if line.size == "M")
    assert new_line.order_line_id == order.id
    app.dependency_overrides.clear()


def test_worker_update_my_report_writes_structured_audit_log(db_session, tmp_path, monkeypatch):
    import json

    from app.db import get_session
    from app.models import AuditLog, ShipmentLine, ShipmentReport, User
    from app.services import photos as photo_service

    monkeypatch.setattr(photo_service, "UPLOAD_DIR", tmp_path)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    worker = User(username="worker_audit", display_name="小杰", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.flush()
    report = ShipmentReport(
        user_id=worker.id,
        ship_date="2026-07-17",
        company_name="源兴发",
        product_name="小红帽",
        style_name="小红帽男",
        status="auto_approved",
        review_reason="",
        note="原备注",
    )
    db_session.add(report)
    db_session.flush()
    line = ShipmentLine(report_id=report.id, size="S", quantity=50)
    db_session.add(line)
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    response = client.post(
        f"/mobile/my-reports/{report.id}/update",
        data={
            "line_ids": [str(line.id)],
            "sizes": ["S"],
            "quantities": ["80"],
            "note": "改后备注",
        },
        files={"photos": ("package.png", PNG_BYTES, "image/png")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    audit = db_session.query(AuditLog).filter_by(report_id=report.id).one()
    assert audit.action == "worker_update"
    assert audit.admin_id == worker.id
    before = json.loads(audit.before_text)
    after = json.loads(audit.after_text)
    assert before[0]["size"] == "S"
    assert before[0]["quantity"] == 50
    assert after[0]["size"] == "S"
    assert after[0]["quantity"] == 80
    assert "补录1张照片" in audit.note
    app.dependency_overrides.clear()


def test_worker_cannot_update_another_workers_report(db_session):
    from app.db import get_session
    from app.models import ShipmentLine, ShipmentReport, User

    owner = User(username="worker_owner", display_name="小杰", password_hash="x", role="worker", is_active=True)
    other = User(username="worker_other", display_name="小陈", password_hash="x", role="worker", is_active=True)
    db_session.add_all([owner, other])
    db_session.flush()
    report = ShipmentReport(
        user_id=owner.id,
        ship_date="2026-07-17",
        company_name="源兴发",
        product_name="小红帽",
        style_name="小红帽男",
        status="auto_approved",
        review_reason="",
        note="原备注",
    )
    db_session.add(report)
    db_session.flush()
    line = ShipmentLine(report_id=report.id, size="S", quantity=50)
    db_session.add(line)
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(other.id))

    response = client.post(
        f"/mobile/my-reports/{report.id}/update",
        data={
            "line_ids": [str(line.id)],
            "sizes": ["S"],
            "quantities": ["999"],
            "note": "不该保存",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.refresh(report)
    db_session.refresh(line)
    assert response.headers["location"] == "/mobile/my-reports"
    assert report.note == "原备注"
    assert line.quantity == 50
    app.dependency_overrides.clear()


def test_worker_update_report_rejects_bad_photo_without_saving_changes(db_session, tmp_path, monkeypatch):
    from app.db import get_session
    from app.models import ShipmentLine, ShipmentPhoto, ShipmentReport, User
    from app.services import photos as photo_service

    monkeypatch.setattr(photo_service, "UPLOAD_DIR", tmp_path)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    worker = User(username="worker_bad_photo", display_name="小杰", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.flush()
    report = ShipmentReport(
        user_id=worker.id,
        ship_date="2026-07-17",
        company_name="源兴发",
        product_name="小红帽",
        style_name="小红帽男",
        status="auto_approved",
        review_reason="",
        note="原备注",
    )
    db_session.add(report)
    db_session.flush()
    line = ShipmentLine(report_id=report.id, size="S", quantity=50)
    db_session.add(line)
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    response = client.post(
        f"/mobile/my-reports/{report.id}/update",
        data={
            "line_ids": [str(line.id)],
            "sizes": ["S"],
            "quantities": ["99"],
            "note": "不该保存",
        },
        files={"photos": ("bad.png", b"bad", "image/png")},
    )

    db_session.refresh(report)
    db_session.refresh(line)
    assert response.status_code == 200
    assert "照片文件内容不正确" in response.text
    assert report.status == "auto_approved"
    assert report.note == "原备注"
    assert line.quantity == 50
    assert db_session.query(ShipmentPhoto).count() == 0
    app.dependency_overrides.clear()


def test_mobile_my_reports_shows_update_form_without_photo_delete(db_session):
    from app.db import get_session
    from app.models import ShipmentLine, ShipmentReport, User

    worker = User(username="worker_update_form", display_name="小杰", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.flush()
    report = ShipmentReport(
        user_id=worker.id,
        ship_date="2026-07-17",
        company_name="源兴发",
        product_name="小红帽",
        style_name="小红帽男",
        status="auto_approved",
        review_reason="",
        note="原备注",
    )
    db_session.add(report)
    db_session.flush()
    db_session.add(ShipmentLine(report_id=report.id, size="S", quantity=50))
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    page = client.get("/mobile/my-reports")

    assert page.status_code == 200
    assert f'action="/mobile/my-reports/{report.id}/update"' in page.text
    assert 'name="line_ids"' in page.text
    assert 'name="quantities"' in page.text
    assert 'name="photos"' in page.text
    assert 'name="waybill_no"' not in page.text
    assert "提交更新给老板审核" in page.text
    assert "删除照片" not in page.text
    assert "remove_photo" not in page.text
    app.dependency_overrides.clear()


def test_mobile_report_draft_shows_photo_thumbnails_without_names(db_session, tmp_path):
    from datetime import date
    from app.db import get_session
    from app.models import PackingDraft, PackingDraftPhoto, User

    worker = User(username="draft_thumb_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    photo = tmp_path / "draft-package.png"
    photo.write_bytes(b"photo")
    draft = PackingDraft(
        user_id=worker.id,
        pack_date=date.today().isoformat(),
        company_name="源兴发",
        product_name="小红帽",
        style_name="小红帽男",
    )
    db_session.add(draft)
    db_session.flush()
    db_session.add(PackingDraftPhoto(draft_id=draft.id, file_path=str(photo), original_name="draft-package.png"))
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    page = client.get("/mobile/report")

    assert page.status_code == 200
    assert 'src="/photos/draft/' in page.text
    assert "draft-package.png" not in page.text
    app.dependency_overrides.clear()


def test_mobile_home_shows_previous_day_shipments_not_replenishment(db_session):
    from datetime import date, timedelta
    from app.db import get_session
    from app.models import ShipmentLine, ShipmentReport, User

    worker = User(username="worker_home", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    report = ShipmentReport(
        user_id=worker.id,
        ship_date=(date.today() - timedelta(days=1)).isoformat(),
        company_name="福建",
        product_name="小偷",
        style_name="小偷女款",
        status="auto_approved",
        review_reason="",
    )
    db_session.add(report)
    db_session.flush()
    db_session.add(ShipmentLine(report_id=report.id, size="M", quantity=120))
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    page = client.get("/mobile")

    assert page.status_code == 200
    assert "前一日发货" in page.text
    assert "福建" in page.text
    assert "小偷女款" in page.text
    assert "M <b>120</b>" in page.text
    assert "优先补货参考" not in page.text
    app.dependency_overrides.clear()
