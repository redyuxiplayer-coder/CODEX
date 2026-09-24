# Order Line Pricing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add administrator-only unit prices per formal-order size, derived line and order amounts, audited price editing, and price columns in internal exports only.

**Architecture:** Store a nullable fixed-point `unit_price` on each `OrderLine`; keep derived amounts out of the database and calculate them with `Decimal` in service/API/export code. Extend only administrator endpoints and Vue pages with price data, while retaining the current employee payloads and customer exports unchanged.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, PostgreSQL/SQLite compatibility, Vue 3, Element Plus, openpyxl, pytest, Vite.

## Global Constraints

- Currency is RMB; unit price is nullable, nonnegative, and has at most two decimal places.
- A null unit price means “未填写”; `0.00` is a valid explicit price and has different semantics.
- Line amount is `ordered quantity × unit price`; no derived amount is persisted.
- An order total is complete only when every active line has a unit price; otherwise return the known subtotal and missing-line count.
- Price data is available only through administrator pages, administrator endpoints, operation logs, and internal exports.
- Employee pages and payloads and all customer exports must contain no unit-price or amount fields.
- Existing orders are not backfilled. Production PostgreSQL must be backed up before migration.
- Account deletion is out of scope; departing employees use the existing account deactivation control.

---

### Task 1: Nullable fixed-point price storage and migration

**Files:**
- Modify: `app/models.py`
- Modify: `app/db.py`
- Create: `scripts/migration_2026_09_24_order_line_price.sql`
- Modify: `tests/test_db.py`

**Interfaces:**
- Produces: `OrderLine.unit_price: Decimal | None`, backed by `NUMERIC(12, 2)`.
- Produces: idempotent PostgreSQL migration adding `unit_price` and a nonnegative check constraint.

- [ ] **Step 1: Write failing schema and migration tests**

Add assertions that a fresh schema and an upgraded legacy `order_lines` table contain nullable `unit_price`, and that the migration contains both the column and nonnegative constraint:

```python
assert "unit_price" in order_line_columns
assert "ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS unit_price NUMERIC(12, 2)" in migration
assert "CHECK (unit_price IS NULL OR unit_price >= 0)" in migration
```

- [ ] **Step 2: Run the focused tests and confirm the expected failure**

Run: `python -m pytest tests/test_db.py -q`

Expected: failure because `unit_price` and the migration file do not exist.

- [ ] **Step 3: Add the SQLAlchemy field and compatibility upgrade**

Use SQLAlchemy fixed-point storage:

```python
from decimal import Decimal
from sqlalchemy import Numeric

unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
```

Add `"unit_price": "NUMERIC(12, 2)"` to the `order_lines` compatibility-column map in `ensure_schema_updates` so local legacy SQLite databases gain a nullable field.

- [ ] **Step 4: Add the idempotent PostgreSQL migration**

Create:

```sql
ALTER TABLE order_lines
    ADD COLUMN IF NOT EXISTS unit_price NUMERIC(12, 2);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_order_lines_unit_price_nonnegative'
    ) THEN
        ALTER TABLE order_lines
            ADD CONSTRAINT ck_order_lines_unit_price_nonnegative
            CHECK (unit_price IS NULL OR unit_price >= 0);
    END IF;
END $$;
```

- [ ] **Step 5: Run schema tests and commit**

Run: `python -m pytest tests/test_db.py -q`

Expected: all `test_db.py` tests pass.

Commit:

```bash
git add app/models.py app/db.py scripts/migration_2026_09_24_order_line_price.sql tests/test_db.py
git commit -m "feat: add nullable order line unit price"
```

---

### Task 2: Price validation, creation, summaries, and audited updates

**Files:**
- Modify: `app/services/sales_orders.py`
- Modify: `app/api_v1.py`
- Modify: `tests/test_formal_orders.py`
- Modify: `tests/test_formal_orders_api.py`

**Interfaces:**
- Produces: `parse_unit_price(value: object) -> Decimal | None`.
- Produces: `order_price_summary(order: SalesOrder) -> dict` with `known_subtotal`, `missing_price_count`, `is_complete`, and `total_amount`.
- Produces: `update_order_line_unit_price(session, order_id: int, line_id: int, value: object) -> tuple[OrderLine, Decimal | None]`.
- Produces: `POST /api/v1/sales-orders/{order_id}/lines/{line_id}/unit-price` with JSON `{ "unit_price": string | number | null }`.

- [ ] **Step 1: Write failing service tests for creation and validation**

Cover `None`, empty string, `0`, `12.30`, negative values, three decimal places, and nonnumeric input. Assert created order lines preserve `Decimal("12.30")` and omitted prices stay `None`.

```python
assert parse_unit_price("") is None
assert parse_unit_price("12.30") == Decimal("12.30")
with pytest.raises(ValueError, match="单价"):
    parse_unit_price("12.345")
```

- [ ] **Step 2: Run the service tests and confirm failure**

Run: `python -m pytest tests/test_formal_orders.py -q`

Expected: import or assertion failure because pricing helpers do not exist.

- [ ] **Step 3: Implement fixed-point parsing and order creation**

