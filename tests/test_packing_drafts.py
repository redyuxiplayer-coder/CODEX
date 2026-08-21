from datetime import datetime

import pytest
from sqlalchemy import event, text

from app.models import PackingDraft, ShipmentReport, User, WaybillRecord
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import create_app
from app.services.logistics import create_waybill_record
from app.services.orders import create_order_line, get_order_balances
from app.services.packing_drafts import (
    _parse_weight_kg,
    create_packing_draft,
    delete_packing_draft,
    submit_packing_draft,
    update_packing_draft,
)


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
    db_session.add(
        WaybillRecord(
            company_name="源兴发",
            ship_date="2026-08-04",
            waybill_no="YT-CONFLICT-001",
            courier="快递",
            weight_kg=10,
            package_count=2,
            created_by=admin.id,
        )
    )
    db_session.commit()

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


def test_create_packing_draft_rejects_empty_cleaned_lines(db_session):
    worker = User(username="worker_empty_create", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()

    with pytest.raises(ValueError, match="至少填写一条"):
        create_packing_draft(
            db_session,
            worker.id,
            "2026-08-04",
            "源兴发",
            "小红帽",
            "小红帽男",
            [{"size": "L", "quantity": "0"}],
            waybill_no="YT-EMPTY-CREATE",
            shipping_method="courier",
            package_count=1,
            weight_kg=2,
        )

    assert db_session.query(PackingDraft).count() == 0


def test_update_packing_draft_rejects_empty_cleaned_lines_without_erasing_existing(db_session):
    worker = User(username="worker_empty_update", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    draft = create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "L", "quantity": 12}],
        waybill_no="YT-EMPTY-UPDATE",
        shipping_method="courier",
        package_count=1,
        weight_kg=2,
    )

    with pytest.raises(ValueError, match="至少填写一条"):
        update_packing_draft(
            db_session,
            draft.id,
            worker.id,
            [{"size": "", "quantity": 10}],
            waybill_no="YT-EMPTY-UPDATE",
            shipping_method="courier",
            package_count=1,
            weight_kg=2,
        )

    db_session.refresh(draft)
    assert [(line.size, line.quantity) for line in draft.lines] == [("L", 12)]


def test_submit_packing_draft_uses_a_for_update_query(db_session):
    worker = User(username="worker_submit_lock", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    draft = create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "L", "quantity": 12}],
        waybill_no="YT-SUBMIT-LOCK",
        shipping_method="courier",
        package_count=1,
        weight_kg=2,
    )
    saw_for_update = []

    def capture_for_update(execute_state):
        if execute_state.is_select and getattr(execute_state.statement, "_for_update_arg", None) is not None:
            saw_for_update.append(True)

    event.listen(db_session, "do_orm_execute", capture_for_update)
    try:
        submit_packing_draft(db_session, draft.id, worker.id)
    finally:
        event.remove(db_session, "do_orm_execute", capture_for_update)

    assert saw_for_update == [True]


def test_submit_packing_draft_refreshes_submitted_state_before_creating_report(db_session):
    worker = User(username="worker_submit_refresh", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    draft = create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "L", "quantity": 12}],
        waybill_no="YT-SUBMIT-REFRESH",
        shipping_method="courier",
        package_count=1,
        weight_kg=2,
    )
    db_session.execute(
        text("UPDATE packing_drafts SET submitted_report_id = 999 WHERE id = :draft_id"),
        {"draft_id": draft.id},
    )

    with pytest.raises(ValueError, match="已提交"):
        submit_packing_draft(db_session, draft.id, worker.id)

    assert db_session.query(ShipmentReport).count() == 0


