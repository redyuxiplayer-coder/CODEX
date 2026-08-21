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


def test_mobile_upload_script_handles_order_filters_and_logistics_autosave():
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert 'id="order-company-filter"' not in script
    assert "option.dataset.company === company" in script
    assert "option.dataset.styleColor === styleColor" in script
    assert "option.dataset.search.toLowerCase().includes(query.toLowerCase())" in script
    assert "packDate:" in script
    assert "orderCompanyFilter:" in script
    assert "orderStyleColorFilter:" in script
    assert "orderSearchFilter:" in script
    assert "shippingMethod:" in script
    assert "waybillNo:" in script
    assert "packageCount:" in script
    assert "weightKg:" in script
    assert "clearIncompatibleLogistics" in script
    assert 'zy-report-draft:new:' in script
    assert 'form.dataset.autosaveKey === "new"' in script
    assert "localStorage.removeItem(previousKey)" in script
    assert "/mobile/report/huolala-trips" in script
    assert "if (!company || !shipDate) return []" in script
