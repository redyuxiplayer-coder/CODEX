import asyncio
from datetime import date
import hashlib
from pathlib import Path

from app.config import UPLOAD_DIR
from app.services import photos as photo_service
from app.services.photos import build_shipment_photo_name, ensure_thumbnail, parse_storage_path, save_uploads


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
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    payload = b"\xff\xd8\xff\xe0" + b"a" * (photo_service.UPLOAD_CHUNK_SIZE + 17)
    upload = ChunkedUpload("box.jpg", payload)

    paths = asyncio.run(
        save_uploads([upload], company_name="源兴发", style_name="小红帽男款", upload_date=date(2026, 7, 30))
    )

    assert len(paths) == 1
    assert Path(paths[0]).read_bytes() == payload
    assert Path(paths[0]).parent.name == "源兴发"
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


def test_save_uploads_always_saves_local_even_when_supabase_is_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(photo_service, "UPLOAD_DIR", tmp_path)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "secret")
    upload = ChunkedUpload("box.jpg", JPG_BYTES)

    paths = asyncio.run(
        save_uploads([upload], company_name="源兴发", style_name="小红帽男款", upload_date=date(2026, 7, 30))
    )

    assert len(paths) == 1
    assert not paths[0].startswith("storage://")
    assert paths[0].endswith("2026-07-30_源兴发_小红帽男款_01.jpg")
    assert Path(paths[0]).parent.name == "源兴发"
    assert Path(paths[0]).read_bytes() == JPG_BYTES


def test_parse_storage_path_returns_bucket_and_object_name():
    bucket, object_name = parse_storage_path("storage://shipment-uploads/2026-07-30_photo_01_abcd.jpg")

    assert bucket == "shipment-uploads"
    assert object_name == "2026-07-30_photo_01_abcd.jpg"


def test_ensure_thumbnail_generates_small_jpeg(tmp_path):
    from PIL import Image

    source = tmp_path / "box.jpg"
    Image.new("RGB", (1200, 800), (200, 80, 80)).save(source, "JPEG", quality=90)

    thumb = ensure_thumbnail(str(source))

    assert thumb.exists()
    assert thumb.stat().st_size > 0
    with Image.open(thumb) as img:
        assert img.width <= 120
        assert img.height <= 120
    assert thumb.name.endswith(".jpg")


def test_ensure_thumbnail_is_cached(tmp_path):
    from PIL import Image

    source = tmp_path / "box.jpg"
    Image.new("RGB", (800, 600), (80, 80, 200)).save(source, "JPEG")

    first = ensure_thumbnail(str(source))
    first_mtime = first.stat().st_mtime_ns
    second = ensure_thumbnail(str(source))

    assert first == second
    assert second.stat().st_mtime_ns == first_mtime