def test_update_and_delete_packing_drafts_use_for_update_queries(db_session):
    worker = User(username="worker_mutation_lock", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    update_draft = create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "L", "quantity": 12}],
        waybill_no="YT-UPDATE-LOCK",
        shipping_method="courier",
        package_count=1,
        weight_kg=2,
    )
    delete_draft = create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽女",
        [{"size": "M", "quantity": 8}],
        waybill_no="YT-DELETE-LOCK",
        shipping_method="courier",
        package_count=1,
        weight_kg=2,
    )
    saw_for_update = []

    def capture_for_update(execute_state):
        if execute_state.is_select and getattr(execute_state.statement, "_for_update_arg", None) is not None:
            saw_for_update.append(True)

    event.listen(db_session, "do_orm_execute", capture_for_update)
    try:
        update_packing_draft(
            db_session,
            update_draft.id,
            worker.id,
            [{"size": "L", "quantity": 13}],
            waybill_no="YT-UPDATE-LOCK",
            shipping_method="courier",
            package_count=1,
            weight_kg=2,
        )
        delete_packing_draft(db_session, delete_draft.id, worker.id)
    finally:
        event.remove(db_session, "do_orm_execute", capture_for_update)

    assert saw_for_update == [True, True]


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_draft_mutations_refresh_submitted_state_before_writing(db_session, operation):
    worker = User(username=f"worker_mutation_refresh_{operation}", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    draft = create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "L", "quantity": 12}],
        waybill_no=f"YT-MUTATION-REFRESH-{operation}",
        shipping_method="courier",
        package_count=1,
        weight_kg=2,
    )
    db_session.execute(
        text("UPDATE packing_drafts SET submitted_report_id = 999 WHERE id = :draft_id"),
        {"draft_id": draft.id},
    )

    with pytest.raises(ValueError, match="已提交"):
        if operation == "update":
            update_packing_draft(
                db_session,
                draft.id,
                worker.id,
                [{"size": "L", "quantity": 13}],
                waybill_no=f"YT-MUTATION-REFRESH-{operation}",
                shipping_method="courier",
                package_count=1,
                weight_kg=2,
            )
        else:
            delete_packing_draft(db_session, draft.id, worker.id)

    assert db_session.get(PackingDraft, draft.id) is not None


def test_create_packing_draft_rejects_compact_iso_date(db_session):
    worker = User(username="worker_compact_date", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()

    with pytest.raises(ValueError, match="发货日期格式不正确"):
        create_packing_draft(
            db_session,
            worker.id,
            "20260804",
            "源兴发",
            "小红帽",
            "小红帽男",
            [{"size": "L", "quantity": 12}],
            waybill_no="YT-COMPACT-DATE",
            shipping_method="courier",
            package_count=1,
            weight_kg=2,
        )

    assert db_session.query(PackingDraft).count() == 0


@pytest.mark.parametrize("weight", ["NaN", "Infinity", "-Infinity"])
def test_weight_parser_rejects_non_finite_values(weight):
    with pytest.raises(ValueError, match="请填写正确的总重量"):
        _parse_weight_kg(weight)


def test_update_packing_draft_refreshes_updated_at(db_session):
    worker = User(username="worker_updated_at", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    draft = create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "L", "quantity": 12}],
        waybill_no="YT-UPDATED-AT",
        shipping_method="courier",
        package_count=1,
        weight_kg=2,
    )
    original_updated_at = datetime(2000, 1, 1)
    draft.updated_at = original_updated_at
    db_session.commit()

    updated = update_packing_draft(
        db_session,
        draft.id,
        worker.id,
        [{"size": "L", "quantity": 13}],
        waybill_no="YT-UPDATED-AT",
        shipping_method="courier",
        package_count=1,
        weight_kg=2,
    )

    assert updated.updated_at > original_updated_at


def test_existing_huolala_draft_copies_authoritative_count_and_weight(db_session):
    source_worker = User(username="huolala_source", display_name="同事", password_hash="x", role="worker", is_active=True)
    worker = User(username="huolala_existing", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add_all([source_worker, worker])
    db_session.commit()
    create_packing_draft(
        db_session,
        source_worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "L", "quantity": 12}],
        waybill_no="HL-AUTH-DRAFT",
        shipping_method="huolala",
        package_count=3,
        weight_kg=12.5,
    )

    reused = create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽女",
        [{"size": "M", "quantity": 8}],
        waybill_no="HL-AUTH-DRAFT",
        shipping_method="huolala",
        trip_mode="existing",
        package_count=999,
        weight_kg=999,
    )

    assert reused.package_count == 3
    assert reused.weight_kg == 12.5


def test_existing_huolala_waybill_record_copies_authoritative_count_and_weight(db_session):
    worker = User(username="huolala_record", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_waybill_record(
        db_session,
        worker.id,
        "源兴发",
        "2026-08-04",
        "HL-AUTH-RECORD",
        courier="货拉拉",
        package_count=5,
        weight_kg=18.5,
    )

    reused = create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "L", "quantity": 12}],
        waybill_no="HL-AUTH-RECORD",
        shipping_method="huolala",
        trip_mode="existing",
        package_count=1,
        weight_kg=1,
    )

    assert reused.package_count == 5
    assert reused.weight_kg == 18.5


