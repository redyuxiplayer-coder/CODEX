from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATA_DIR, DATABASE_URL, EXPORT_DIR, UPLOAD_DIR


class Base(DeclarativeBase):
    pass


def engine_kwargs_for_url(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {}


engine = create_engine(DATABASE_URL, **engine_kwargs_for_url(DATABASE_URL))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_storage() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    init_storage()
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_schema_updates()


def ensure_schema_updates() -> None:
    inspector = inspect(engine)
    if "work_info_lines" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("work_info_lines")}
        with engine.begin() as connection:
            if "photo_path" not in columns:
                connection.execute(text("ALTER TABLE work_info_lines ADD COLUMN photo_path VARCHAR(500) DEFAULT ''"))
            if "original_name" not in columns:
                connection.execute(text("ALTER TABLE work_info_lines ADD COLUMN original_name VARCHAR(255) DEFAULT ''"))
    if "waybill_photos" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("waybill_photos")}
        with engine.begin() as connection:
            if "waybill_date" not in columns:
                connection.execute(text("ALTER TABLE waybill_photos ADD COLUMN waybill_date VARCHAR(30) DEFAULT ''"))
    if "shipment_lines" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("shipment_lines")}
        with engine.begin() as connection:
            if "order_line_id" not in columns:
                connection.execute(text("ALTER TABLE shipment_lines ADD COLUMN order_line_id INTEGER"))
    if "packing_draft_lines" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("packing_draft_lines")}
        with engine.begin() as connection:
            if "order_line_id" not in columns:
                connection.execute(text("ALTER TABLE packing_draft_lines ADD COLUMN order_line_id INTEGER"))


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
