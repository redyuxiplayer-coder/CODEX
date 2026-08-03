from pathlib import Path


def test_mobile_upload_submit_waits_for_photo_compression():
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert "waitForPhotoCompression" in script
    assert 'input.dataset.compressing === "1"' in script
    assert "HTMLFormElement.prototype.submit.call(form)" in script
    assert "form.requestSubmit" not in script


def test_mobile_upload_compresses_smaller_and_reports_progress():
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert "const maxSide = 1024" in script
    assert '"image/jpeg", 0.58' in script
    assert "file.size < 260 * 1024" in script
    assert "正在处理照片" in script
    assert "await nextFrame()" in script