def test_update_huolala_existing_copies_authoritative_logistics(db_session):
    source_worker = User(username="huolala_update_source", display_name="同事", password_hash="x", role="worker", is_active=True)
    worker = User(username="huolala_update", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add_all([source_worker, worker])
    db_session.commit()
    create_packing_draft(
        db_session,
        source_worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "L", "quantity": 12}],
        waybill_no="HL-UPDATE-SOURCE",
        shipping_method="huolala",
        package_count=4,
        weight_kg=15.5,
    )
    target = create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽女",
        [{"size": "M", "quantity": 8}],
        waybill_no="YT-BEFORE-HUOLALA",
        shipping_method="courier",
        package_count=1,
        weight_kg=2,
    )

    updated = update_packing_draft(
        db_session,
        target.id,
        worker.id,
        [{"size": "M", "quantity": 9}],
        waybill_no="HL-UPDATE-SOURCE",
        shipping_method="huolala",
        trip_mode="existing",
        package_count=999,
        weight_kg=999,
    )

    assert updated.shipping_method == "huolala"
    assert updated.package_count == 4
    assert updated.weight_kg == 15.5


def test_update_new_huolala_generates_identifier_when_blank(db_session):
    worker = User(username="huolala_update_new", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    draft = create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "L", "quantity": 12}],
        waybill_no="YT-BEFORE-NEW",
        shipping_method="courier",
        package_count=1,
        weight_kg=2,
    )

    updated = update_packing_draft(
        db_session,
        draft.id,
        worker.id,
        [{"size": "L", "quantity": 13}],
        waybill_no="",
        shipping_method="huolala",
        trip_mode="new",
        package_count=2,
        weight_kg=6.5,
    )

    assert updated.waybill_no == f"货拉拉-20260804-{draft.id:03d}"
    assert updated.package_count == 2
    assert updated.weight_kg == 6.5


def test_existing_huolala_rejects_cross_company_and_cross_date_sources(db_session):
    worker = User(username="huolala_scope", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "L", "quantity": 12}],
        waybill_no="HL-SCOPED",
        shipping_method="huolala",
        package_count=3,
        weight_kg=12.5,
    )

    for company_name, pack_date in [("别家公司", "2026-08-04"), ("源兴发", "2026-08-05")]:
        with pytest.raises(ValueError, match="同公司同日期"):
            create_packing_draft(
                db_session,
                worker.id,
                pack_date,
                company_name,
                "小红帽",
                "小红帽女",
                [{"size": "M", "quantity": 8}],
                waybill_no="HL-SCOPED",
                shipping_method="huolala",
                trip_mode="existing",
                package_count=3,
                weight_kg=12.5,
            )


def test_courier_draft_identifier_cannot_be_reused_as_huolala(db_session):
    worker = User(username="channel_courier_first", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "L", "quantity": 12}],
        waybill_no="CHANNEL-DRAFT-1",
        shipping_method="courier",
        package_count=1,
        weight_kg=2,
    )

    with pytest.raises(ValueError, match="不能跨发货方式复用"):
        create_packing_draft(
            db_session,
            worker.id,
            "2026-08-04",
            "源兴发",
            "小红帽",
            "小红帽女",
            [{"size": "M", "quantity": 8}],
            waybill_no="CHANNEL-DRAFT-1",
            shipping_method="huolala",
            package_count=1,
            weight_kg=2,
        )


def test_huolala_record_identifier_cannot_be_reused_as_courier(db_session):
    worker = User(username="channel_huolala_first", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_waybill_record(
        db_session,
        worker.id,
        "源兴发",
        "2026-08-04",
        "CHANNEL-RECORD-1",
        courier="货拉拉",
        package_count=1,
        weight_kg=2,
    )

    with pytest.raises(ValueError, match="不能跨发货方式复用"):
        create_packing_draft(
            db_session,
            worker.id,
            "2026-08-04",
            "源兴发",
            "小红帽",
            "小红帽男",
            [{"size": "L", "quantity": 12}],
            waybill_no="CHANNEL-RECORD-1",
            shipping_method="courier",
            package_count=1,
            weight_kg=2,
        )


def test_postgres_logistics_identifier_lock_is_transaction_scoped_and_namespaced():
    from types import SimpleNamespace

    from app.services.logistics import lock_logistics_identifier

    executions = []

    class FakeSession:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement, params):
            executions.append((str(statement), params))

    lock_logistics_identifier(FakeSession(), "  SHARED-ID  ")

    assert len(executions) == 1
    statement, params = executions[0]
    assert "pg_advisory_xact_lock" in statement
    assert "hashtext" in statement
    assert params == {"identifier": "SHARED-ID"}


