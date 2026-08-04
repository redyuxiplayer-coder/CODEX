from fastapi.testclient import TestClient

from app.db import get_session
from app.main import create_app
from app.models import OrderLineComment, ReturnRework, User
from app.services.orders import create_order_line, get_order_balances

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"a" * 256


def _admin_order(db_session):
    admin = User(username="detail_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    order = create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)
    return admin, order


def _client(db_session):
    admin, order = _admin_order(db_session)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    client.cookies.set("zy_user_id", str(admin.id))
    return client, admin, order


def test_order_line_detail_page_shows_ledger_and_forms(db_session):
    client, _admin, order = _client(db_session)

    response = client.get(f"/admin/order-lines/{order.id}")

    assert response.status_code == 200
    for text in ["订单流水", "退货/返工", "盘点/调整", "关闭", "沟通记录"]:
        assert text in response.text


def test_order_line_forms_create_records_and_affect_balance(db_session):
    client, admin, order = _client(db_session)

    response = client.post(
        f"/admin/order-lines/{order.id}/returns",
        data={"quantity": "3", "reason_type": "退回返工", "reason": "测试返工", "status": "pending_rework"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    row = get_order_balances(db_session)[0]
    assert row["returned"] == 3
    assert row["remaining"] == 103

    record = db_session.query(ReturnRework).one()
    response = client.post(
        f"/admin/order-lines/{order.id}/returns/{record.id}/status",
        data={"status": "scrapped"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    row = get_order_balances(db_session)[0]
    assert row["adjusted"] == 3
    assert row["remaining"] == 100

    client.post(
        f"/admin/order-lines/{order.id}/adjustments",
        data={"quantity": "1", "reason": "盘亏"},
        follow_redirects=False,
    )
    client.post(
        f"/admin/order-lines/{order.id}/closes",
        data={"quantity": "2", "reason": "客户不要"},
        follow_redirects=False,
    )
    client.post(
        f"/admin/order-lines/{order.id}/comments",
        data={"content": "客户说这单先不补了"},
        follow_redirects=False,
    )
    row = get_order_balances(db_session)[0]
    assert row["adjusted"] == 4
    assert row["closed"] == 2
    assert row["remaining"] == 100 + 3 - 4 - 2
    comment = db_session.query(OrderLineComment).one()
    assert comment.content == "客户说这单先不补了"


def test_return_photo_upload_and_route(db_session):
    client, admin, order = _client(db_session)

    response = client.post(
        f"/admin/order-lines/{order.id}/returns",
        data={"quantity": "2", "reason_type": "质量问题", "reason": "有污渍", "status": "pending_rework"},
        files={"photos": ("ret.png", PNG_BYTES, "image/png")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    record = db_session.query(ReturnRework).one()
    assert len(record.photos) == 1
    photo = record.photos[0]
    photo_response = client.get(f"/photos/return/{photo.id}")
    assert photo_response.status_code == 200
