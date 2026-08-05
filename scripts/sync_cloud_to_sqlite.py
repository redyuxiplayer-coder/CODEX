"""把云端（Postgres）数据库完整同步为一个 SQLite 文件，用于本地复现。

用法（在服务器上跑，连生产库）：
    cd /home/ubuntu/zy-shipping && set -a && source ./.env && set +a
    ./.venv/bin/python scripts/sync_cloud_to_sqlite.py /home/ubuntu/zy-shipping/data/cloud_sync.sqlite3

生成的文件下载到本地后替换 data/zy_shipping.sqlite3 即可。
脚本只读云端，写的是新文件，不影响生产。
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.config import DATABASE_URL  # noqa: E402
from app.db import Base, engine_kwargs_for_url  # noqa: E402
import app.models  # noqa: F401,E402  # 注册全部表
from sqlalchemy import create_engine, text  # noqa: E402


def main() -> int:
    target_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "data" / "cloud_sync.sqlite3"
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if DATABASE_URL.startswith("sqlite"):
        print(f"注意：源是 SQLite（{DATABASE_URL}），不是生产库！")
    else:
        print(f"源数据库: {DATABASE_URL.split('@')[-1].split('/')[0]}")

    source_engine = create_engine(DATABASE_URL, **engine_kwargs_for_url(DATABASE_URL))
    target_engine = create_engine(f"sqlite:///{target_path.as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(target_engine)

    with source_engine.connect() as src, target_engine.begin() as dst:
        dst.execute(text("PRAGMA foreign_keys=OFF"))
        total = 0
        for table in Base.metadata.sorted_tables:
            name = table.name
            if not src.dialect.has_table(src, name):
                print(f"跳过（源无此表）: {name}")
                continue
            cols = [column.name for column in table.columns]
            rows = src.execute(table.select()).fetchall()
            dst.execute(text(f"DELETE FROM {name}"))
            if rows:
                placeholders = ",".join("?" for _ in cols)
                dst.exec_driver_sql(
                    f"INSERT INTO {name} ({','.join(cols)}) VALUES ({placeholders})",
                    [tuple(row) for row in rows],
                )
            total += len(rows)
            print(f"{name}: {len(rows)} 行")
        dst.execute(text("PRAGMA foreign_keys=ON"))
        print(f"共复制 {total} 行 -> {target_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
