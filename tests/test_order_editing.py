from app.services.orders import create_order_line, update_order_line, delete_order_line
from app.models import OrderLine


def test_update_order_line_changes_size_and_quantity(db_session):
    order = create_order_line(db_session, "广东茉莉", "囚服", "短袖囚服两件套", "S", 260)

    updated = update_order_line(db_session, order.id, size="M", quantity=700, note="改过")

    assert updated.size == "M"
    assert updated.quantity == 700
    assert updated.note == "改过"


def test_delete_order_line_marks_order_inactive(db_session):
    order = create_order_line(db_session, "广东茉莉", "囚服", "短袖囚服两件套", "S", 260)

    delete_order_line(db_session, order.id)

    saved = db_session.get(OrderLine, order.id)
    assert saved.is_active is False
