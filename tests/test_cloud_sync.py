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


def test_sync_copies_sales_order_archive_history(tmp_path):
    source = tmp_path / "source-archive.sqlite3"
    connection = sqlite3.connect(source)
    connection.execute(
        "CREATE TABLE sales_order_archives ("
        "id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL, archived_by INTEGER NOT NULL, "
        "archived_at DATETIME NOT NULL, restored_by INTEGER, restored_at DATETIME)"
    )
    connection.execute(
        "INSERT INTO sales_order_archives "
        "(id, order_id, archived_by, archived_at, restored_by, restored_at) "
        "VALUES (1, 9, 2, '2026-08-10 10:00:00', 3, '2026-08-10 11:00:00')"
    )
    connection.commit()
    connection.close()
    target = tmp_path / "target-archive.sqlite3"

    report = sync_database(
        f"sqlite:///{source.as_posix()}",
        target,
        allow_non_production_source=True,
    )

    assert "sales_order_archives" in report["tables"]
    assert report["tables"]["sales_order_archives"]["copied_rows"] == 1
    target_connection = sqlite3.connect(target)
    row = target_connection.execute(
        "SELECT order_id, archived_by, restored_by FROM sales_order_archives"
    ).fetchone()
    target_connection.close()
    assert row == (9, 2, 3)
