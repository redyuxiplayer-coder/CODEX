from app.models import Company, OrderLine, SalesOrder, ShipmentLine, ShipmentReport, User
from scripts.migrate_legacy_sales_orders import apply_decisions, database_url_for_cli, preview_legacy_orders


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


def test_database_url_for_cli_reads_production_url_from_named_environment(monkeypatch):
    monkeypatch.setenv("SUPABASE_DATABASE_URL", "postgresql+psycopg://example.invalid/db")

    assert database_url_for_cli(None, "SUPABASE_DATABASE_URL") == "postgresql+psycopg://example.invalid/db"


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


def test_apply_allows_legacy_aliases_to_share_one_canonical_spu(db_session):
    first_company = Company(name="源兴发", code="")
    second_company = Company(name="广东茉莉", code="")
    db_session.add_all([first_company, second_company])
    db_session.flush()
    first = _line(db_session, first_company, "僵尸棒球", "僵尸棒球男款", "S", "2026-06-10")
    second = _line(db_session, second_company, "僵尸棒球", "棒球男", "M", "2026-05-22")
    db_session.commit()

    decisions = [
        {
            "order_line_ids": [first.id],
            "company_code": "YXF",
            "spu_code": "JSBQ",
            "product_name": "僵尸棒球",
            "style_name": "男款",
            "color_name": "",
            "color_code": "",
            "order_date": "2026-06-10",
        },
        {
            "order_line_ids": [second.id],
            "company_code": "ML",
            "spu_code": "JSBQ",
            "product_name": "僵尸棒球",
            "style_name": "男款",
            "color_name": "",
            "color_code": "",
            "order_date": "2026-05-22",
        },
    ]

    apply_decisions(db_session, decisions)

    orders = db_session.query(SalesOrder).order_by(SalesOrder.id).all()
    assert {order.spu.code for order in orders} == {"JSBQ"}
    assert {(order.product_name, order.style_name) for order in orders} == {("僵尸棒球", "男款")}


def test_apply_writes_reviewed_customer_sku_only_to_named_order_line(db_session):
    company = Company(name="源兴发", code="")
    db_session.add(company)
    db_session.flush()
    small = _line(db_session, company, "小红帽", "小红帽男款", "S", "2026-06-10")
    extra_large = _line(db_session, company, "小红帽", "小红帽男款", "XL", "2026-06-10")
    db_session.commit()

    apply_decisions(
        db_session,
        [
            {
                "order_line_ids": [small.id, extra_large.id],
                "company_code": "YXF",
                "spu_code": "XHHM",
                "product_name": "小红帽",
                "style_name": "男款",
                "color_name": "",
                "color_code": "",
                "order_date": "2026-06-10",
                "customer_skus": {str(extra_large.id): "FZWS1209004-04-Red and white stripes-XL"},
            }
        ],
    )

    db_session.refresh(small)
    db_session.refresh(extra_large)
    assert small.customer_sku == ""
    assert extra_large.customer_sku == "FZWS1209004-04-Red and white stripes-XL"


def test_apply_binds_historical_unbound_shipment_line_when_match_is_unique(db_session):
    company = Company(name="源兴发", code="")
    worker = User(username="legacy_worker", display_name="仓库", password_hash="x", role="worker")
    db_session.add_all([company, worker])
    db_session.flush()
    order_line = _line(db_session, company, "小偷", "小偷女款", "S", "2026-06-10")
    report = ShipmentReport(
        user_id=worker.id,
        ship_date="2026-06-20",
        company_name=company.name,
        product_name="小偷",
        style_name="小偷女款",
        status="auto_approved",
    )
    db_session.add(report)
    db_session.flush()
    shipment_line = ShipmentLine(report_id=report.id, order_line_id=None, size="S", quantity=10)
    db_session.add(shipment_line)
    db_session.commit()

    audit = apply_decisions(
        db_session,
        [
            {
                "order_line_ids": [order_line.id],
                "company_code": "YXF",
                "spu_code": "XTF",
                "product_name": "小偷",
                "style_name": "女款",
                "color_name": "",
                "color_code": "",
                "order_date": "2026-06-10",
            }
        ],
    )

    db_session.refresh(report)
    db_session.refresh(shipment_line)
    assert shipment_line.order_line_id == order_line.id
    assert report.order_id == order_line.order_id
    assert audit["uniquely_matched_shipment_line_count"] == 1


def test_apply_corrects_reviewed_legacy_size_value(db_session):
    company = Company(name="张鹏", code="")
    db_session.add(company)
    db_session.flush()
    order_line = _line(db_session, company, "围裙", "围裙", "4件套", "2026-04-29")
    db_session.commit()

    apply_decisions(
        db_session,
        [
            {
                "order_line_ids": [order_line.id],
                "company_code": "ZP",
                "spu_code": "WQ4",
                "product_name": "围裙",
                "style_name": "四件套",
                "color_name": "",
                "color_code": "",
                "order_date": "2026-04-29",
                "size_overrides": {str(order_line.id): "均码"},
            }
        ],
    )

    db_session.refresh(order_line)
    assert order_line.size == "均码"
