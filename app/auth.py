from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import SESSION_COOKIE
from app.models import User

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def authenticate(session: Session, username: str, password: str) -> User | None:
    user = session.query(User).filter_by(username=username, is_active=True).one_or_none()
    if user and verify_password(password, user.password_hash):
        return user
    return None


def current_user(request: Request, session: Session) -> User | None:
    raw_id = request.cookies.get(SESSION_COOKIE)
    if not raw_id or not raw_id.isdigit():
        return None
    return session.get(User, int(raw_id))


def require_user(request: Request, session: Session) -> User:
    user = current_user(request, session)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def require_admin(request: Request, session: Session) -> User:
    user = require_user(request, session)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="没有权限")
    return user


def redirect_if_not_logged_in(request: Request, session: Session) -> User | RedirectResponse:
    user = current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return user
