import asyncio
from datetime import date
import hashlib
from pathlib import Path

from app.config import UPLOAD_DIR
from app.services import photos as photo_service
from app.services.photos import build_shipment_photo_name, parse_storage_path, save_uploads


JPG_BYTES = b"\xff\xd8\xff\xe0" + b"a" * 128 + b"\xff\xd9"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"a" * 128


def test_build_shipment_photo_name_uses_upload_date_company_and_style():
    name = build_shipment_photo_name(date(2026, 7, 23), "源兴发", "小红帽男款", 2, ".jpg")

    assert name == "2026-07-23_源兴发_小红帽男款_02.jpg"


def test_build_shipment_photo_name_removes_windows_unsafe_chars():
    name = build_shipment_photo_name(date(2026, 7, 23), '张鹏/A款:女款*?', '赛车服<>', 1, ".png")

    assert name == "2026-07-23_张鹏A款女款_赛车服_01.png"


class ChunkedUpload:
    def __init__(self, filename: str, payload: bytes):
        self.filename = filename
        self._payload = payload
        self._offset = 0
        self.read_sizes = []

    async def read(self, size: int = -1):
        self.read_sizes.append(size)
        if size is None or size < 0:
            chunk = self._payload[self._offset :]
            self._offset = len(self._payload)
            return chunk
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def test_save_uploads_writes_files_in_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(photo_service, "UPLOAD_DIR", tmp_path)
    payload = b"\xff\xd8\xff\xe0" + b"a" * (photo_service.UPLOAD_CHUNK_SIZE + 17)
    upload = ChunkedUpload("box.jpg", payload)

    paths = asyncio.run(
        save_uploads([upload], company_name="源兴发", style_name="小红帽男款", upload_date=date(2026, 7, 30))
    )

    assert len(paths) == 1
    assert Path(paths[0]).read_bytes() == payload
    assert upload.read_sizes[:2] == [photo_service.UPLOAD_CHUNK_SIZE, photo_service.UPLOAD_CHUNK_SIZE]


def test_save_uploads_rejects_files_that_are_not_real_images(tmp_path, monkeypatch):
    monkeypatch.setattr(photo_service, "UPLOAD_DIR", tmp_path)
    upload = ChunkedUpload("bad.png", b"box")

    try:
        asyncio.run(save_uploads([upload], company_name="源兴发", style_name="小红帽男款"))
    except ValueError as exc:
        assert "照片文件内容不正确" in str(exc)
    else:
        raise AssertionError("Expected invalid image content to be rejected")

    assert list(tmp_path.iterdir()) == []


def test_save_uploads_returns_cloud_path_and_schedules_local_backup_when_supabase_is_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(photo_service, "UPLOAD_DIR", tmp_path)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "secret")
    uploaded = []
    backups = []

    def fake_upload(bucket, object_name, data, content_type):
        uploaded.append((bucket, object_name, data, content_type))

    monkeypatch.setattr(photo_service, "upload_file_to_supabase_storage", fake_upload)
    monkeypatch.setattr(photo_service, "schedule_cloud_backup_to_local", lambda storage_path, base_name: backups.append((storage_path, base_name)))
    upload = ChunkedUpload("box.jpg", JPG_BYTES)

    paths = asyncio.run(
        save_uploads([upload], company_name="源兴发", style_name="小红帽男款", upload_date=date(2026, 7, 30))
    )

    digest = hashlib.sha1("2026-07-30_源兴发_小红帽男款_01.jpg".encode("utf-8")).hexdigest()[:12]
    object_name = f"2026-07-30_photo_01_{digest}.jpg"
    assert paths == [f"storage://shipment-uploads/{object_name}"]
    assert uploaded == [("shipment-uploads", object_name, JPG_BYTES, "image/jpeg")]
    assert backups == [(f"storage://shipment-uploads/{object_name}", "2026-07-30_源兴发_小红帽男款_01.jpg")]
    assert list(tmp_path.iterdir()) == []


def test_save_uploads_falls_back_to_local_path_when_supabase_upload_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(photo_service, "UPLOAD_DIR", tmp_path)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "secret")

    def fail_upload(bucket, object_name, data, content_type):
        raise RuntimeError("network down")

    monkeypatch.setattr(photo_service, "upload_file_to_supabase_storage", fail_upload)
    upload = ChunkedUpload("box.jpg", JPG_BYTES)

    paths = asyncio.run(
        save_uploads([upload], company_name="源兴发", style_name="小红帽男款", upload_date=date(2026, 7, 30))
    )

    assert len(paths) == 1
    assert paths[0].endswith("2026-07-30_源兴发_小红帽男款_01.jpg")
    assert Path(paths[0]).read_bytes() == JPG_BYTES


def test_parse_storage_path_returns_bucket_and_object_name():
    bucket, object_name = parse_storage_path("storage://shipment-uploads/2026-07-30_photo_01_abcd.jpg")

    assert bucket == "shipment-uploads"
    assert object_name == "2026-07-30_photo_01_abcd.jpg"
