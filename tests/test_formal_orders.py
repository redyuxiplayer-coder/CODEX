from app.models import Company, OrderLine, SalesOrder, Spu


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
