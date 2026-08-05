"""把已存到 Supabase 的照片迁移到服务器本地磁盘，并更新数据库路径。

用法（服务器上跑，需要 .env 里有 SUPABASE_URL / SUPABASE_SERVICE_KEY 用于下载）：
    cd /home/ubuntu/zy-shipping && set -a && source ./.env && set +a
    # 先预览（只列出，不下载不写库）
    ./.venv/bin/python scripts/migrate_supabase_photos_to_local.py
    # 确认无误后执行
    ./.venv/bin/python scripts/migrate_supabase_photos_to_local.py --apply

迁移后可将 .env 里的 SUPABASE_URL / SUPABASE_SERVICE_KEY 移除。
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.config import UPLOAD_DIR  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    PackingDraftPhoto,
    ReturnReworkPhoto,
    ShipmentPhoto,
    WaybillPhoto,
    WorkInfoLine,
)
from app.services.photos import (  # noqa: E402
    download_file_from_supabase_storage,
    safe_filename_part,
    save_local_upload,
)

TARGETS = [
    (ShipmentPhoto, "file_path", "original_name"),
    (WaybillPhoto, "stored_path", "original_name"),
    (WorkInfoLine, "photo_path", "original_name"),
    (PackingDraftPhoto, "file_path", "original_name"),
    (ReturnReworkPhoto, "file_path", "original_name"),
]


def main() -> int:
    apply = "--apply" in sys.argv
    print("== 预览模式（不下载不写库），加 --apply 才执行 ==" if not apply else "== 执行模式 ==")
    session = SessionLocal()
    total = 0
    try:
        for model, col, name_col in TARGETS:
            for record in session.query(model).all():
                path = getattr(record, col)
                if not path or not str(path).startswith("storage://"):
                    continue
                total += 1
                original = getattr(record, name_col) or ""
                print(f"{model.__name__} #{record.id}: {path}" + (f"（原名 {original}）" if original else ""))
                if not apply:
                    continue
                data, content_type = download_file_from_supabase_storage(path)
                suffix = Path(path).suffix.lower()
                if not suffix:
                    suffix = ".jpg" if content_type and content_type.startswith("image/jpeg") else ".png"
                base = safe_filename_part(original) or f"{model.__name__.lower()}_{record.id}{suffix}"
                if not Path(base).suffix:
                    base = base + suffix
                local_path = save_local_upload(base, data)
                setattr(record, col, local_path)
        if apply:
            session.commit()
            print(f"\n已迁移 {total} 张到 {UPLOAD_DIR} 并更新数据库。")
        else:
            print(f"\n共 {total} 张 storage:// 照片待迁移。")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
