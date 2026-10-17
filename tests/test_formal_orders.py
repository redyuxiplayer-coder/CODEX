from decimal import Decimal

import pytest

from app.models import Company, OrderLine, SalesOrder, Spu
from app.services.sales_orders import create_sales_order, order_price_summary, parse_unit_price
from app.services.spus import create_spu


def test_formal_order_schema_has_required_links(db_session):
    company = Company(name="源兴发", code="YXF", next_order_sequence=1)
    spu = Spu(code="JS", product_name="啦啦队", style_name="僵尸啦啦队")
    db_session.add_all([company, spu])
    db_session.flush()
    order = SalesOrder(
        system_order_no="YXF-00001-JS-RED",
        customer_order_no="",
        company_id=company.id,
        company_sequence=1,
        spu_id=spu.id,
        product_name="啦啦队",
        style_name="僵尸啦啦队",
        color_name="红色",
        color_code="RED",
        order_date="2026-08-09",
    )
    db_session.add(order)
    db_session.flush()
    line = OrderLine(
        order_id=order.id,
        company_id=company.id,
        product_name=order.product_name,
        style_name=order.style_name,
        size="S",
        quantity=100,
        customer_sku="FZB1209001-01-red-S",
    )
    db_session.add(line)
    db_session.commit()

    assert line.order.system_order_no == "YXF-00001-JS-RED"
    assert line.customer_sku == "FZB1209001-01-red-S"


def test_company_sequences_are_independent_and_color_is_optional(db_session):
    yxf = Company(name="源兴发", code="YXF", next_order_sequence=1)
    zp = Company(name="张鹏", code="ZP", next_order_sequence=1)
    spu = Spu(code="JS", product_name="啦啦队", style_name="僵尸啦啦队")
    db_session.add_all([yxf, zp, spu])
    db_session.commit()

    first = create_sales_order(
        db_session,
        yxf.id,
        spu.id,
        "红色",
        "RED",
        "2026-08-09",
        [{"size": "S", "quantity": 100, "customer_sku": "SKU-S"}],
    )
    second = create_sales_order(
        db_session,
        yxf.id,
        spu.id,
        "",
        "",
        "2026-08-10",
        [{"size": "M", "quantity": 50, "customer_sku": ""}],
    )
    other = create_sales_order(
        db_session,
        zp.id,
        spu.id,
        "红色",
        "RED",
        "2026-08-09",
        [{"size": "S", "quantity": 30, "customer_sku": ""}],
    )

    assert first.system_order_no == "YXF-00001-JS-RED"
    assert second.system_order_no == "YXF-00002-JS"
    assert other.system_order_no == "ZP-00001-JS-RED"
    assert first.lines[0].customer_sku == "SKU-S"
    assert second.lines[0].customer_sku == ""


def test_spu_code_can_be_manual_or_automatic(db_session):
    manual = create_spu(db_session, "js", "啦啦队", "僵尸啦啦队")
    automatic = create_spu(db_session, "", "裁判服", "圆领裁判")

    assert manual.code == "JS"
    assert automatic.code == f"SPU{automatic.id:05d}"


def test_order_rejects_mixed_color_fields_and_duplicate_sizes(db_session):
    company = Company(name="源兴发", code="YXF", next_order_sequence=1)
    spu = Spu(code="JS", product_name="啦啦队", style_name="僵尸啦啦队")
    db_session.add_all([company, spu])
    db_session.commit()

    import pytest

    with pytest.raises(ValueError, match="颜色名称和颜色编码必须同时填写"):
        create_sales_order(
            db_session,
            company.id,
            spu.id,
            "红色",
            "",
            "2026-08-09",
            [{"size": "S", "quantity": 100}],
        )

    with pytest.raises(ValueError, match="同一订单不能有重复尺码"):
        create_sales_order(
            db_session,
            company.id,
            spu.id,
            "红色",
            "RED",
            "2026-08-09",
            [{"size": "S", "quantity": 100}, {"size": "S", "quantity": 50}],
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("  ", None),
        (0, Decimal("0.000")),
        ("12.30", Decimal("12.300")),
        (12.3, Decimal("12.300")),
        ("9999999999.99", Decimal("9999999999.990")),
    ],
)
def test_parse_unit_price_accepts_blank_and_valid_money(value, expected):
    assert parse_unit_price(value) == expected


@pytest.mark.parametrize(
    "value",
    ["-0.01", "12.3456", "1.0000", "not money", "NaN", "Infinity", "10000000000", True],
)
def test_parse_unit_price_rejects_invalid_money(value):
    with pytest.raises(ValueError, match="单价"):
        parse_unit_price(value)


def test_three_decimal_unit_price_is_preserved_in_size_and_order_amounts(db_session):
    company = Company(name="三位小数价格测试", code="MILLI", next_order_sequence=1)
    spu = Spu(code="SKU", product_name="产品", style_name="款式")
    db_session.add_all([company, spu])
    db_session.commit()

    order = create_sales_order(
        db_session,
        company.id,
        spu.id,
        "",
        "",
        "2026-10-17",
        [{"size": "S", "quantity": 3, "unit_price": "12.345"}],
    )

    assert order.lines[0].unit_price == Decimal("12.345")
    assert order_price_summary(order)["total_amount"] == Decimal("37.035")


def test_create_formal_order_preserves_filled_zero_and_missing_prices(db_session):
    company = Company(name="价格测试", code="PRICE", next_order_sequence=1)
    spu = Spu(code="SKU", product_name="产品", style_name="款式")
    db_session.add_all([company, spu])
    db_session.commit()

    order = create_sales_order(
        db_session,
        company.id,
        spu.id,
        "",
        "",
        "2026-09-24",
        [
            {"size": "S", "quantity": 100, "unit_price": "12.30"},
            {"size": "M", "quantity": 2, "unit_price": 0},
            {"size": "L", "quantity": 1},
        ],
    )

    assert [line.unit_price for line in order.lines] == [Decimal("12.300"), Decimal("0.000"), None]
    assert order_price_summary(order) == {
        "known_subtotal": Decimal("1230.000"),
        "missing_price_count": 1,
        "is_complete": False,
        "total_amount": None,
    }


def test_create_formal_order_rejects_invalid_price_before_writing(db_session):
    company = Company(name="价格测试", code="PRICE", next_order_sequence=1)
    spu = Spu(code="SKU", product_name="产品", style_name="款式")
    db_session.add_all([company, spu])
    db_session.commit()

    with pytest.raises(ValueError, match="单价"):
        create_sales_order(
            db_session,
            company.id,
            spu.id,
            "",
            "",
            "2026-09-24",
            [{"size": "S", "quantity": 1, "unit_price": "12.3456"}],
        )

    assert db_session.query(SalesOrder).count() == 0


def test_order_price_summary_keeps_cents_with_large_quantity(db_session):
    company = Company(name="精度测试", code="PREC", next_order_sequence=1)
    spu = Spu(code="SKU", product_name="产品", style_name="款式")
    db_session.add_all([company, spu])
    db_session.commit()

    order = create_sales_order(
        db_session,
        company.id,
        spu.id,
        "",
        "",
        "2026-09-24",
        [
            {"size": "S", "quantity": 99999999999999999, "unit_price": "9999999999.99"},
            {"size": "M", "quantity": 1, "unit_price": "0.02"},
        ],
    )

    assert order_price_summary(order) == {
        "known_subtotal": Decimal("999999999998999990000000000.03"),
        "missing_price_count": 0,
        "is_complete": True,
        "total_amount": Decimal("999999999998999990000000000.03"),
    }
