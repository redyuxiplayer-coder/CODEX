from app.models import Company, ShipmentLine, ShipmentReport, Spu, User
from app.services.sales_orders import create_sales_order


def setup_orders(db_session):
    admin = User(username="batch_archive_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    company = Company(name="批量归档客户", code="PGD", next_order_sequence=1)
    spu = Spu(code="CP", product_name="裁判", style_name="圆领裁判")
    db_session.add_all([admin, company, spu])
    db_session.commit()
    completed = create_sales_order(
        db_session,
        company.id,
        spu.id,
        "",
        "",
        "2026-08-01",
        [{"size": "S", "quantity": 10}],
    )
    unfinished = create_sales_order(
        db_session,
        company.id,
        spu.id,
        "",
        "",
        "2026-08-02",
        [{"size": "M", "quantity": 20}],
    )
    report = ShipmentReport(
        user_id=admin.id,
        order_id=completed.id,
        ship_date="2026-08-09",
        company_name=company.name,
        product_name=completed.product_name,
        style_name=completed.style_name,
        status="approved_after_edit",
    )
    db_session.add(report)
    db_session.flush()
    db_session.add(
        ShipmentLine(
            report_id=report.id,
            order_line_id=completed.lines[0].id,
            size="S",
            quantity=10,
        )
    )
    db_session.commit()
    return admin, completed, unfinished


def test_archive_script_preview_does_not_write(db_session):
    from scripts.archive_completed_sales_orders import collect_archive_candidates
    from app.models import SalesOrderArchive

    _admin, completed, _unfinished = setup_orders(db_session)

    result = collect_archive_candidates(db_session)

    assert [order.id for order in result] == [completed.id]
    assert db_session.query(SalesOrderArchive).count() == 0


def test_archive_script_apply_uses_archive_service(db_session):
    from scripts.archive_completed_sales_orders import apply_archive_candidates, collect_archive_candidates
    from app.services.order_archives import archived_order_ids

    admin, completed, unfinished = setup_orders(db_session)

    applied = apply_archive_candidates(db_session, collect_archive_candidates(db_session), admin.id)

    assert [record.order_id for record in applied] == [completed.id]
    assert archived_order_ids(db_session) == {completed.id}
    assert unfinished.id not in archived_order_ids(db_session)
