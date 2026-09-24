# Task 2 implementation report

## Status and commit

- Complete in isolated worktree `feature/order-line-pricing`.
- Commit: `4e02f31 feat: calculate and audit order line prices`.
- Precision review fix: `25a1506 fix: preserve cents in large order amounts`.
- No UI, export, deployment, or production database files changed.

## Precision review fix (2026-09-24)

- Root cause: multiplying `99999999999999999 × Decimal("9999999999.99")` with Decimal's default precision of 28 produced `999999999998999990000000000.00`; the exact amount is `999999999998999990000000000.01`. Decimal summation could also discard cents.
- Fix: `order_line_amount_cents()` computes each line with integer cents; `money_from_cents()` constructs an exact Decimal from the integer. Both the active-line summary and administrator line serializer use these helpers. Summation stays in integer cents.
- RED: `python -m pytest tests/test_formal_orders.py::test_order_price_summary_keeps_cents_with_large_quantity -q` → `1 failed`, actual subtotal ended in `.0` instead of `.03`.
- RED: `python -m pytest tests/test_formal_orders_api.py::test_price_detail_keeps_cents_with_large_quantity -q` → `1 failed`, actual line amount ended in `.00` instead of `.01`.
- GREEN: both single-test commands → `1 passed` each; `python -m pytest tests/test_formal_orders.py tests/test_formal_orders_api.py -q` → `35 passed`; `python -m pytest tests -q` → `375 passed`.
- `git diff --cached --check` → exit 0 before commit.
- Self-review: the bounded two-decimal unit price needs at most 12 digits when converted to cents, safely within the default Decimal precision; multiplication by unbounded quantity and summation use Python integers. Decimal construction from a fixed-point string retains the exact cents. The two regression tests cover the reviewer quantity and price through the service summary and administrator detail endpoint.

## Files

- `app/services/sales_orders.py`: parses nullable fixed-point prices, saves prices during order creation, summarizes active order lines, and flushes validated line updates without committing.
- `app/api_v1.py`: accepts nullable prices during creation, serializes prices and amounts as two-decimal strings in administrator order payloads, and adds the administrator-only audited update endpoint. The line update and operation log use one commit, with rollback on failure.
- `tests/test_formal_orders.py`: validation, creation, unknown-versus-zero, and summary coverage.
- `tests/test_formal_orders_api.py`: creation and detail serialization, complete/incomplete summaries, active-line filtering, update/clear audit, authorization, wrong-order rejection, and audit-failure rollback coverage.

## Red/green evidence

1. Baseline: `python -m pytest tests/test_formal_orders.py tests/test_formal_orders_api.py -q` → `11 passed`.
2. Service red: `python -m pytest tests/test_formal_orders.py -q` → collection error, `order_price_summary` missing.
3. Service green: same command → `21 passed`.
4. API red: `python -m pytest tests/test_formal_orders_api.py -q` → `6 failed, 6 passed`; failures showed missing price fields, summary, and update route.
5. API green: same command → `12 passed`.
6. Final focused command: `python -m pytest tests/test_formal_orders.py tests/test_formal_orders_api.py -q` → `33 passed`.
7. Full suite after the final test edit: `python -m pytest tests -q` → `373 passed`.
8. `git diff --cached --check` → exit 0, no whitespace errors.

The test runs emitted existing FastAPI/Starlette deprecation warnings under Python 3.14; no test failures remained.

## Self-review

- Confirmed `None` stays distinct from explicit `0.00` through parsing, storage, API output, summary, and audit records.
- Confirmed finite, nonnegative, at-most-two-decimal prices within `NUMERIC(12,2)` range. Invalid values fail before order creation or update commits.
- Confirmed the service checks line ownership before mutation. The API requires administrator access before fetching pricing data or updating it.
- Confirmed totals include active lines only; incomplete orders return a partial subtotal and `total_amount: null`.
- Confirmed the update service flushes but does not commit; the endpoint adds `OperationLog` and commits once. An injected audit insert failure leaves the previous price intact.
- No unresolved Task 2 code concerns. The project-wide Obsidian changelog/shared handoff update belongs to the parent task when the full feature is complete; this Task 2 commit is local and not deployed.

---

# Retained historical Task 2 report

# Task 2 Report

## Scope

Implemented the worker shipment report page experience on top of `fed5f16` without touching Task 3/4 display logic or repair scripts.

## RED

Command:

```bash
python -m pytest tests/test_pages.py tests/test_shipment_order_binding.py tests/test_mobile_upload_script.py -q
```

Result:

- `4 failed, 80 passed`
- Expected RED points were confirmed:
  - old open drafts were still filtered to today only
  - `formal_order_options_payload()` had no `remaining_summary`
  - `/mobile/report` had no order-company / style-color / order-search filters or reusable huolala trip UI
  - `app/static/app.js` did not persist the new filter/logistics fields or clear incompatible logistics on company/date changes

## GREEN

Command:

```bash
python -m pytest tests/test_pages.py tests/test_shipment_order_binding.py tests/test_mobile_upload_script.py -q
```

