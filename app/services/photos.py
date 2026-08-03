from pathlib import Path
import hashlib
import mimetypes
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4
from datetime import date

from fastapi import UploadFile

from app.config import MAX_PHOTOS_PER_REPORT, UPLOAD_DIR

ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
UPLOAD_CHUNK_SIZE = 1024 * 1024
SUPABASE_UPLOAD_BUCKET = "shipment-uploads"


def is_supported_image_content(suffix: str, data: bytes) -> bool:
    suffix = suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if suffix == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix == ".webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def safe_filename_part(value: str) -> str:
    text = "".join(ch for ch in str(value).strip() if ch not in r'\/:*?"<>|')
    return text.replace(" ", "") or "未命名"


def build_shipment_photo_name(upload_date: date, company_name: str, style_name: str, index: int, suffix: str) -> str:
    company = safe_filename_part(company_name)
    style = safe_filename_part(style_name)
    return f"{upload_date.isoformat()}_{company}_{style}_{index:02d}{suffix.lower()}"


def unique_target(base_name: str) -> Path:
    target = UPLOAD_DIR / base_name
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    index = 2
    while True:
        candidate = UPLOAD_DIR / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def supabase_storage_configured() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_KEY"))


def build_supabase_object_name(base_name: str) -> str:
    digest = hashlib.sha1(base_name.encode("utf-8")).hexdigest()[:12]
    suffix = Path(base_name).suffix.lower() or ".bin"
    date_prefix = base_name.split("_", 1)[0]
    index_part = Path(base_name).stem.rsplit("_", 1)[-1]
    if not index_part.isdigit():
        index_part = "01"
    return f"{date_prefix}_photo_{int(index_part):02d}_{digest}{suffix}"


def upload_file_to_supabase_storage(bucket: str, object_name: str, data: bytes, content_type: str) -> None:
    supabase_url = os.environ["SUPABASE_URL"].rstrip("/")
    service_key = os.environ["SUPABASE_SERVICE_KEY"]
    quoted_name = "/".join(urllib.parse.quote(part, safe="") for part in object_name.split("/"))
    endpoint = f"{supabase_url}/storage/v1/object/{bucket}/{quoted_name}"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": content_type,
        "x-upsert": "true",
    }
    request = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        response.read()


def parse_storage_path(path: str) -> tuple[str, str]:
    if not path.startswith("storage://"):
        raise ValueError("不是 Supabase Storage 路径")
    bucket_and_name = path.removeprefix("storage://")
    bucket, _, object_name = bucket_and_name.partition("/")
    if not bucket or not object_name:
        raise ValueError("Supabase Storage 路径不完整")
    return bucket, object_name


def download_file_from_supabase_storage(storage_path: str) -> tuple[bytes, str]:
    supabase_url = os.environ["SUPABASE_URL"].rstrip("/")
    service_key = os.environ["SUPABASE_SERVICE_KEY"]
    bucket, object_name = parse_storage_path(storage_path)
    quoted_name = "/".join(urllib.parse.quote(part, safe="") for part in object_name.split("/"))
    endpoint = f"{supabase_url}/storage/v1/object/{bucket}/{quoted_name}"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
    }
    request = urllib.request.Request(endpoint, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=60) as response:
        content_type = response.headers.get("content-type") or "application/octet-stream"
        return response.read(), content_type


async def read_valid_upload_data(file: UploadFile, suffix: str) -> bytes:
    first_chunk = await file.read(UPLOAD_CHUNK_SIZE)
    if not first_chunk or not is_supported_image_content(suffix, first_chunk):
        raise ValueError("照片文件内容不正确，请重新选择原始照片上传")
    chunks = [first_chunk]
    while True:
        chunk = await file.read(UPLOAD_CHUNK_SIZE)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def save_local_upload(base_name: str, data: bytes) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = unique_target(base_name)
    target.write_bytes(data)
    return str(target)


def backup_supabase_file_to_local(storage_path: str, base_name: str) -> None:
    data, _content_type = download_file_from_supabase_storage(storage_path)
    save_local_upload(base_name, data)


def schedule_cloud_backup_to_local(storage_path: str, base_name: str) -> None:
    if os.getenv("VERCEL"):
        return
    thread = threading.Thread(target=backup_supabase_file_to_local, args=(storage_path, base_name), daemon=True)
    thread.start()


def maybe_upload_to_supabase(base_name: str, data: bytes) -> str | None:
    if not supabase_storage_configured():
        return None
    object_name = build_supabase_object_name(base_name)
    content_type = mimetypes.guess_type(base_name)[0] or "application/octet-stream"
    try:
        upload_file_to_supabase_storage(SUPABASE_UPLOAD_BUCKET, object_name, data, content_type)
    except Exception:
        return None
    storage_path = f"storage://{SUPABASE_UPLOAD_BUCKET}/{object_name}"
    try:
        schedule_cloud_backup_to_local(storage_path, base_name)
    except Exception:
        pass
    return storage_path


async def save_uploads(
    files: list[UploadFile],
    *,
    company_name: str = "",
    style_name: str = "",
    upload_date: date | None = None,
) -> list[str]:
    if len(files) > MAX_PHOTOS_PER_REPORT:
        raise ValueError(f"每次最多上传 {MAX_PHOTOS_PER_REPORT} 张照片")
    saved = []
    upload_date = upload_date or date.today()
    for file in files:
        if not file.filename:
            continue
        suffix = Path(file.filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise ValueError("照片只支持 jpg、jpeg、png、webp")
        if company_name and style_name:
            base_name = build_shipment_photo_name(upload_date, company_name, style_name, len(saved) + 1, suffix)
        else:
            base_name = f"{uuid4().hex}{suffix}"
        data = await read_valid_upload_data(file, suffix)
        cloud_path = maybe_upload_to_supabase(base_name, data)
        saved.append(cloud_path or save_local_upload(base_name, data))
    return saved