Normalize using `Decimal(str(value))`, reject nonfinite, negative, over-two-decimal, and values above `9999999999.99`, and quantize valid values to `Decimal("0.01")`. Add the normalized value to `_clean_order_lines` and set `OrderLine(unit_price=row["unit_price"])` during creation.

- [ ] **Step 4: Write failing API tests for summaries, updates, authorization, and audit**

Assert administrator detail payloads contain:

```python
assert payload["lines"][0]["unit_price"] == "12.30"
assert payload["lines"][0]["line_amount"] == "1230.00"
assert payload["price_summary"] == {
    "known_subtotal": "1230.00",
    "missing_price_count": 1,
    "is_complete": False,
    "total_amount": None,
}
```

Post a new price and assert the row changes, the response becomes complete when applicable, and an `OperationLog` with action `order_line_unit_price_update` contains order ID, line ID, size, `before`, and `after`. Use a worker-authenticated client and assert both detail and update pricing endpoints return `403`.

- [ ] **Step 5: Run the focused API tests and confirm failure**

Run: `python -m pytest tests/test_formal_orders_api.py -q`

Expected: pricing fields/endpoint assertions fail.

- [ ] **Step 6: Implement administrator payloads and audited update endpoint**

Add a Pydantic payload accepting `str | Decimal | None`. Serialize money as two-decimal strings to avoid JSON floating-point ambiguity. Calculate summary from active lines only:

```python
known = sum((line.quantity * line.unit_price for line in active if line.unit_price is not None), Decimal("0.00"))
missing = sum(1 for line in active if line.unit_price is None)
```

Verify the line belongs to the URL order before mutation. Capture `before`, update and flush, add the operation log, then commit once so the value and audit record succeed or fail together.

- [ ] **Step 7: Run pricing service/API tests and commit**

Run: `python -m pytest tests/test_formal_orders.py tests/test_formal_orders_api.py -q`

Expected: all tests pass.

Commit:

```bash
git add app/services/sales_orders.py app/api_v1.py tests/test_formal_orders.py tests/test_formal_orders_api.py
git commit -m "feat: calculate and audit order line prices"
```

---

### Task 3: Administrator order creation and detail UI

**Files:**
- Modify: `web/src/api.js`
- Modify: `web/src/views/NewOrder.vue`
- Modify: `web/src/views/SalesOrderDetail.vue`
- Create: `web/src/order-pricing.js`
- Create: `web/src/order-pricing.test.js`

**Interfaces:**
- Consumes: administrator pricing payloads and update endpoint from Task 2.
- Produces: `formatMoney(value)`, `priceStatusText(summary)`, and an administrator-only price editor.

- [ ] **Step 1: Write failing pure-JavaScript display tests**

Use Node's test runner to assert null values display `未填写`, zero displays `¥0.00`, complete totals display `订单总金额 ¥...`, and partial totals include known subtotal and missing count.

Run: `node --test web/src/order-pricing.test.js`

Expected: failure because `order-pricing.js` does not exist.

- [ ] **Step 2: Implement the formatting helper and make tests pass**

Keep formatting separate from Vue components:

```js
export function formatMoney(value) {
  if (value === null || value === undefined || value === "") return "未填写";
  return `¥${Number(value).toFixed(2)}`;
}
```

Run: `node --test web/src/order-pricing.test.js`

Expected: all pricing display tests pass.

- [ ] **Step 3: Add price input to new-order rows**

Add `unit_price: null` to default and newly added lines. Use `el-input-number` with `:min="0"`, `:precision="2"`, and `:step="0.01"`. Keep blank values as `null` in the request.

- [ ] **Step 4: Add inline editing and summary to order detail**

Add “商品单价” and “尺码金额” columns. Each row supports edit/save/cancel without changing the selected fulfillment line. After save, call the existing guarded `load()` so stale responses cannot overwrite another order. Render either the complete total or partial status from `price_summary`.

- [ ] **Step 5: Build and run frontend tests**

Run:

```bash
node --test web/src/order-pricing.test.js web/src/order-links.test.js
cd web && npm run build
```

Expected: all Node tests pass and Vite exits `0`, producing updated `web/dist` assets.

- [ ] **Step 6: Commit the administrator UI**

```bash
git add web/src/api.js web/src/views/NewOrder.vue web/src/views/SalesOrderDetail.vue web/src/order-pricing.js web/src/order-pricing.test.js web/dist
git commit -m "feat: manage per-size prices in formal orders"
```

---

### Task 4: Internal export pricing with customer-export isolation

**Files:**
- Modify: `app/services/orders.py`
- Modify: `app/services/exports.py`
- Modify: `tests/test_customer_export.py`
- Modify: `tests/test_core.py`

**Interfaces:**
- Consumes: `OrderLine.unit_price` from Task 1.
- Produces: internal balance rows with `unit_price` and `line_amount`; customer workbooks retain their exact existing headers.

- [ ] **Step 1: Write failing export tests**

