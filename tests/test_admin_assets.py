from pathlib import Path


WEB_SRC = Path("web/src")


def test_formal_order_routes_and_navigation_are_registered():
    router = (WEB_SRC / "router.js").read_text(encoding="utf-8")
    app = (WEB_SRC / "App.vue").read_text(encoding="utf-8")

    for route in ["/companies", "/spus", "/sales-orders", "/sales-orders/:id"]:
        assert route in router
    assert 'to="/companies"' in app
    assert 'to="/spus"' in app
    assert 'to="/sales-orders"' in app


def test_new_order_page_uses_formal_order_fields():
    page = (WEB_SRC / "views" / "NewOrder.vue").read_text(encoding="utf-8")

    for field in [
        "company_id",
        "spu_id",
        "color_name",
        "color_code",
        "customer_order_no",
        "customer_sku",
    ]:
        assert field in page
    assert "createSalesOrder" in page
    assert "系统订单号" in page


def test_company_and_spu_management_pages_exist():
    companies = (WEB_SRC / "views" / "Companies.vue").read_text(encoding="utf-8")
    spus = (WEB_SRC / "views" / "Spus.vue").read_text(encoding="utf-8")

    assert "公司代码" in companies
    assert "next_order_sequence" in companies
    assert "SPU 编码" in spus
    assert "product_name" in spus
    assert "style_name" in spus
