from pathlib import Path
import hashlib
import re
from shutil import copy2

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config import WAYBILL_DIR
from app.models import Company, WaybillPhoto
from app.services.photos import ALLOWED_SUFFIXES, safe_filename_part


def clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def clean_waybill_date(value) -> str:
    text = clean_text(value)
    if not text:
        return ""
    match = re.fullmatch(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    match = re.fullmatch(r"(\d{1,2})[-/.月](\d{1,2})日?", text)
    if match:
        from datetime import datetime

        month, day = (int(part) for part in match.groups())
        return f"{datetime.now().year:04d}-{month:02d}-{day:02d}"
    return text


def infer_waybill_date_from_name(original_name: str) -> str:
    stem = Path(clean_text(original_name)).stem
    match = re.search(r"(?<!\d)(\d{4})[-_.年](\d{1,2})[-_.月](\d{1,2})日?(?!\d)", stem)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    match = re.search(r"(?<!\d)(\d{1,2})[-_.月](\d{1,2})日?(?!\d)", stem)
    if match:
        from datetime import datetime

        month, day = (int(part) for part in match.groups())
        return f"{datetime.now().year:04d}-{month:02d}-{day:02d}"
    return ""


def waybill_display_name(photo: WaybillPhoto) -> str:
    waybill_date = clean_waybill_date(getattr(photo, "waybill_date", ""))
    if not waybill_date:
        waybill_date = infer_waybill_date_from_name(photo.original_name)
    if not waybill_date and photo.created_at:
        waybill_date = photo.created_at.strftime("%Y-%m-%d")
    if waybill_date:
        return f"{waybill_date} 面单"
    return "快递面单"


def company_names(session: Session) -> list[str]:
    return [row.name for row in session.query(Company).filter(Company.is_active.is_(True)).all()]


def match_company(folder_name: str, names: list[str]) -> str:
    folder_name = clean_text(folder_name)
    if folder_name.startswith("合肥") and "合肥Hoo" in names:
        return "合肥Hoo"
    for name in sorted(names, key=len, reverse=True):
        if folder_name.startswith(name) or name in folder_name:
            return name
    return ""


def _company_dir(company_name: str) -> Path:
    safe = "".join(ch for ch in company_name if ch not in r'\/:*?"<>|').strip() or "unknown"
    target = WAYBILL_DIR / safe
    target.mkdir(parents=True, exist_ok=True)
    return target


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def has_duplicate_waybill_content(session: Session, company_name: str, source_path: Path) -> bool:
    source_hash = file_digest(source_path)
    rows = session.query(WaybillPhoto).filter_by(company_name=clean_text(company_name)).all()
    for row in rows:
        stored_path = Path(row.stored_path)
        if stored_path.exists() and stored_path.is_file() and file_digest(stored_path) == source_hash:
            return True
    return False


def build_waybill_file_name(waybill_date: str, company_name: str, index: int, suffix: str) -> str:
    date_part = clean_waybill_date(waybill_date) or "未填日期"
    company = safe_filename_part(company_name)
    return f"{date_part}_{company}_面单_{index:02d}{suffix.lower()}"


def unique_waybill_target(company_name: str, base_name: str) -> Path:
    company_dir = _company_dir(company_name)
    target = company_dir / base_name
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    index = 2
    while True:
        candidate = company_dir / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def next_waybill_index(session: Session, company_name: str, waybill_date: str) -> int:
    date_part = clean_waybill_date(waybill_date)
    if not date_part:
        return 1
    count = (
        session.query(WaybillPhoto)
        .filter(WaybillPhoto.company_name == clean_text(company_name), WaybillPhoto.waybill_date == date_part)
        .count()
    )
    return count + 1


def save_waybill_file(
    session: Session,
    company_name: str,
    source_path: Path,
    *,
    uploaded_by: int | None = None,
    waybill_date: str = "",
) -> WaybillPhoto | None:
    source_path = source_path.resolve()
    suffix = source_path.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        return None
    existing = session.query(WaybillPhoto).filter_by(source_path=str(source_path)).one_or_none()
    if existing:
        return None
    if has_duplicate_waybill_content(session, company_name, source_path):
        return None
    cleaned_date = clean_waybill_date(waybill_date)
    if not cleaned_date:
        cleaned_date = infer_waybill_date_from_name(source_path.name)
    if not cleaned_date:
        from datetime import datetime

        cleaned_date = datetime.now().strftime("%Y-%m-%d")
    base_name = build_waybill_file_name(cleaned_date, company_name, next_waybill_index(session, company_name, cleaned_date), suffix)
    target = unique_waybill_target(company_name, base_name)
    copy2(source_path, target)
    photo = WaybillPhoto(
        company_name=clean_text(company_name),
        stored_path=str(target),
        original_name=target.name,
        waybill_date=cleaned_date,
        source_path=str(source_path),
        uploaded_by=uploaded_by,
    )
    session.add(photo)
    session.commit()
    session.refresh(photo)
    return photo


async def save_waybill_uploads(
    session: Session,
    company_name: str,
    files: list[UploadFile],
    *,
    uploaded_by: int | None = None,
    waybill_date: str = "",
) -> dict[str, int]:
    imported = 0
    skipped = 0
    for file in files:
        if not file.filename:
            skipped += 1
            continue
        suffix = Path(file.filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            skipped += 1
            continue
        cleaned_date = clean_waybill_date(waybill_date)
        if not cleaned_date:
            from datetime import datetime

            cleaned_date = datetime.now().strftime("%Y-%m-%d")
        base_name = build_waybill_file_name(cleaned_date, company_name, next_waybill_index(session, company_name, cleaned_date) + imported, suffix)
        target = unique_waybill_target(company_name, base_name)
        target.write_bytes(await file.read())
        photo = WaybillPhoto(
            company_name=clean_text(company_name),
            stored_path=str(target),
            original_name=target.name,
            waybill_date=cleaned_date,
            source_path="",
            uploaded_by=uploaded_by,
        )
        session.add(photo)
        imported += 1
    session.commit()
    return {"imported": imported, "skipped": skipped}


def import_waybill_directory(session: Session, root: Path, *, uploaded_by: int | None = None, waybill_date: str = "") -> dict[str, object]:
    root = Path(root)
    names = company_names(session)
    imported = 0
    skipped = 0
    details: list[str] = []
    if not root.exists():
        raise ValueError("快递面单文件夹不存在")
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        company = match_company(path.parent.name, names)
        if not company:
            skipped += 1
            details.append(f"未匹配公司：{path}")
            continue
        photo = save_waybill_file(session, company, path, uploaded_by=uploaded_by, waybill_date=waybill_date)
        if photo:
            imported += 1
        else:
            skipped += 1
    return {"imported": imported, "skipped": skipped, "details": details}


def get_waybill_photos(session: Session, company_name: str) -> list[WaybillPhoto]:
    return (
        session.query(WaybillPhoto)
        .filter_by(company_name=company_name)
        .order_by(WaybillPhoto.waybill_date, WaybillPhoto.created_at, WaybillPhoto.original_name)
        .all()
    )


def list_waybill_photos(session: Session) -> list[WaybillPhoto]:
    return (
        session.query(WaybillPhoto)
        .order_by(WaybillPhoto.company_name, WaybillPhoto.waybill_date, WaybillPhoto.created_at, WaybillPhoto.id)
        .all()
    )


def update_waybill_date(session: Session, photo_id: int, waybill_date: str) -> WaybillPhoto:
    photo = session.query(WaybillPhoto).filter_by(id=photo_id).one()
    photo.waybill_date = clean_waybill_date(waybill_date)
    session.commit()
    session.refresh(photo)
    return photo
