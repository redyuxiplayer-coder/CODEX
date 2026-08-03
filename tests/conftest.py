import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app import models  # noqa: F401


@pytest.fixture(autouse=True)
def default_admin_env(monkeypatch):
    monkeypatch.setenv("ZY_INITIAL_ADMIN_USERNAME", "zhangyong")
    monkeypatch.setenv("ZY_INITIAL_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("ZY_SYNC_INITIAL_ADMIN_PASSWORD", "1")


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
