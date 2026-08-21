import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import create_app
from app.models import Company, PackingDraft, SalesOrderArchive, Spu, User
from app.main import formal_order_lines_payload, formal_order_options_payload
from app.services.sales_orders import create_sales_order
from app.services.packing_drafts import create_packing_draft, submit_packing_draft
from app.services.shipments import resolve_order_line_id, submit_shipment_report


def _formal_orders(db_session):
    company = Company(name="源兴发", code="YXF", next_order_sequence=1)
    spu = Spu(code="JS", product_name="啦啦队", style_name="僵尸啦啦队")
    worker = User(username="worker", display_name="员工", password_hash="test", role="worker")
    db_session.add_all([company, spu, worker])
    db_session.commit()
    first = create_sales_order(
        db_session,
        company.id,
        spu.id,
        "红色",
        "RED",
        "2026-08-09",
        [{"size": "S", "quantity": 100}, {"size": "M", "quantity": 80}],
    )
    second = create_sales_order(
        db_session,
        company.id,
        spu.id,
        "蓝色",
        "BLUE",
        "2026-08-09",
        [{"size": "S", "quantity": 60}],
    )
    return worker, first, second


def test_shipment_report_is_bound_to_selected_formal_order(db_session):
    worker, order, _ = _formal_orders(db_session)

    report = submit_shipment_report(
        db_session,
        user_id=worker.id,
        ship_date="2026-08-09",
        company_name="错误公司名",
        product_name="错误产品名",
        style_name="错误款式名",
        lines=[{"size": "S", "quantity": 20, "order_line_id": order.lines[0].id}],
        order_id=order.id,
    )

    assert report.order_id == order.id
    assert report.company_name == "源兴发"
    assert report.product_name == order.product_name
    assert report.style_name == order.style_name


def test_shipment_report_rejects_line_from_another_order(db_session):
    worker, selected_order, other_order = _formal_orders(db_session)

    with pytest.raises(ValueError, match="发货尺码不属于所选订单"):
        submit_shipment_report(
            db_session,
            user_id=worker.id,
            ship_date="2026-08-09",
            company_name="源兴发",
            product_name=selected_order.product_name,
            style_name=selected_order.style_name,
            lines=[{"size": "S", "quantity": 10, "order_line_id": other_order.lines[0].id}],
            order_id=selected_order.id,
        )


def test_packing_draft_keeps_selected_order_through_submission(db_session):
    worker, order, _ = _formal_orders(db_session)
    draft = create_packing_draft(
        db_session,
        user_id=worker.id,
        pack_date="2026-08-09",
        company_name="",
        product_name="",
        style_name="",
        lines=[{"size": "M", "quantity": 15, "order_line_id": order.lines[1].id}],
        order_id=order.id,
        waybill_no="YT-BIND-001",
        shipping_method="courier",
        package_count=1,
        weight_kg=2.5,
    )

    report = submit_packing_draft(db_session, draft.id, worker.id)

    assert draft.order_id == order.id
    assert report.order_id == order.id
    assert report.lines[0].order_line_id == order.lines[1].id


def test_packing_draft_rejects_line_from_another_order(db_session):
    worker, selected_order, other_order = _formal_orders(db_session)

    with pytest.raises(ValueError, match="包货尺码不属于所选订单"):
        create_packing_draft(
            db_session,
            user_id=worker.id,
            pack_date="2026-08-09",
            company_name="",
            product_name="",
            style_name="",
            lines=[{"size": "S", "quantity": 10, "order_line_id": other_order.lines[0].id}],
            order_id=selected_order.id,
            waybill_no="YT-BIND-REJECT-001",
            shipping_method="courier",
            package_count=1,
            weight_kg=2.6,
        )


def test_mobile_form_lists_order_number_date_color_and_only_its_sizes(db_session):
    _worker, first, second = _formal_orders(db_session)

    options = formal_order_options_payload(db_session)
    payload = formal_order_lines_payload(db_session, first.id)

    assert [row["id"] for row in options] == [second.id, first.id]
    first_option = next(row for row in options if row["id"] == first.id)
    assert first_option["system_order_no"] == "YXF-00001-JS-RED"
    assert first_option["order_date"] == "2026-08-09"
    assert first_option["color_name"] == "红色"
    assert [row["order_line_id"] for row in payload["lines"]] == [line.id for line in first.lines]
    assert {row["size"] for row in payload["lines"]} == {"S", "M"}


def test_order_option_contains_remaining_summary(db_session):
    worker, order, _ = _formal_orders(db_session)

    submit_shipment_report(
        db_session,
        user_id=worker.id,
        ship_date="2026-08-10",
        company_name="",
        product_name="",
        style_name="",
        lines=[
            {"size": "S", "quantity": 2, "order_line_id": order.lines[0].id},
            {"size": "M", "quantity": 17, "order_line_id": order.lines[1].id},
        ],
        order_id=order.id,
    )

    option = next(row for row in formal_order_options_payload(db_session) if row["id"] == order.id)

    assert option["remaining_summary"] == "S98 / M63"


