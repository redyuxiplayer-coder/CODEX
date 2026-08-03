from app.models import ShipmentReport, User
from app.services.orders import create_order_line, get_order_balances
from app.services.shipments import delete_own_pending_report, submit_shipment_report, update_own_pending_report


def test_worker_can_update_own_pending_report(db_session):
    worker = User(username="worker_a", display_name="仓库A", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_order_line(db_session, "张鹏", "万圣节-僵尸棒球", "万圣节-僵尸棒球", "L", 400)
    report = submit_shipment_report(
        db_session,
        worker.id,
        "2026-07-17",
        "张鹏",
        "万圣节-僵尸棒球",
        "万圣节-僵尸棒球",
        [{"size": "L", "quantity": 100}],
        [],
        "原备注",
    )

    updated = update_own_pending_report(db_session, report.id, worker.id, [{"size": "L", "quantity": 120}], "改后备注")

    assert updated.status == "pending_review"
    assert updated.note == "改后备注"
    assert [(line.size, line.quantity) for line in updated.lines] == [("L", 120)]
    balance = get_order_balances(db_session, "张鹏")[0]
    assert balance["shipped"] == 0
    assert balance["remaining"] == 400


def test_worker_cannot_update_other_workers_report(db_session):
    owner = User(username="owner", display_name="员工1", password_hash="x", role="worker", is_active=True)
    other = User(username="other", display_name="员工2", password_hash="x", role="worker", is_active=True)
    db_session.add_all([owner, other])
    db_session.commit()
    create_order_line(db_session, "张鹏", "万圣节-僵尸棒球", "万圣节-僵尸棒球", "L", 400)
    report = submit_shipment_report(db_session, owner.id, "2026-07-17", "张鹏", "万圣节-僵尸棒球", "万圣节-僵尸棒球", [{"size": "L", "quantity": 100}], [], "")

    try:
        update_own_pending_report(db_session, report.id, other.id, [{"size": "L", "quantity": 120}], "")
    except ValueError as exc:
        assert "不能修改" in str(exc)
    else:
        raise AssertionError("other worker should not edit report")


def test_worker_can_delete_own_pending_report(db_session):
    worker = User(username="worker_a", display_name="仓库A", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    report = submit_shipment_report(db_session, worker.id, "2026-07-17", "张鹏", "万圣节-僵尸棒球", "万圣节-僵尸棒球", [{"size": "L", "quantity": 100}], [], "")

    delete_own_pending_report(db_session, report.id, worker.id)

    assert db_session.get(ShipmentReport, report.id) is None
