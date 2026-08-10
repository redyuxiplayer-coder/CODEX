"""Copy the cloud PostgreSQL database to a local SQLite snapshot.

The source is read-only. Source tables are reflected so older schemas are
copied using the source/target column intersection instead of ORM-wide SELECTs.
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy import MetaData, create_engine, select, text
from sqlalchemy.engine import make_url

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.config import DATABASE_URL  # noqa: E402
from app.db import Base, engine_kwargs_for_url  # noqa: E402
import app.models  # noqa: F401,E402


def _is_production_source(source_url: str) -> bool:
    parsed = make_url(source_url)
    return parsed.drivername.startswith("postgresql") and parsed.database == "zy_shipping"


def _source_label(source_url: str) -> str:
    parsed = make_url(source_url)
    host = parsed.host or "本机套接字"
    return f"{parsed.drivername}://{host}/{parsed.database or ''}"


def sync_database(
    source_url: str,
    target_path: Path,
    *,
    allow_non_production_source: bool = False,
) -> dict:
    if not _is_production_source(source_url) and not allow_non_production_source:
        raise ValueError("源数据库不是腾讯云生产 PostgreSQL；如确需继续，请传 --allow-non-production-source")
    target_path = Path(target_path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source_engine = create_engine(source_url, **engine_kwargs_for_url(source_url))
    target_engine = create_engine(f"sqlite:///{target_path.as_posix()}", connect_args={"check_same_thread": False})
    source_metadata = MetaData()
    source_metadata.reflect(bind=source_engine)
    Base.metadata.create_all(target_engine)

    report = {"source": _source_label(source_url), "target": str(target_path), "total_rows": 0, "tables": {}}
    with source_engine.connect() as src, target_engine.begin() as dst:
        dst.execute(text("PRAGMA foreign_keys=OFF"))
        for target_table in Base.metadata.sorted_tables:
            name = target_table.name
            source_table = source_metadata.tables.get(name)
            if source_table is None:
                report["tables"][name] = {"copied_rows": 0, "missing_table": True, "missing_source_columns": []}
                print(f"跳过（源无此表）: {name}")
                continue
            source_names = {column.name for column in source_table.columns}
            target_names = [column.name for column in target_table.columns]
            common_names = [name for name in target_names if name in source_names]
            missing = [name for name in target_names if name not in source_names]
            rows = [dict(row) for row in src.execute(select(*(source_table.c[name] for name in common_names))).mappings().all()]
            dst.execute(target_table.delete())
            if rows:
                dst.execute(target_table.insert(), rows)
            report["tables"][name] = {
                "copied_rows": len(rows),
                "missing_table": False,
                "missing_source_columns": missing,
            }
            report["total_rows"] += len(rows)
            drift = f"；源缺列: {', '.join(missing)}" if missing else ""
            print(f"{name}: {len(rows)} 行{drift}")
        dst.execute(text("PRAGMA foreign_keys=ON"))
    source_engine.dispose()
    target_engine.dispose()
    print(f"共复制 {report['total_rows']} 行 -> {target_path}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="将腾讯云 PostgreSQL 完整同步为 SQLite 快照")
    parser.add_argument("target", nargs="?", default=str(REPO_ROOT / "data" / "cloud_sync.sqlite3"))
    parser.add_argument("--allow-non-production-source", action="store_true")
    args = parser.parse_args()
    print(f"源数据库: {_source_label(DATABASE_URL)}")
    sync_database(
        DATABASE_URL,
        Path(args.target),
        allow_non_production_source=args.allow_non_production_source,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