def test_draft_validation_locks_identifier_before_channel_lookup(db_session, monkeypatch):
    from app.services import packing_drafts as packing_drafts_service

    worker = User(username="identifier_lock_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    events = []
    original_validate_channel = packing_drafts_service._validate_identifier_channel

    monkeypatch.setattr(
        packing_drafts_service,
        "lock_logistics_identifier",
        lambda _session, waybill_no: events.append(("lock", waybill_no)),
        raising=False,
    )

    def capture_channel_validation(*args, **kwargs):
        events.append(("validate", kwargs["waybill_no"]))
        return original_validate_channel(*args, **kwargs)

    monkeypatch.setattr(packing_drafts_service, "_validate_identifier_channel", capture_channel_validation)

    create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "L", "quantity": 12}],
        waybill_no="SERIALIZED-ID",
        shipping_method="courier",
        package_count=1,
        weight_kg=2,
    )

    assert events[:2] == [("lock", "SERIALIZED-ID"), ("validate", "SERIALIZED-ID")]


def test_waybill_writer_locks_identifier_and_rejects_cross_channel_draft(db_session, monkeypatch):
    from app.services import logistics as logistics_service

    worker = User(username="identifier_writer_worker", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "L", "quantity": 12}],
        waybill_no="WRITER-CHANNEL-ID",
        shipping_method="huolala",
        package_count=1,
        weight_kg=2,
    )
    locked = []
    monkeypatch.setattr(
        logistics_service,
        "lock_logistics_identifier",
        lambda _session, waybill_no: locked.append(waybill_no),
        raising=False,
    )

    with pytest.raises(ValueError, match="不能跨发货方式复用"):
        logistics_service.create_waybill_record(
            db_session,
            worker.id,
            "源兴发",
            "2026-08-04",
            "WRITER-CHANNEL-ID",
            courier="快递",
            package_count=1,
            weight_kg=2,
        )

    assert locked == ["WRITER-CHANNEL-ID"]
    assert db_session.query(WaybillRecord).count() == 0


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"company_name": "别家公司"}, "公司必须一致"),
        ({"ship_date": "2026-08-05"}, "发货日期必须一致"),
        ({"package_count": 9}, "包裹件数必须一致"),
        ({"weight_kg": 9.5}, "总重量必须一致"),
        ({"weight_kg": float("nan")}, "正确的总重量"),
        ({"weight_kg": float("inf")}, "正确的总重量"),
        ({"weight_kg": float("-inf")}, "正确的总重量"),
    ],
)
def test_waybill_create_rejects_same_channel_draft_metadata_mismatch(db_session, override, message):
    worker = User(username=f"writer_metadata_{message}", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "L", "quantity": 12}],
        waybill_no="WRITER-METADATA-ID",
        shipping_method="courier",
        package_count=2,
        weight_kg=4.5,
    )
    values = {
        "company_name": "源兴发",
        "ship_date": "2026-08-04",
        "package_count": 2,
        "weight_kg": 4.5,
    }
    values.update(override)

    with pytest.raises(ValueError, match=message):
        create_waybill_record(
            db_session,
            worker.id,
            values["company_name"],
            values["ship_date"],
            "WRITER-METADATA-ID",
            courier="快递",
            package_count=values["package_count"],
            weight_kg=values["weight_kg"],
        )

    assert db_session.query(WaybillRecord).count() == 0


def test_waybill_update_rejects_retargeting_to_incompatible_same_channel_draft(db_session):
    from app.services.logistics import update_waybill_record

    worker = User(username="writer_update_metadata", display_name="仓库", password_hash="x", role="worker", is_active=True)
    db_session.add(worker)
    db_session.commit()
    create_packing_draft(
        db_session,
        worker.id,
        "2026-08-04",
        "源兴发",
        "小红帽",
        "小红帽男",
        [{"size": "L", "quantity": 12}],
        waybill_no="DRAFT-METADATA-ID",
        shipping_method="courier",
        package_count=2,
        weight_kg=4.5,
    )
    record = create_waybill_record(
        db_session,
        worker.id,
        "别家公司",
        "2026-08-05",
        "ADMIN-OTHER-ID",
        courier="快递",
        package_count=8,
        weight_kg=12,
    )

    with pytest.raises(ValueError, match="公司必须一致"):
        update_waybill_record(db_session, record.id, waybill_no="DRAFT-METADATA-ID")

    db_session.refresh(record)
    assert record.waybill_no == "ADMIN-OTHER-ID"
