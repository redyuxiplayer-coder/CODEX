from app.models import Company, OrderLine, SalesOrder, ShipmentLine, ShipmentReport, User
from scripts.migrate_legacy_sales_orders import apply_decisions, preview_legacy_orders


def _line(db_session, company, product, style, size, order_date="", batch=""):
    row = OrderLine(
        company_id=company.id,
        product_name=product,
        style_name=style,
        size=size,
        quantity=100,
        order_date=order_date,
        batch=batch,
        is_active=True,
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_preview_groups_sizes_without_guessing_color_and_flags_missing_date(db_session):
    company = Company(name="源兴发", code="")
    db_session.add(company)
    db_session.flush()
    first = _line(db_session, company, "啦啦队", "僵尸啦啦队", "S", "", "首单")
    second = _line(db_session, company, "啦啦队", "僵尸啦啦队", "M", "", "首单")
    db_session.commit()

    preview = preview_legacy_orders(db_session)

    assert len(preview["groups"]) == 1
    group = preview["groups"][0]
    assert group["order_line_ids"] == [first.id, second.id]
    assert group["candidate_color_name"] == ""
    assert group["candidate_color_code"] == ""
    assert "missing_order_date" in group["reasons"]
    assert "missing_company_code" in group["reasons"]
    assert group in preview["needs_review"]
    assert "system_order_no" not in group


def test_preview_flags_shipment_that_crosses_candidate_orders(db_session):
    company = Company(name="源兴发", code="YXF")
    worker = User(username="migration_worker", display_name="仓库", password_hash="x", role="worker")
    db_session.add_all([company, worker])
    db_session.flush()
    first = _line(db_session, company, "啦啦队", "僵尸啦啦队", "S", "2026-07-01")
    second = _line(db_session, company, "啦啦队", "僵尸啦啦队", "M", "2026-07-02")
    report = ShipmentReport(
        user_id=worker.id,
        ship_date="2026-07-10",
        company_name=company.name,
        product_name="啦啦队",
        style_name="僵尸啦啦队",
        status="auto_approved",
    )
    db_session.add(report)
    db_session.flush()
    db_session.add_all([
        ShipmentLine(report_id=report.id, order_line_id=first.id, size="S", quantity=10),
        ShipmentLine(report_id=report.id, order_line_id=second.id, size="M", quantity=10),
    ])
    db_session.commit()

    preview = preview_legacy_orders(db_session)

    assert len(preview["needs_review"]) == 2
    assert all("cross_candidate_shipment" in group["reasons"] for group in preview["needs_review"])
    assert all(group["linked_shipment_report_ids"] == [report.id] for group in preview["groups"])


def test_apply_numbers_each_company_independently_in_stable_date_order(db_session):
    first_company = Company(name="源兴发", code="")
    second_company = Company(name="张鹏", code="")
    db_session.add_all([first_company, second_company])
    db_session.flush()
    later = _line(db_session, first_company, "啦啦队", "僵尸啦啦队", "M", "2026-07-02")
    earlier = _line(db_session, first_company, "啦啦队", "僵尸啦啦队", "S", "2026-07-01")
    other = _line(db_session, second_company, "啦啦队", "僵尸啦啦队", "S", "2026-07-01")
    db_session.commit()

    decisions = [
        {"order_line_ids": [later.id], "company_code": "YXF", "spu_code": "JS", "color_name": "", "color_code": "", "order_date": "2026-07-02", "customer_order_no": ""},
        {"order_line_ids": [other.id], "company_code": "ZP", "spu_code": "JS", "color_name": "", "color_code": "", "order_date": "2026-07-01", "customer_order_no": ""},
        {"order_line_ids": [earlier.id], "company_code": "YXF", "spu_code": "JS", "color_name": "", "color_code": "", "order_date": "2026-07-01", "customer_order_no": ""},
    ]

    audit = apply_decisions(db_session, decisions)

    numbers = {order.company.name: [] for order in db_session.query(SalesOrder).all()}
    for order in db_session.query(SalesOrder).order_by(SalesOrder.company_id, SalesOrder.company_sequence):
        numbers[order.company.name].append(order.system_order_no)
    assert numbers["源兴发"] == ["YXF-00001-JS", "YXF-00002-JS"]
    assert numbers["张鹏"] == ["ZP-00001-JS"]
    assert audit["order_line_count"] == 3
    assert audit["grouped_order_line_count"] == 3
    assert audit["unconfirmed_group_count"] == 0
