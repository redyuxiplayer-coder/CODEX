from app.models import User
from app.services.orders import create_order_line, get_order_balances
from app.services.packing_drafts import create_packing_draft, delete_packing_draft, submit_packing_draft, update_packing_draft


def test_worker_can_edit_packing_draft_without_shipping_count(db_session):
    worker = User(username="worker_a", display_name="仓库A", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_order_line(db_session, "张鹏", "万圣节-僵尸棒球", "万圣节-僵尸棒球", "L", 400)

    draft = create_packing_draft(
        db_session,
        worker.id,
        "2026-07-17",
        "张鹏",
        "万圣节-僵尸棒球",
        "万圣节-僵尸棒球",
        [{"size": "L", "quantity": 100}],
        "先包100",
    )
    updated = update_packing_draft(db_session, draft.id, worker.id, [{"size": "L", "quantity": 120}], "改成120")

    assert updated.note == "改成120"
    assert [(line.size, line.quantity) for line in updated.lines] == [("L", 120)]
    balance = get_order_balances(db_session, "张鹏")[0]
    assert balance["shipped"] == 0
    assert balance["remaining"] == 400


def test_submit_packing_draft_creates_pending_report_and_removes_draft(db_session):
    worker = User(username="worker_a", display_name="仓库A", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_order_line(db_session, "张鹏", "万圣节-僵尸棒球", "万圣节-僵尸棒球", "L", 400)
    draft = create_packing_draft(db_session, worker.id, "2026-07-17", "张鹏", "万圣节-僵尸棒球", "万圣节-僵尸棒球", [{"size": "L", "quantity": 100}], "")

    report = submit_packing_draft(db_session, draft.id, worker.id)

    assert report.status == "pending_review"
    assert "等待老板审核" in report.review_reason
    assert db_session.get(type(draft), draft.id) is None


def test_worker_can_delete_own_packing_draft(db_session):
    worker = User(username="worker_a", display_name="仓库A", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    draft = create_packing_draft(db_session, worker.id, "2026-07-17", "张鹏", "万圣节-僵尸棒球", "万圣节-僵尸棒球", [{"size": "L", "quantity": 100}], "")

    delete_packing_draft(db_session, draft.id, worker.id)

    assert db_session.get(type(draft), draft.id) is None


def test_submit_packing_draft_keeps_internal_package_photos(db_session, tmp_path):
    worker = User(username="worker_a", display_name="仓库A", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    photo = tmp_path / "package.png"
    photo.write_bytes(b"photo")
    draft = create_packing_draft(
        db_session,
        worker.id,
        "2026-07-17",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "M", "quantity": 10}],
        "",
        [str(photo)],
    )

    report = submit_packing_draft(db_session, draft.id, worker.id)

    assert [p.file_path for p in report.photos] == [str(photo)]
