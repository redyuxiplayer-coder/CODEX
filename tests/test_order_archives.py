import importlib

import pytest

from app.models import Company, OperationLog, SalesOrder, ShipmentLine, ShipmentReport, Spu, User
from app.services.sales_orders import create_sales_order


def archive_service():
    return importlib.import_module("app.services.order_archives")


def make_order(db_session, quantities=None):
    company = Company(name="源兴发", code="YXF", next_order_sequence=1)
    spu = Spu(code="REF", product_name="裁判", style_name="圆领裁判")
    admin = User(
        username="archive_admin",
        display_name="老板",
        password_hash="x",
        role="admin",
        is_active=True,
    )
    db_session.add_all([company, spu, admin])
    db_session.commit()
    order = create_sales_order(
        db_session,
        company.id,
        spu.id,
        "",
        "",
        "2026-08-10",
        [
            {"size": size, "quantity": quantity, "customer_sku": ""}
            for size, quantity in (quantities or {"S": 100, "M": 50}).items()
        ],
    )
    return order, admin


def ship_order(db_session, order, admin, quantities, ship_date="2026-08-10"):
    report = ShipmentReport(
        user_id=admin.id,
        order_id=order.id,
        ship_date=ship_date,
        company_name=order.company.name,
        product_name=order.product_name,
        style_name=order.style_name,
        status="approved_after_edit",
        review_reason="",
        note="",
    )
    db_session.add(report)
    db_session.flush()
    lines_by_size = {line.size: line for line in order.lines}
    for size, quantity in quantities.items():
        db_session.add(
            ShipmentLine(
                report_id=report.id,
                order_line_id=lines_by_size[size].id,
                size=size,
                quantity=quantity,
            )
        )
    db_session.commit()
    return report


def test_archive_rejects_order_with_remaining_size(db_session):
    order, admin = make_order(db_session)
    ship_order(db_session, order, admin, {"S": 100})

    with pytest.raises(ValueError, match="M 码还需 50 件"):
        archive_service().archive_sales_order(db_session, order.id, admin.id)


def test_archive_accepts_exactly_shipped_order(db_session):
    order, admin = make_order(db_session)
    ship_order(db_session, order, admin, {"S": 100, "M": 50})

    archive = archive_service().archive_sales_order(db_session, order.id, admin.id)

    assert archive.restored_at is None
    assert order.id in archive_service().archived_order_ids(db_session)


def test_archive_accepts_over_shipped_order(db_session):
    order, admin = make_order(db_session)
    ship_order(db_session, order, admin, {"S": 102, "M": 50})

    state = archive_service().archive_state(db_session, order)
    archive = archive_service().archive_sales_order(db_session, order.id, admin.id)

    assert state["can_archive"] is True
    assert state["blocking_sizes"] == []
    assert archive.order_id == order.id


def test_restore_closes_current_record_and_preserves_history(db_session):
    order, admin = make_order(db_session)
    ship_order(db_session, order, admin, {"S": 100, "M": 50})
    service = archive_service()
    first = service.archive_sales_order(db_session, order.id, admin.id)

    restored = service.restore_sales_order(db_session, order.id, admin.id)
    second = service.archive_sales_order(db_session, order.id, admin.id)
    state = service.archive_state(db_session, order)

    assert restored.id == first.id
    assert restored.restored_at is not None
    assert restored.restored_by == admin.id
    assert second.id != first.id
    assert len(state["history"]) == 2


def test_duplicate_archive_and_restore_without_archive_are_rejected(db_session):
    order, admin = make_order(db_session)
    ship_order(db_session, order, admin, {"S": 100, "M": 50})
    service = archive_service()
    service.archive_sales_order(db_session, order.id, admin.id)

    with pytest.raises(ValueError, match="订单已经归档"):
        service.archive_sales_order(db_session, order.id, admin.id)
    service.restore_sales_order(db_session, order.id, admin.id)
    with pytest.raises(ValueError, match="订单尚未归档"):
        service.restore_sales_order(db_session, order.id, admin.id)


def test_archive_rejects_order_without_active_lines(db_session):
    order, admin = make_order(db_session)
    for line in order.lines:
        line.is_active = False
    db_session.commit()

    with pytest.raises(ValueError, match="订单没有有效明细"):
        archive_service().archive_sales_order(db_session, order.id, admin.id)


def test_archive_and_restore_operations_are_logged(db_session):
    order, admin = make_order(db_session)
    ship_order(db_session, order, admin, {"S": 100, "M": 50})
    service = archive_service()

    service.archive_sales_order(db_session, order.id, admin.id)
    service.restore_sales_order(db_session, order.id, admin.id)

    logs = db_session.query(OperationLog).order_by(OperationLog.id).all()
    assert [(log.action, log.target, log.actor_id) for log in logs] == [
        ("archive_sales_order", order.system_order_no, admin.id),
        ("restore_sales_order", order.system_order_no, admin.id),
    ]


def test_archive_missing_order_is_rejected(db_session):
    _, admin = make_order(db_session)

    with pytest.raises(ValueError, match="订单不存在"):
        archive_service().archive_sales_order(db_session, 999999, admin.id)


def test_inactive_company_does_not_make_unshipped_order_archivable(db_session):
    order, admin = make_order(db_session)
    order.company.is_active = False
    db_session.commit()

    state = archive_service().archive_state(db_session, order)

    assert state["can_archive"] is False
    assert state["blocking_sizes"] == [
        {"size": "S", "remaining": 100},
        {"size": "M", "remaining": 50},
    ]
    with pytest.raises(ValueError, match="还需"):
        archive_service().archive_sales_order(db_session, order.id, admin.id)


def test_pending_report_cannot_be_approved_or_edited_after_archive(db_session):
    from app.services.shipments import approve_report, edit_and_approve_report, reject_report, update_own_pending_report

    order, admin = make_order(db_session)
    approved = ship_order(db_session, order, admin, {"S": 100, "M": 50})
    pending = ShipmentReport(
        user_id=admin.id,
        order_id=order.id,
        ship_date="2026-08-10",
        company_name=order.company.name,
        product_name=order.product_name,
        style_name=order.style_name,
        status="pending_review",
        review_reason="等待审核",
        note="",
    )
    db_session.add(pending)
    db_session.flush()
    db_session.add(
        ShipmentLine(
            report_id=pending.id,
            order_line_id=order.lines[0].id,
            size="S",
            quantity=1,
        )
    )
    db_session.commit()
    archive_service().archive_sales_order(db_session, order.id, admin.id)

    with pytest.raises(ValueError, match="订单已归档，请先恢复"):
        approve_report(db_session, pending.id, admin.id)
    with pytest.raises(ValueError, match="订单已归档，请先恢复"):
        edit_and_approve_report(
            db_session,
            pending.id,
            admin.id,
            [{"size": "S", "quantity": 2, "order_line_id": order.lines[0].id}],
        )
    with pytest.raises(ValueError, match="订单已归档，请先恢复"):
        update_own_pending_report(
            db_session,
            pending.id,
            admin.id,
            [{"size": "S", "quantity": 2, "order_line_id": order.lines[0].id}],
        )
    with pytest.raises(ValueError, match="订单已归档，请先恢复"):
        reject_report(db_session, approved.id, admin.id)
    db_session.refresh(pending)
    assert pending.status == "pending_review"
    assert pending.lines[0].quantity == 1
    db_session.refresh(approved)
    assert approved.status == "approved_after_edit"
