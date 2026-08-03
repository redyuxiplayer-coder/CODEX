from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models import User


def _clean(value: str) -> str:
    return (value or "").strip()


def _active_admin_count(session: Session, exclude_user_id: int | None = None) -> int:
    query = session.query(User).filter_by(role="admin", is_active=True)
    if exclude_user_id is not None:
        query = query.filter(User.id != exclude_user_id)
    return query.count()


def set_user_password(session: Session, user_id: int, password: str) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise ValueError("账号不存在")
    user.password_hash = hash_password(password)
    session.commit()
    session.refresh(user)
    return user


def update_user_profile(
    session: Session,
    user_id: int,
    *,
    username: str,
    display_name: str,
    role: str,
    is_active: bool,
) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise ValueError("账号不存在")
    username = _clean(username)
    display_name = _clean(display_name)
    role = _clean(role)
    if not username or not display_name:
        raise ValueError("账号和姓名不能为空")
    if role not in {"admin", "worker"}:
        raise ValueError("角色不正确")
    existing = session.query(User).filter(User.username == username, User.id != user_id).one_or_none()
    if existing is not None:
        raise ValueError("账号已存在")
    would_remove_last_admin = user.role == "admin" and user.is_active and (role != "admin" or not is_active)
    if would_remove_last_admin and _active_admin_count(session, exclude_user_id=user_id) == 0:
        raise ValueError("至少保留一个启用的老板账号")
    user.username = username
    user.display_name = display_name
    user.role = role
    user.is_active = bool(is_active)
    session.commit()
    session.refresh(user)
    return user


def create_worker_user(session: Session, username: str, display_name: str, password: str) -> User:
    existing = session.query(User).filter_by(username=username).one_or_none()
    if existing is not None:
        raise ValueError("账号已存在")
    user = User(
        username=username.strip(),
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        role="worker",
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
