import importlib


def test_database_url_uses_supabase_database_url_when_present(monkeypatch):
    monkeypatch.setenv("SUPABASE_DATABASE_URL", "postgresql+psycopg://user:pass@example.com/postgres")

    from app import config

    reloaded = importlib.reload(config)

    assert reloaded.DATABASE_URL == "postgresql+psycopg://user:pass@example.com/postgres"
