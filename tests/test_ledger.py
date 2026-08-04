from app.models import (
    OrderAdjustment,
    OrderLedgerEntry,
    OrderLineClose,
    ReturnRework,
    User,
)
from app.services.ledger import order_line_totals, recompute_order_ledger
from app.services.orders import create_order_line, get_order_balances
from app.services.shipments import submit_shipment_report


def _admin(db_session) -> User:
    admin = User(username="ledger_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    return admin


def _ship(db_session, order, quantity: int, user: User):
    return submit_shipment_report(
        db_session,
        user.id,
        "2026-08-04",
        order.company.name,
        order.product_name,
        order.style_name,
        [{"size": order.size, "quantity": quantity, "order_line_id": order.id}],
        [],
        "",
    )


def test_balance_formula_with_return_adjust_close(db_session):
    order = create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)
    db_session.add(ReturnRework(order_line_id=order.id, quantity=5, reason_type="退回返工", reason="线头", status="pending_rework"))
    db_session.add(OrderAdjustment(order_line_id=order.id, quantity=1, reason="报废"))
    db_session.add(OrderLineClose(order_line_id=order.id, quantity=2, reason="客户不要"))
    db_session.commit()
    recompute_order_ledger(db_session, order.id)

    row = get_order_balances(db_session)[0]
    assert row["returned"] == 5
    assert row["adjusted"] == 1
    assert row["closed"] == 2
    assert row["remaining"] == 100 - 0 + 5 - 1 - 2


def test_recompute_ledger_rebuilds_from_sources(db_session):
    admin = _admin(db_session)
    order = create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)
    report = _ship(db_session, order, 100, admin)
    assert report.status == "auto_approved"
    db_session.add(ReturnRework(order_line_id=order.id, quantity=5, reason_type="退回返工", reason="返工", status="pending_rework"))
    db_session.commit()
    recompute_order_ledger(db_session, order.id)

    entries = db_session.query(OrderLedgerEntry).filter_by(order_line_id=order.id).order_by(OrderLedgerEntry.id).all()
    assert [(e.movement_type, e.quantity) for e in entries] == [("shipped", 100), ("returned", 5)]

    db_session.query(ReturnRework).delete()
    db_session.commit()
    recompute_order_ledger(db_session, order.id)
    entries = db_session.query(OrderLedgerEntry).filter_by(order_line_id=order.id).all()
    assert [(e.movement_type, e.quantity) for e in entries] == [("shipped", 100)]


def test_scrapped_return_counts_as_returned_plus_adjusted(db_session):
    admin = _admin(db_session)
    order = create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)
    _ship(db_session, order, 100, admin)
    db_session.add(ReturnRework(order_line_id=order.id, quantity=5, reason_type="质量问题", reason="报废", status="scrapped"))
    db_session.commit()
    recompute_order_ledger(db_session, order.id)

    row = get_order_balances(db_session)[0]
    assert row["returned"] == 5
    assert row["adjusted"] == 5
    assert row["remaining"] == 100 - 100 + 5 - 5
    totals = order_line_totals(db_session, order.id)
    assert totals["returned"] == 5
    assert totals["adjusted"] == 5
    assert totals["remaining"] == 0