Result:

- `84 passed`

Related regression:

```bash
python -m pytest tests/test_packing_drafts.py -q
```

- `11 passed`

Frontend build:

```bash
cd web
npm run build
```

- Vite build passed with exit 0
- Existing upstream warnings remained:
  - Rollup `#__PURE__` comment placement warnings from `@vueuse/core`
  - chunk size warning for the admin SPA bundle
- Generated `web/dist/*` noise was restored and not included in the task diff

## Changes

- `app/main.py`
  - added `remaining_summary` to formal order options
  - counted pending/approved bound shipment quantities in formal-order remaining hints
  - removed the `pack_date == today` restriction from worker open-draft loading
  - added reusable huolala trip payload assembly from open drafts and huolala waybill records
  - centralized `/mobile/report` page context so the direct-submit path and draft page stay consistent

- `app/templates/mobile/report.html`
  - made the new report date field explicitly editable/required with `max=today`
  - added company/style-color/order-number filter controls above the order selector
  - changed order option copy to `订单号｜下单日期｜颜色｜还差摘要`
  - added huolala new/existing trip branch controls for both new and edit forms
  - showed all unsubmitted drafts instead of today-only drafts

- `app/static/app.js`
  - added client-side order option filtering by company + style/color + order number query
  - expanded autosave/restore to include date, filters, shipping method, trip mode, waybill, package count, and weight
  - filtered reusable huolala trips by current company/date
  - populated and locked count/weight when an existing huolala trip is selected
  - cleared incompatible logistics selections when company/date context changes

- `app/static/app.css`
  - added lightweight layout styles for the new order filters and huolala choice panels

- tests
  - added RED/GREEN coverage for all-open drafts, remaining summary, missing-logistics rejection, and JS filter/autosave behavior

## Self-review

- Verified no Task 3/4 files were edited
- Reverted unrelated `web/dist` build artifacts before commit
- Kept service-side logistics validation authoritative so the flow does not depend on JS

## Commit

Planned command:

```bash
git add app/main.py app/templates/mobile/report.html app/static/app.js app/static/app.css tests/test_pages.py tests/test_shipment_order_binding.py tests/test_mobile_upload_script.py .superpowers/sdd/task-2-report.md
git commit -m "feat: improve worker shipment report form"
```

## Attention Points

- `remaining_summary` now intentionally reflects pending-review bound shipment quantities, not only approved quantities, so workers do not keep selecting already-submitted sizes.
- The empty-state copy on `/mobile/report` stays compatible with existing page assertions even though the draft query is now all open drafts.

## Review Fix Round 1

### RED

Command:

```bash
python -m pytest tests/test_pages.py tests/test_mobile_upload_script.py -q
```

Result:

- `4 failed, 70 passed`
- Confirmed review regressions:
  - new-form localStorage key still crossed dates and would restore yesterday's `pack_date` / filters / logistics
  - `/mobile/report` HTML still embedded all huolala trips
  - authenticated `/mobile/report/huolala-trips` endpoint did not exist yet
  - empty-state copy still used the old `今天还没有包货草稿。`

### GREEN

Command:

```bash
python -m pytest tests/test_pages.py tests/test_mobile_upload_script.py -q
```

Result:

- `74 passed`

Related regression:

```bash
python -m pytest tests/test_shipment_order_binding.py tests/test_packing_drafts.py -q
```

- `22 passed`

Frontend build:

```bash
cd web
npm run build
```

- Vite build passed with exit 0
- Existing upstream warnings remained:
  - Rollup `#__PURE__` comment placement warnings from `@vueuse/core`
  - chunk size warning for the admin SPA bundle
- Restored tracked `web/dist/*` build outputs before commit so the task diff stayed source-only

### Review Fix Changes

- `app/main.py`
  - narrowed huolala trip payloads to exact `company_name + ship_date`
  - added authenticated `/mobile/report/huolala-trips` JSON endpoint
  - removed full-trip payload injection from `/mobile/report` page context

- `app/templates/mobile/report.html`
  - removed server-rendered huolala trip `<option>` leakage from both new/edit forms
  - kept only the empty placeholder for client-loaded trip choices
  - updated empty-state copy to `还没有未提交包货草稿。`

- `app/templates/mobile/today.html`
  - aligned the empty-state copy with the same `还没有未提交包货草稿。`

- `app/static/app.js`
  - isolated new-draft autosave keys by `pack_date` using the `zy-report-draft:new:<date>` namespace
  - removed the previous new-draft key when the date changes so drafts migrate instead of cross-day contaminating
  - changed huolala existing-trip loading to fetch on demand only after company and date are both known
  - kept package count / weight locking when a matching existing huolala trip is chosen

### Review Fix Commit

Command:

```bash
git add app/main.py app/static/app.js app/templates/mobile/report.html app/templates/mobile/today.html tests/test_pages.py tests/test_mobile_upload_script.py
git add -f .superpowers/sdd/task-2-report.md
git commit -m "fix: tighten worker report draft isolation"
```
