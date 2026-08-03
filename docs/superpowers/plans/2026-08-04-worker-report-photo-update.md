# Worker Report Photo Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let employees update their own submitted shipment reports by appending photos and correcting quantities or notes, then send the record back to boss review.

**Architecture:** Keep the existing FastAPI routes and SQLAlchemy models. Add one worker-owned update route for shipment reports, reuse the existing photo saving service, and render an update form in the mobile "我的上报" page. Existing photos are only read and displayed; no employee delete path is added.

**Tech Stack:** FastAPI, SQLAlchemy, Jinja2 templates, pytest, FastAPI TestClient.

## Global Constraints

- Employees can only update their own shipment reports.
- Employees can append photos but cannot delete existing photos.
- Any employee update sets the report status to `pending_review`.
- Existing database rows and photo files must not be deleted.
- Local data is backed up before implementation; Tencent Cloud PostgreSQL `zy_shipping` must be backed up before deployment.

---

### Task 1: Worker Shipment Update Route

**Files:**
- Modify: `tests/test_pages.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: `save_uploads(files, company_name, style_name, upload_date) -> list[str]`
- Produces: `POST /mobile/my-reports/{report_id}/update`

- [ ] **Step 1: Write failing tests**

Add tests that create a worker report, post to `/mobile/my-reports/{id}/update`, and assert photos are appended, old photos remain, status becomes `pending_review`, and another worker cannot update the report.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_pages.py::test_worker_can_append_photos_to_own_submitted_report tests/test_pages.py::test_worker_update_report_keeps_existing_photos_and_sets_pending_review tests/test_pages.py::test_worker_cannot_update_another_workers_report -v`

Expected: FAIL with `404 Not Found`.

- [ ] **Step 3: Implement route**

Add a mobile route that checks login, verifies report ownership, validates quantities, appends `ShipmentPhoto` rows for newly saved uploads, updates note and lines, sets status to `pending_review`, and redirects to `/mobile/my-reports`.

- [ ] **Step 4: Run route tests**

Run the same targeted pytest command.

Expected: PASS.

### Task 2: Mobile My Reports Update Form

**Files:**
- Modify: `tests/test_pages.py`
- Modify: `app/templates/mobile/my_reports.html`

**Interfaces:**
- Consumes: `POST /mobile/my-reports/{report_id}/update`
- Produces: update form in "我的上报"

- [ ] **Step 1: Write failing page test**

Add a test asserting the page contains the update route, quantity inputs, photo upload input, and no delete-photo control.

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_pages.py::test_mobile_my_reports_shows_update_form_without_photo_delete -v`

Expected: FAIL because the update form is missing.

- [ ] **Step 3: Implement template**

Render each report with editable size/quantity fields, editable note, multi-file photo input, and a submit button labeled `提交更新给老板审核`.

- [ ] **Step 4: Run page test**

Run the same targeted pytest command.

Expected: PASS.

### Task 3: Full Verification

**Files:**
- No additional files.

**Interfaces:**
- Consumes: all changes from Tasks 1 and 2.
- Produces: verified worker report update behavior.

- [ ] **Step 1: Run targeted tests**

Run: `pytest tests/test_pages.py -v`

Expected: PASS.

- [ ] **Step 2: Run broader tests**

Run: `pytest -v`

Expected: PASS.

- [ ] **Step 3: Commit**

Run:

```bash
git add app/main.py app/templates/mobile/my_reports.html tests/test_pages.py
git commit -m "feat: let workers update shipment reports"
```
