from app.models import User
from app.services.aliases import create_product_alias, list_product_aliases
from app.services.orders import create_order_line, get_order_balances
from app.services.shipments import submit_shipment_report


def test_product_aliases_can_be_created_and_listed(db_session):
    alias = create_product_alias(
        db_session,
        company_name="源兴发",
        alias_product="僵尸拉拉队红色",
        alias_style="僵尸拉拉队红色",
        canonical_product="僵尸啦啦队红色",
        canonical_style="僵尸啦啦队红色",
        note="统一错别字",
    )

    aliases = list_product_aliases(db_session)

    assert alias.id is not None
    assert aliases[0].alias_product == "僵尸拉拉队红色"
    assert aliases[0].canonical_product == "僵尸啦啦队红色"
    assert aliases[0].note == "统一错别字"


def test_order_balances_merge_alias_product_and_style(db_session):
    create_product_alias(
        db_session,
        company_name="源兴发",
        alias_product="僵尸拉拉队红色",
        alias_style="僵尸拉拉队红色",
        canonical_product="僵尸啦啦队红色",
        canonical_style="僵尸啦啦队红色",
    )
    create_order_line(db_session, "源兴发", "僵尸啦啦队红色", "僵尸啦啦队红色", "M", 100)
    create_order_line(db_session, "源兴发", "僵尸拉拉队红色", "僵尸拉拉队红色", "M", 50)

    balances = get_order_balances(db_session, "源兴发")

    assert len(balances) == 1
    assert balances[0]["product"] == "僵尸啦啦队红色"
    assert balances[0]["style"] == "僵尸啦啦队红色"
    assert balances[0]["ordered"] == 150


def test_alias_shipment_matches_canonical_order(db_session):
    worker = User(username="worker_alias", display_name="仓库", password_hash="x", role="admin", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_product_alias(
        db_session,
        company_name="源兴发",
        alias_product="僵尸拉拉队红色",
        alias_style="僵尸拉拉队红色",
        canonical_product="僵尸啦啦队红色",
        canonical_style="僵尸啦啦队红色",
    )
    create_order_line(db_session, "源兴发", "僵尸啦啦队红色", "僵尸啦啦队红色", "M", 100)

    report = submit_shipment_report(
        db_session,
        worker.id,
        "2026-07-18",
        "源兴发",
        "僵尸拉拉队红色",
        "僵尸拉拉队红色",
        [{"size": "M", "quantity": 40}],
        [],
        "",
    )

    assert report.status == "auto_approved"
    balance = get_order_balances(db_session, "源兴发")[0]
    assert balance["shipped"] == 40
    assert balance["remaining"] == 60
