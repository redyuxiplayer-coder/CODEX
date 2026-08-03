from app.models import User
from app.services.daily_goals import get_daily_goals, set_daily_goals


def test_set_and_get_daily_goals(db_session):
    admin = User(username="zhangyong", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()

    set_daily_goals(db_session, "2026-07-17", ["先发福建小偷", "补齐源兴发小红帽"], admin.id)

    goals = get_daily_goals(db_session, "2026-07-17")
    assert [goal.content for goal in goals] == ["先发福建小偷", "补齐源兴发小红帽"]
