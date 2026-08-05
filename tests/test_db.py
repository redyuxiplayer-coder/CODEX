from app.db import engine_kwargs_for_url, needs_local_storage
from sqlalchemy import create_engine, inspect

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
    assert {"package_no", "waybill_no"}.issubset(draft_columns)
    report_columns = {c["name"] for c in inspector.get_columns("shipment_reports")}
    assert "waybill_no" in report_columns


def test_waybill_table_and_link_column_registered():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "waybill_records" in tables
    report_columns = {c["name"] for c in inspector.get_columns("shipment_reports")}
    assert "waybill_id" in report_columns
