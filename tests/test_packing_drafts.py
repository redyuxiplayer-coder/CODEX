from app.models import PackingDraft, User
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import create_app
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


def test_submit_packing_draft_creates_pending_report_and_keeps_package(db_session):
    worker = User(username="worker_a", display_name="仓库A", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_order_line(db_session, "张鹏", "万圣节-僵尸棒球", "万圣节-僵尸棒球", "L", 400)
    draft = create_packing_draft(db_session, worker.id, "2026-07-17", "张鹏", "万圣节-僵尸棒球", "万圣节-僵尸棒球", [{"size": "L", "quantity": 100}], "")

    report = submit_packing_draft(db_session, draft.id, worker.id)

    assert report.status == "pending_review"
    assert "等待老板审核" in report.review_reason
    saved_draft = db_session.get(type(draft), draft.id)
    assert saved_draft is not None
    assert saved_draft.submitted_report_id == report.id


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
    assert all(p.draft_id == draft.id for p in report.photos)


def test_delete_submitted_packing_draft_is_rejected(db_session):
    worker = User(username="worker_a", display_name="仓库A", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_order_line(db_session, "张鹏", "万圣节-僵尸棒球", "万圣节-僵尸棒球", "L", 400)
    draft = create_packing_draft(db_session, worker.id, "2026-07-17", "张鹏", "万圣节-僵尸棒球", "万圣节-僵尸棒球", [{"size": "L", "quantity": 100}], "")
    submit_packing_draft(db_session, draft.id, worker.id)

    try:
        delete_packing_draft(db_session, draft.id, worker.id)
    except ValueError as exc:
        assert "已提交" in str(exc)
    else:
        raise AssertionError("submitted package draft should not be deletable")
    assert db_session.get(PackingDraft, draft.id) is not None


def test_create_packing_draft_auto_assigns_package_no(db_session):
    worker = User(username="worker_pkg", display_name="仓库A", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()

    first = create_packing_draft(db_session, worker.id, "2026-08-04", "源兴发", "小红帽", "小红帽男", [{"size": "M", "quantity": 10}], "")
    second = create_packing_draft(db_session, worker.id, "2026-08-04", "源兴发", "小红帽", "小红帽男", [{"size": "L", "quantity": 5}], "")

    assert first.package_no == "PKG-20260804-001"
    assert second.package_no == "PKG-20260804-002"


def test_packing_print_pages_render_for_admin_and_owner(db_session):
    admin = User(username="pkg_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    worker = User(username="pkg_worker", display_name="仓库A", password_hash="x", role="worker", is_active=True)
    db_session.add_all([admin, worker])
    db_session.commit()
    draft = create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "M", "quantity": 10}, {"size": "L", "quantity": 5}],
        "注意轻放",
    )
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)

    client.cookies.set("zy_user_id", str(admin.id))
    page = client.get(f"/admin/packing/{draft.id}/print")
    assert page.status_code == 200
    for text in ["装箱单", "PKG-20260804-001", "小红帽男", "M", "10", "注意轻放"]:
        assert text in page.text

    client.cookies.set("zy_user_id", str(worker.id))
    page = client.get(f"/mobile/packing/{draft.id}/print")
    assert page.status_code == 200
    assert "PKG-20260804-001" in page.text
