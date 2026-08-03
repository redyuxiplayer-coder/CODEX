from app.auth import verify_password
from app.models import User
from app.services.users import create_worker_user, set_user_password, update_user_profile


def test_set_user_password_replaces_old_password(db_session):
    user = User(username="worker_a", display_name="仓库01", password_hash="old", role="worker", is_active=True)
    db_session.add(user)
    db_session.commit()

    set_user_password(db_session, user.id, "newpass123")

    saved = db_session.get(User, user.id)
    assert verify_password("newpass123", saved.password_hash) is True
    assert verify_password("wrong", saved.password_hash) is False


def test_create_worker_user_defaults_to_worker_role(db_session):
    user = create_worker_user(db_session, username="ck02", display_name="仓库02", password="123456")

    assert user.username == "ck02"
    assert user.display_name == "仓库02"
    assert user.role == "worker"
    assert user.is_active is True
    assert verify_password("123456", user.password_hash) is True


def test_update_user_profile_changes_account_fields(db_session):
    user = User(username="worker_a", display_name="仓库01", password_hash="x", role="worker", is_active=True)
    db_session.add(user)
    db_session.commit()

    updated = update_user_profile(db_session, user.id, username="xiaojie", display_name="小杰", role="admin", is_active=False)

    assert updated.username == "xiaojie"
    assert updated.display_name == "小杰"
    assert updated.role == "admin"
    assert updated.is_active is False


def test_update_user_profile_rejects_duplicate_username(db_session):
    first = User(username="worker_a", display_name="仓库01", password_hash="x", role="worker", is_active=True)
    second = User(username="worker_b", display_name="仓库02", password_hash="x", role="worker", is_active=True)
    db_session.add_all([first, second])
    db_session.commit()

    try:
        update_user_profile(db_session, second.id, username="worker_a", display_name="仓库02", role="worker", is_active=True)
    except ValueError as exc:
        assert "账号已存在" in str(exc)
    else:
        raise AssertionError("duplicate username should fail")
