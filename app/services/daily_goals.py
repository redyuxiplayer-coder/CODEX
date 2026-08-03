from sqlalchemy.orm import Session

from app.models import DailyGoal


def get_daily_goals(session: Session, goal_date: str) -> list[DailyGoal]:
    return (
        session.query(DailyGoal)
        .filter_by(goal_date=goal_date)
        .order_by(DailyGoal.sort_order, DailyGoal.id)
        .all()
    )


def set_daily_goals(session: Session, goal_date: str, contents: list[str], updated_by: int | None) -> list[DailyGoal]:
    session.query(DailyGoal).filter_by(goal_date=goal_date).delete()
    goals = []
    for index, content in enumerate(contents):
        text = content.strip()
        if not text:
            continue
        goal = DailyGoal(goal_date=goal_date, content=text, sort_order=index, updated_by=updated_by)
        session.add(goal)
        goals.append(goal)
    session.commit()
    return get_daily_goals(session, goal_date)
