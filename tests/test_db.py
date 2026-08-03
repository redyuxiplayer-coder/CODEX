from app.db import engine_kwargs_for_url, needs_local_storage


def test_engine_kwargs_only_use_sqlite_thread_check_for_sqlite():
    assert engine_kwargs_for_url("sqlite:///data.db") == {"connect_args": {"check_same_thread": False}}
    assert engine_kwargs_for_url("postgresql+psycopg://user:pass@example.com/postgres") == {}


def test_local_storage_is_only_required_for_sqlite():
    assert needs_local_storage("sqlite:///data.db") is True
    assert needs_local_storage("postgresql+psycopg://user:pass@example.com/postgres") is False
