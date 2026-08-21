import pytest

from app.models import PackingDraft, ShipmentReport, User, WaybillRecord
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import create_app
from app.services.logistics import create_waybill_record
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
        waybill_no="YT-EDIT-001",
        shipping_method="courier",
        package_count=1,
        weight_kg=2.5,
    )
    updated = update_packing_draft(
        db_session,
        draft.id,
        worker.id,
        [{"size": "L", "quantity": 120}],
        "改成120",
        waybill_no="YT-EDIT-001",
        shipping_method="courier",
        package_count=1,
        weight_kg=2.5,
    )

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
    draft = create_packing_draft(
        db_session,
        worker.id,
        "2026-07-17",
        "张鹏",
        "万圣节-僵尸棒球",
        "万圣节-僵尸棒球",
        [{"size": "L", "quantity": 100}],
        "",
        waybill_no="YT-SUBMIT-001",
        shipping_method="courier",
        package_count=2,
        weight_kg=5.5,
    )

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
    draft = create_packing_draft(
        db_session,
        worker.id,
        "2026-07-17",
        "张鹏",
        "万圣节-僵尸棒球",
        "万圣节-僵尸棒球",
        [{"size": "L", "quantity": 100}],
        "",
        waybill_no="YT-DELETE-001",
        shipping_method="courier",
        package_count=1,
        weight_kg=3.2,
    )

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
        "YT-PHOTO-001",
        None,
        "courier",
        1,
        1.2,
    )

    report = submit_packing_draft(db_session, draft.id, worker.id)

    assert [p.file_path for p in report.photos] == [str(photo)]
    assert all(p.draft_id == draft.id for p in report.photos)


def test_delete_submitted_packing_draft_is_rejected(db_session):
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
        "",
        waybill_no="YT-SUBMITTED-001",
        shipping_method="courier",
        package_count=1,
        weight_kg=2.8,
    )
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

    first = create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "M", "quantity": 10}],
        "",
        waybill_no="YT-PKG-001",
        shipping_method="courier",
        package_count=1,
        weight_kg=2.0,
    )
    second = create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "L", "quantity": 5}],
        "",
        waybill_no="YT-PKG-002",
        shipping_method="courier",
        package_count=1,
        weight_kg=2.1,
    )

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
        waybill_no="YT-PRINT-001",
        shipping_method="courier",
        package_count=2,
        weight_kg=4.3,
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


def test_create_draft_rejects_future_date_without_persisting(db_session):
    worker = User(username="worker_future", display_name="仓库A", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()

    with pytest.raises(ValueError, match="发货日期不能晚于今天"):
        create_packing_draft(
            db_session,
            worker.id,
            "2099-01-01",
            "源兴发",
            "小红帽",
            "小红帽男",
            [{"size": "M", "quantity": 10}],
            "",
            waybill_no="YT-FUTURE-001",
            shipping_method="courier",
            package_count=1,
            weight_kg=1.5,
        )

    assert db_session.query(PackingDraft).count() == 0


def test_submit_two_drafts_reuses_one_waybill(db_session):
    worker = User(username="worker_waybill", display_name="仓库A", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_order_line(db_session, "源兴发", "小红帽", "小红帽男", "M", 100)
    create_order_line(db_session, "源兴发", "小红帽", "小红帽男", "L", 100)

    first = create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "M", "quantity": 10}],
        "",
        waybill_no="YT-REUSE-001",
        shipping_method="courier",
        package_count=2,
        weight_kg=10,
    )
    second = create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "L", "quantity": 8}],
        "",
        waybill_no="YT-REUSE-001",
        shipping_method="courier",
        package_count=2,
        weight_kg=10,
    )

    first_report = submit_packing_draft(db_session, first.id, worker.id)
    second_report = submit_packing_draft(db_session, second.id, worker.id)

    assert first_report.waybill_id == second_report.waybill_id
    assert db_session.query(WaybillRecord).count() == 1


def test_waybill_conflict_does_not_create_partial_report(db_session):
    admin = User(username="admin_conflict", display_name="老板", password_hash="x", role="admin", is_active=True)
    worker = User(username="worker_conflict", display_name="仓库A", password_hash="x", role="worker", is_active=True)
    db_session.add_all([admin, worker])
    db_session.commit()
    create_order_line(db_session, "源兴发", "小红帽", "小红帽男", "M", 100)
    draft = create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "M", "quantity": 12}],
        "",
        waybill_no="YT-CONFLICT-001",
        shipping_method="courier",
        package_count=3,
        weight_kg=10,
    )
    create_waybill_record(
        db_session,
        admin.id,
        "源兴发",
        "2026-08-04",
        "YT-CONFLICT-001",
        courier="快递",
        weight_kg=10,
        package_count=2,
    )

    with pytest.raises(ValueError, match="包裹件数"):
        submit_packing_draft(db_session, draft.id, worker.id)

    db_session.refresh(draft)
    assert draft.submitted_report_id is None
    assert db_session.query(ShipmentReport).count() == 0


def test_get_or_create_matching_waybill_recovers_from_integrity_error(db_session, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import sessionmaker

    admin = User(username="admin_race", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    from app.services import packing_drafts as packing_drafts_service
    from app.services.packing_drafts import get_or_create_matching_waybill

    triggered = {"done": False}

    def racing_create_waybill_record(*args, **kwargs):
        if not triggered["done"]:
            triggered["done"] = True
            Session = sessionmaker(bind=db_session.bind)
            race_session = Session()
            try:
                create_waybill_record(
                    race_session,
                    admin.id,
                    "源兴发",
                    "2026-08-04",
                    "YT-RACE-001",
                    courier="快递",
                    weight_kg=8,
                    package_count=2,
                )
            finally:
                race_session.close()
            raise IntegrityError("insert into waybill_records", {}, Exception("duplicate key"))
        return create_waybill_record(*args, **kwargs)

    monkeypatch.setattr(packing_drafts_service, "create_waybill_record", racing_create_waybill_record)

    record = get_or_create_matching_waybill(
        db_session,
        user_id=admin.id,
        company_name="源兴发",
        ship_date="2026-08-04",
        waybill_no="YT-RACE-001",
        shipping_method="courier",
        package_count=2,
        weight_kg=8,
    )

    assert record.waybill_no == "YT-RACE-001"
    assert db_session.query(WaybillRecord).count() == 1