Create a priced formal order and assert internal `订单发货明细` and `未发货明细` contain “商品单价” and “金额”, numeric values `12.3` and `1230`, and number format `¥#,##0.00`. Create an unpriced line and assert both cells are blank. Assert every customer sheet header lacks “商品单价”, “单价”, “金额”, and “订单总金额”.

- [ ] **Step 2: Run focused export tests and confirm failure**

Run: `python -m pytest tests/test_customer_export.py tests/test_core.py -q`

Expected: internal price columns are missing.

- [ ] **Step 3: Project price data into balance rows**

Select `OrderLine.unit_price` in `get_order_balances`. Preserve `None`; calculate `line_amount` with `Decimal` only when price is present. Since merged legacy rows can represent more than one order line, emit a price only when all merged members have the same non-null price; otherwise leave price and amount blank to avoid fabricating a value.

- [ ] **Step 4: Add numeric price cells only to internal balance sheets**

Extend `add_balance_sheet` headers and rows, then set Excel number formats on the new columns. Do not change `add_customer_balance_sheet` or `add_customer_detail_sheet`. Price columns are based on ordered quantity, not shipped quantity.

- [ ] **Step 5: Run export tests and commit**

Run: `python -m pytest tests/test_customer_export.py tests/test_core.py -q`

Expected: all tests pass and customer headers remain unchanged.

Commit:

```bash
git add app/services/orders.py app/services/exports.py tests/test_customer_export.py tests/test_core.py
git commit -m "feat: include prices in internal exports"
```

---

### Task 5: Full regression, browser acceptance, and documentation

**Files:**
- Modify: `README.md`
- Modify after deployment: `E:/CODEX/1-项目/仓库系统管理/07-更新日志.md`
- Modify after deployment: `E:/CODEX/1-项目/仓库系统管理/11-共享接手状态.md`
- Create after deployment: `E:/CODEX/raw/2026-09-24-订单尺码单价部署核验.md`

**Interfaces:**
- Consumes: all completed pricing tasks.
- Produces: verified build, regression evidence, operator handoff, and deployment evidence without secrets.

- [ ] **Step 1: Run full automated verification**

Run:

```bash
python -m pytest tests -q
node --test web/src/order-pricing.test.js web/src/order-links.test.js
cd web && npm run build
git diff --check
```

Expected: all tests pass, Vite exits `0`, and `git diff --check` prints no errors.

- [ ] **Step 2: Run isolated browser acceptance**

Against a scratch SQLite database, verify as administrator: create one priced and one unpriced size, see partial subtotal, fill the missing price, see complete total, edit to zero, clear back to unpriced, and see audit entries. Verify the order balance and fulfillment interactions still work. Log in as worker and inspect report/order-selection responses and pages for absence of price labels and values.

- [ ] **Step 3: Verify both export variants**

Generate one internal and one customer workbook from the scratch database. Inspect with openpyxl: internal price cells are numeric/formatted and unpriced cells blank; no customer worksheet contains price headers.

- [ ] **Step 4: Update repository documentation and commit**

Document administrator pricing, internal-only export visibility, null semantics, and the migration command in `README.md`.

Commit:

```bash
git add README.md web/dist
git commit -m "docs: describe administrator order pricing"
```

---

### Task 6: Safe Aliyun production deployment

**Files:**
- Deploy: committed application files and `scripts/migration_2026_09_24_order_line_price.sql`
- Update: the Obsidian records listed in Task 5

**Interfaces:**
- Consumes: a clean, pushed commit passing Task 5.
- Produces: migrated production schema and deployed application with a recorded rollback point.

- [ ] **Step 1: Reconcile all three code states before deployment**

Confirm local `main`, GitHub `origin/main`, and `/home/ubuntu/zy-shipping` are clean and identify their exact commits. Stop if the server has unrecorded differences; preserve and reconcile them before deployment.

- [ ] **Step 2: Back up production before migration**

Create a timestamped directory outside the live checkout. Save a PostgreSQL custom-format dump, application archive, upload/data archive, server Git status, and current commit. Verify `pg_restore -l` and archive listings before proceeding.

- [ ] **Step 3: Deploy code and execute migration as PostgreSQL administrator**

Fast-forward the server to the pushed commit. Run:

```bash
sudo -u postgres psql -v ON_ERROR_STOP=1 -d zy_shipping -f scripts/migration_2026_09_24_order_line_price.sql
```

Query `information_schema.columns` and `pg_constraint` to confirm the nullable `NUMERIC(12,2)` field and nonnegative constraint. Confirm existing rows have null prices.

- [ ] **Step 4: Restart and perform production acceptance**

Restart `zy-shipping`; verify `systemctl is-active`, local `/health`, public `/health`, `/app/`, and the new hashed assets. With an administrator test order, verify price entry, partial/complete totals, audit logging, and internal export. With a worker account verify price absence; inspect a customer export for price absence. Do not modify unrelated business data.

- [ ] **Step 5: Record deployment and validate the knowledge base**

Create the dated raw evidence file once, update the shared status and changelog with commits, backup path, migration result, tests, acceptance limits, and rollback point, then run:

```bash
python E:\CODEX\scripts\lint-wiki.py
```

Expected: `LINT OK` with no secrets in the records.