def test_worker_mobile_form_submits_one_selected_order(db_session):
    worker, order, _ = _formal_orders(db_session)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))

    page = client.get("/mobile/report")
    options = client.get(f"/mobile/report/options?order_id={order.id}")
    response = client.post(
        "/mobile/today/new",
        data={
            "pack_date": "2026-08-09",
            "order_id": str(order.id),
            "order_line_ids": [str(order.lines[0].id)],
            "sizes": ["S"],
            "quantities": ["20"],
            "shipping_method": "courier",
            "waybill_no": "YT-BIND-ROUTE-001",
            "package_count": "2",
            "weight_kg": "9.5",
        },
        follow_redirects=False,
    )

    assert page.status_code == 200
    assert order.system_order_no in page.text
    assert options.status_code == 200
    assert [row["order_line_id"] for row in options.json()["lines"]] == [line.id for line in order.lines]
    assert response.status_code == 303
    draft = db_session.query(PackingDraft).one()
    assert draft.order_id == order.id
    app.dependency_overrides.clear()


def test_worker_candidates_hide_archived_order(db_session):
    worker, archived_order, active_order = _formal_orders(db_session)
    db_session.add(SalesOrderArchive(order_id=archived_order.id, archived_by=worker.id))
    db_session.commit()

    options = formal_order_options_payload(db_session)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(worker.id))
    report_page = client.get("/mobile/report")
    orders_page = client.get("/mobile/orders")

    assert [row["id"] for row in options] == [active_order.id]
    assert archived_order.system_order_no not in report_page.text
    assert active_order.system_order_no in report_page.text
    assert archived_order.system_order_no not in orders_page.text
    assert active_order.system_order_no in orders_page.text
    app.dependency_overrides.clear()


def test_submit_and_draft_reject_archived_selected_order(db_session):
    worker, order, _ = _formal_orders(db_session)
    db_session.add(SalesOrderArchive(order_id=order.id, archived_by=worker.id))
    db_session.commit()
    line = order.lines[0]

    with pytest.raises(ValueError, match="订单已归档，请先恢复"):
        submit_shipment_report(
            db_session,
            user_id=worker.id,
            ship_date="2026-08-10",
            company_name="",
            product_name="",
            style_name="",
            lines=[{"size": line.size, "quantity": 1, "order_line_id": line.id}],
            order_id=order.id,
        )
    with pytest.raises(ValueError, match="订单已归档，请先恢复"):
        create_packing_draft(
            db_session,
            user_id=worker.id,
            pack_date="2026-08-10",
            company_name="",
            product_name="",
            style_name="",
            lines=[{"size": line.size, "quantity": 1, "order_line_id": line.id}],
            order_id=order.id,
            waybill_no="YT-BIND-ARCHIVE-001",
            shipping_method="courier",
            package_count=1,
            weight_kg=2.7,
        )


def test_order_line_resolver_skips_archived_preferred_line(db_session):
    worker, archived_order, active_order = _formal_orders(db_session)
    archived_line = archived_order.lines[0]
    active_line = active_order.lines[0]
    db_session.add(SalesOrderArchive(order_id=archived_order.id, archived_by=worker.id))
    db_session.commit()

    resolved = resolve_order_line_id(
        db_session,
        archived_order.company.name,
        archived_order.product_name,
        archived_order.style_name,
        archived_line.size,
        preferred=archived_line.id,
    )

    assert resolved == active_line.id


def test_mobile_posts_return_controlled_error_for_archived_order(db_session):
    worker, order, _ = _formal_orders(db_session)
    draft = create_packing_draft(
        db_session,
        user_id=worker.id,
        pack_date="2026-08-10",
        company_name="",
        product_name="",
        style_name="",
        lines=[{"size": "S", "quantity": 1, "order_line_id": order.lines[0].id}],
        order_id=order.id,
        waybill_no="YT-BIND-MOBILE-001",
        shipping_method="courier",
        package_count=1,
        weight_kg=2.8,
    )
    db_session.add(SalesOrderArchive(order_id=order.id, archived_by=worker.id))
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set("zy_user_id", str(worker.id))
    data = {
        "ship_date": "2026-08-10",
        "pack_date": "2026-08-10",
        "order_id": str(order.id),
        "order_line_ids": [str(order.lines[0].id)],
        "sizes": ["S"],
        "quantities": ["1"],
        "shipping_method": "courier",
        "waybill_no": "YT-BIND-ROUTE-ERR-001",
        "package_count": "1",
        "weight_kg": "1.5",
    }

    direct = client.post("/mobile/report", data=data)
    new_draft = client.post("/mobile/today/new", data=data)
    submit_draft = client.post(f"/mobile/today/{draft.id}/submit")

    for response in (direct, new_draft, submit_draft):
        assert response.status_code == 400
        assert response.json()["detail"] == "订单已归档，请先恢复"
    app.dependency_overrides.clear()
