from app.models import OrderLedgerEntry, ReturnRework, User
from app.services.ledger import recompute_order_ledger
from app.services.orders import create_order_line, get_order_balances
from app.services.returns import create_return_rework, set_return_rework_status
from app.services.shipments import submit_shipment_report


def _admin(db_session) -> User:
    admin = User(username="returns_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    return admin


def _order_with_100_shipped(db_session):
    admin = _admin(db_session)
    order = create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)
    submit_shipment_report(
        db_session,
        admin.id,
        "2026-08-04",
        order.company.name,
        order.product_name,
        order.style_name,
        [{"size": order.size, "quantity": 100, "order_line_id": order.id}],
        [],
        "",
    )
    return order, admin


def test_create_return_rework_increases_remaining_and_writes_ledger(db_session):
    order, admin = _order_with_100_shipped(db_session)
    record = create_return_rework(
        db_session,
        order.id,
        admin.id,
        5,
        reason_type="退回返工",
        reason="线头未剪",
        status="pending_rework",
        photo_paths=["data/uploads/ret1.jpg"],
    )

    assert record.status == "pending_rework"
    assert [p.file_path for p in record.photos] == ["data/uploads/ret1.jpg"]
    row = get_order_balances(db_session)[0]
    assert row["returned"] == 5
    assert row["remaining"] == 5
    entries = db_session.query(OrderLedgerEntry).filter_by(order_line_id=order.id).order_by(OrderLedgerEntry.id).all()
    assert [(e.movement_type, e.quantity) for e in entries] == [("shipped", 100), ("returned", 5)]


def test_set_return_status_scrapped_offsets_balance_and_writes_adjustment(db_session):
    order, admin = _order_with_100_shipped(db_session)
    record = create_return_rework(db_session, order.id, admin.id, 5, reason_type="质量问题", reason="破损", status="pending_rework")

    set_return_rework_status(db_session, record.id, "scrapped")

    row = get_order_balances(db_session)[0]
    assert row["returned"] == 5
    assert row["adjusted"] == 5
    assert row["remaining"] == 0
    entries = db_session.query(OrderLedgerEntry).filter_by(order_line_id=order.id).order_by(OrderLedgerEntry.id).all()
    assert [(e.movement_type, e.quantity) for e in entries] == [("shipped", 100), ("returned", 5), ("adjusted", 5)]


def test_list_return_reworks_returns_ordered_records(db_session):
    order, admin = _order_with_100_shipped(db_session)
    create_return_rework(db_session, order.id, admin.id, 2, reason_type="退回返工", reason="a")
    create_return_rework(db_session, order.id, admin.id, 3, reason_type="退回返工", reason="b")
    from app.services.returns import list_return_reworks

    records = list_return_reworks(db_session, order.id)
    assert len(records) == 2
    assert records[0].reason == "b"
