import sqlite3

import pytest

from scripts.sync_cloud_to_sqlite import sync_database


def test_sync_requires_explicit_override_for_non_production_source(tmp_path):
    source = tmp_path / "source.sqlite3"
    sqlite3.connect(source).close()

    with pytest.raises(ValueError, match="allow-non-production-source"):
        sync_database(f"sqlite:///{source.as_posix()}", tmp_path / "target.sqlite3")


def test_sync_copies_only_column_intersection_and_reports_schema_drift(tmp_path):
    source = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE companies (id INTEGER PRIMARY KEY, name VARCHAR(120), is_active BOOLEAN)")
    connection.execute("INSERT INTO companies (id, name, is_active) VALUES (1, '源兴发', 1)")
    connection.commit()
    connection.close()
    target = tmp_path / "target.sqlite3"

    report = sync_database(
        f"sqlite:///{source.as_posix()}",
        target,
        allow_non_production_source=True,
    )

    target_connection = sqlite3.connect(target)
    row = target_connection.execute("SELECT id, name, code, next_order_sequence FROM companies").fetchone()
    target_connection.close()
    assert row == (1, "源兴发", "", 1)
    assert "code" in report["tables"]["companies"]["missing_source_columns"]
    assert report["tables"]["companies"]["copied_rows"] == 1
