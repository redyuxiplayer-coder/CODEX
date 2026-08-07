from fastapi.testclient import TestClient

from app.db import get_session
from app.main import create_app
from app.models import ShipmentReport, User
from app.services.logistics import create_waybill_record, link_reports_to_waybill


def _client(db_session):
    admin = User(username="unlinked_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))
    return client, admin


def _report(db_session, user, date, style, note="", company="广东茉莉"):
    report = ShipmentReport(
        user_id=user.id,
        ship_date=date,
        company_name=company,
        product_name="裁判",
        style_name=style,
        note=note,
        status="auto_approved",
    )
    db_session.add(report)
    db_session.commit()
    return report


def test_unlinked_list_classifies_channel_and_excludes_linked(db_session):
    client, admin = _client(db_session)
    sf = _report(db_session, admin, "2026-07-30", "啤酒节男款", note="发顺丰")
    hl = _report(db_session, admin, "2026-08-02", "红色背心", note="货拉拉发货两包")
    zt = _report(db_session, admin, "2026-07-28", "小红帽", note="中通 小杰上报")
    none = _report(db_session, admin, "2026-07-27", "僵尸棒球男款", note="")
    hist = _report(db_session, admin, "历史导入", "小偷COS", note="已发 573件")
    record = create_waybill_record(db_session, admin.id, "广东茉莉", "2026-07-30", "800210643018", weight_kg=10, package_count=1)
    link_reports_to_waybill(db_session, record.id, [sf.id])

    response = client.get("/api/v1/logistics/unlinked")

    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()["records"]}
    assert sf.id not in rows  # 已挂单的不出现
    assert rows[hl.id]["channel"] == "货拉拉"
    assert rows[zt.id]["channel"] == "中通"
    assert rows[none.id]["channel"] == "待确认"
    assert rows[hist.id]["channel"] == "历史导入"


def test_quick_link_creates_waybill_with_courier_and_links(db_session):
    client, admin = _client(db_session)
    report = _report(db_session, admin, "2026-07-30", "啤酒节男款", note="发顺丰")

    response = client.post(
        "/api/v1/logistics/quick-link",
        data={
            "report_id": str(report.id),
            "courier": "顺丰",
            "waybill_no": "SF1234567890",
            "weight_kg": "10",
            "package_count": "2",
            "note": "",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["waybill_no"] == "SF1234567890"
    assert payload["courier"] == "顺丰"
    assert payload["linked_count"] == 1
    unlinked = client.get("/api/v1/logistics/unlinked").json()["records"]
    assert report.id not in {row["id"] for row in unlinked}


def test_set_unlinked_reason_persists_and_shows(db_session):
    client, admin = _client(db_session)
    report = _report(db_session, admin, "2026-08-02", "红色背心", note="货拉拉")

    response = client.post(
        f"/api/v1/shipments/{report.id}/unlinked-reason",
        data={"reason": "货拉拉无单号"},
    )

    assert response.status_code == 200
    rows = client.get("/api/v1/logistics/unlinked").json()["records"]
    row = next(row for row in rows if row["id"] == report.id)
    assert row["unlinked_reason"] == "货拉拉无单号"
