from app.models import OrderLedgerEntry, User
from app.services.adjustments import create_order_adjustment, create_order_line_close, list_adjustments, list_closes
from app.services.orders import create_order_line, get_order_balances


def test_create_adjustment_reduces_remaining_and_writes_ledger(db_session):
    admin = User(username="adj_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    order = create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)

    create_order_adjustment(db_session, order.id, admin.id, 1, reason="盘亏")

    row = get_order_balances(db_session)[0]
    assert row["adjusted"] == 1
    assert row["remaining"] == 99
    entry = db_session.query(OrderLedgerEntry).filter_by(order_line_id=order.id).one()
    assert entry.movement_type == "adjusted"
    assert entry.quantity == 1
    assert len(list_adjustments(db_session, order.id)) == 1


def test_create_close_reduces_remaining_and_writes_ledger(db_session):
    admin = User(username="close_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    order = create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "L", 100)

    create_order_line_close(db_session, order.id, admin.id, 2, reason="客户不要了")

    row = get_order_balances(db_session)[0]
    assert row["closed"] == 2
    assert row["remaining"] == 98
    entry = db_session.query(OrderLedgerEntry).filter_by(order_line_id=order.id).one()
    assert entry.movement_type == "closed"
    assert entry.quantity == 2
    assert len(list_closes(db_session, order.id)) == 1
