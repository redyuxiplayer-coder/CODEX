from app.db import engine_kwargs_for_url, ensure_schema_updates, needs_local_storage
from sqlalchemy import create_engine, inspect
from pathlib import Path

from app.db import Base
from app import models  # noqa: F401


def test_engine_kwargs_only_use_sqlite_thread_check_for_sqlite():
    assert engine_kwargs_for_url("sqlite:///data.db") == {"connect_args": {"check_same_thread": False}}
    assert engine_kwargs_for_url("postgresql+psycopg://user:pass@example.com/postgres") == {}


def test_local_storage_is_only_required_for_sqlite():
    assert needs_local_storage("sqlite:///data.db") is True
    assert needs_local_storage("postgresql+psycopg://user:pass@example.com/postgres") is False


def test_new_ledger_tables_and_columns_are_registered():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    for name in [
        "order_ledger_entries",
        "return_reworks",
        "return_rework_photos",
        "order_adjustments",
        "order_line_closes",
        "order_line_comments",
    ]:
        assert name in tables, f"missing table {name}"

    order_columns = {c["name"] for c in inspector.get_columns("order_lines")}
    assert "sku" in order_columns
    sku_columns = {c["name"] for c in inspector.get_columns("sku_mappings")}
    assert "barcode" in sku_columns
    draft_columns = {c["name"] for c in inspector.get_columns("packing_drafts")}
    assert {"package_no", "shipping_method", "waybill_no", "package_count", "weight_kg"}.issubset(draft_columns)
    report_columns = {c["name"] for c in inspector.get_columns("shipment_reports")}
    assert "waybill_no" in report_columns


def test_formal_order_tables_and_columns_are_registered():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)

    assert {"spus", "sales_orders"}.issubset(inspector.get_table_names())
    company_columns = {c["name"] for c in inspector.get_columns("companies")}
    assert {"code", "next_order_sequence"}.issubset(company_columns)
    order_line_columns = {c["name"] for c in inspector.get_columns("order_lines")}
    assert {"order_id", "customer_sku"}.issubset(order_line_columns)
    draft_columns = {c["name"] for c in inspector.get_columns("packing_drafts")}
    assert {"order_id", "shipping_method", "package_count", "weight_kg"}.issubset(draft_columns)
    report_columns = {c["name"] for c in inspector.get_columns("shipment_reports")}
    assert "order_id" in report_columns


def test_sales_order_archive_table_tracks_archive_and_restore_history():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)

    assert "sales_order_archives" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("sales_order_archives")}
    assert {
        "id",
        "order_id",
        "archived_by",
        "archived_at",
        "restored_by",
        "restored_at",
    }.issubset(columns)


def test_schema_updates_add_formal_order_columns_to_legacy_sqlite():
    legacy_engine = create_engine("sqlite:///:memory:")
    with legacy_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE companies (id INTEGER PRIMARY KEY, name VARCHAR(120), note TEXT, is_active BOOLEAN)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE order_lines (id INTEGER PRIMARY KEY, company_id INTEGER, product_name VARCHAR(160), "
            "style_name VARCHAR(160), size VARCHAR(80), quantity INTEGER)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE packing_drafts (id INTEGER PRIMARY KEY, user_id INTEGER, pack_date VARCHAR(30))"
        )
        connection.exec_driver_sql(
            "CREATE TABLE shipment_reports (id INTEGER PRIMARY KEY, user_id INTEGER, ship_date VARCHAR(30))"
        )
    Base.metadata.create_all(bind=legacy_engine)

    ensure_schema_updates(legacy_engine)

    inspector = inspect(legacy_engine)
    assert {"spus", "sales_orders"}.issubset(inspector.get_table_names())
    assert {"code", "next_order_sequence"}.issubset(
        {c["name"] for c in inspector.get_columns("companies")}
    )
    assert {"order_id", "customer_sku"}.issubset(
        {c["name"] for c in inspector.get_columns("order_lines")}
    )
    assert {"order_id", "shipping_method", "package_count", "weight_kg"}.issubset(
        {c["name"] for c in inspector.get_columns("packing_drafts")}
    )
    assert "order_id" in {c["name"] for c in inspector.get_columns("shipment_reports")}


def test_postgres_formal_order_migration_contains_required_schema_and_grants():
    migration = Path("scripts/migration_2026_08_09_formal_orders.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS spus" in migration
    assert "CREATE TABLE IF NOT EXISTS sales_orders" in migration
    assert "uq_sales_orders_company_sequence" in migration
    assert "ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS customer_sku" in migration
    assert "ALTER TABLE shipment_reports ADD COLUMN IF NOT EXISTS order_id" in migration
    assert "GRANT ALL PRIVILEGES ON TABLE spus, sales_orders TO zy_shipping" in migration
    assert "ALTER TABLE sales_orders DISABLE ROW LEVEL SECURITY" in migration


def test_postgres_order_archive_migration_is_idempotent_and_grants_app_access():
    migration = Path("scripts/migration_2026_08_10_sales_order_archives.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS sales_order_archives" in migration
    assert "CREATE INDEX IF NOT EXISTS ix_sales_order_archives_order_id" in migration
    assert "CREATE INDEX IF NOT EXISTS ix_sales_order_archives_restored_at" in migration
    assert "GRANT ALL PRIVILEGES ON TABLE sales_order_archives TO zy_shipping" in migration
    assert "GRANT USAGE, SELECT ON SEQUENCE sales_order_archives_id_seq TO zy_shipping" in migration


def test_waybill_table_and_link_column_registered():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "waybill_records" in tables
    report_columns = {c["name"] for c in inspector.get_columns("shipment_reports")}
    assert "waybill_id" in report_columns


def test_postgres_packing_logistics_migration_is_idempotent_and_grants_app_access():
    migration = Path("scripts/migration_2026_08_21_packing_logistics.sql").read_text(encoding="utf-8")

    assert "ALTER TABLE packing_drafts ADD COLUMN IF NOT EXISTS shipping_method" in migration
    assert "ALTER TABLE packing_drafts ADD COLUMN IF NOT EXISTS package_count" in migration
    assert "ALTER TABLE packing_drafts ADD COLUMN IF NOT EXISTS weight_kg" in migration
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE packing_drafts TO zy_shipping" in migration
