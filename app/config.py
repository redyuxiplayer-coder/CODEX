from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
WAYBILL_DIR = DATA_DIR / "waybills"
EXPORT_DIR = DATA_DIR / "exports"
DATABASE_PATH = DATA_DIR / "zy_shipping.sqlite3"
DATABASE_URL = os.getenv("SUPABASE_DATABASE_URL") or f"sqlite:///{DATABASE_PATH}"
MAX_PHOTOS_PER_REPORT = 20
SESSION_COOKIE = "zy_user_id"
