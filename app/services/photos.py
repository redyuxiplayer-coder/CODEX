from pathlib import Path
import os
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4
from datetime import date

from fastapi import UploadFile

from app.config import MAX_PHOTOS_PER_REPORT, UPLOAD_DIR
from app.config import THUMBNAIL_DIR

ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
UPLOAD_CHUNK_SIZE = 1024 * 1024
THUMBNAIL_MAX_SIDE = 120
THUMBNAIL_QUALITY = 80


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


def unique_target(target: Path) -> Path:
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    index = 2
    while True:
        candidate = target.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
        index += 1


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


def save_local_upload(base_name: str, data: bytes, subdir: str = "") -> str:
    target_dir = UPLOAD_DIR / subdir if subdir else UPLOAD_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target = unique_target(target_dir / base_name)
    target.write_bytes(data)
    return str(target)


def thumbnail_path_for(source_path: str) -> Path:
    source = Path(source_path)
    return THUMBNAIL_DIR / f"{source.stem}_thumb.jpg"


def ensure_thumbnail(source_path: str) -> Path:
    """Return a cached 120px JPEG thumbnail for a local photo file."""
    from PIL import Image, ImageOps

    source = Path(source_path)
    if not source.exists():
        raise ValueError("照片文件不存在")
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
    target = thumbnail_path_for(source_path)
    if target.exists():
        return target
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((THUMBNAIL_MAX_SIDE, THUMBNAIL_MAX_SIDE))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.save(target, "JPEG", quality=THUMBNAIL_QUALITY, optimize=True)
    return target


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
        subdir = safe_filename_part(company_name) if company_name else ""
        saved.append(save_local_upload(base_name, data, subdir=subdir))
    return saved
