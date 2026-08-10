from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATA_DIR, DATABASE_URL, EXPORT_DIR, THUMBNAIL_DIR, UPLOAD_DIR


class Base(DeclarativeBase):
    pass


def engine_kwargs_for_url(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {}


def needs_local_storage(database_url: str) -> bool:
    return database_url.startswith("sqlite")


engine = create_engine(DATABASE_URL, **engine_kwargs_for_url(DATABASE_URL))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_storage() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    init_storage()
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_schema_updates()


def ensure_schema_updates(target_engine=None) -> None:
    schema_engine = target_engine or engine
    inspector = inspect(schema_engine)
    table_names = set(inspector.get_table_names())

    def add_columns(table_name: str, definitions: dict[str, str]) -> None:
        if table_name not in table_names:
            return
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        missing = {name: definition for name, definition in definitions.items() if name not in existing}
        if not missing:
            return
        with schema_engine.begin() as connection:
            for name, definition in missing.items():
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}"))

    add_columns(
        "work_info_lines",
        {
            "photo_path": "VARCHAR(500) DEFAULT ''",
            "original_name": "VARCHAR(255) DEFAULT ''",
        },
    )
    add_columns("waybill_photos", {"waybill_date": "VARCHAR(30) DEFAULT ''"})
    add_columns("shipment_lines", {"order_line_id": "INTEGER"})
    add_columns("packing_draft_lines", {"order_line_id": "INTEGER"})
    add_columns(
        "packing_drafts",
        {
            "submitted_report_id": "INTEGER",
            "package_no": "VARCHAR(40) DEFAULT ''",
            "waybill_no": "VARCHAR(80) DEFAULT ''",
            "order_id": "INTEGER",
        },
    )
    add_columns("shipment_photos", {"draft_id": "INTEGER"})
    add_columns(
        "order_lines",
        {
            "sku": "VARCHAR(255) DEFAULT ''",
            "order_id": "INTEGER",
            "customer_sku": "VARCHAR(255) DEFAULT ''",
        },
    )
    add_columns("sku_mappings", {"barcode": "VARCHAR(255) DEFAULT ''"})
    add_columns(
        "shipment_reports",
        {
            "waybill_no": "VARCHAR(80) DEFAULT ''",
            "waybill_id": "INTEGER",
            "order_id": "INTEGER",
        },
    )
    add_columns(
        "companies",
        {
            "code": "VARCHAR(40) DEFAULT ''",
            "next_order_sequence": "INTEGER DEFAULT 1",
        },
    )


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
