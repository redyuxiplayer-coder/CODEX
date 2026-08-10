# Export Order Date and Number Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every customer and internal export sheet retains or gains an “订单” column containing the formal system order number and adds an adjacent “下单时间” column.

**Architecture:** Extend the order-balance projection with formal-order identity while preserving legacy allocation keys, then make the shared Excel sheet builders consume the new fields. Shipment exports resolve the formal order per shipment line first and fall back to the report-level order so cross-order reports remain correct.

**Tech Stack:** Python 3, SQLAlchemy ORM, openpyxl, pytest

## Global Constraints

- Existing “订单” columns remain in their current positions; sheets without one gain it.
- “订单” values are `SalesOrder.system_order_no`, for example `ZP-00005-CPLY`.
- “下单时间” is placed immediately after “订单” and uses `SalesOrder.order_date`.
- Rows without a formal-order binding leave both fields empty; no style-based guessing or history backfill.
- Existing quantity, shipment detail, waybill, SKU, and customer-SKU behavior must not change.
- No database schema change and no production deployment are part of this plan.

---

### Task 1: Expose Formal Order Identity in Balance Rows

**Files:**
- Modify: `tests/test_customer_export.py`
- Modify: `app/services/orders.py:1-16,271-397`

**Interfaces:**
- Consumes: `OrderLine.order_id -> SalesOrder.id` from the existing formal-order schema.
- Produces: `get_order_balances(...) -> list[dict]` rows containing `system_order_no: str` and `formal_order_date: str` in addition to the existing allocation fields.

- [ ] **Step 1: Add a formal-order export fixture and a failing balance projection test**

Replace the legacy `_setup` order construction in `tests/test_customer_export.py` with a formal order and return both the order and its first line:

```python
from app.models import Company, ShipmentLine, ShipmentReport, Spu, User, WaybillRecord
from app.services.sales_orders import create_sales_order


def _setup(db_session):
    admin = User(username="export_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    company = Company(name="广东茉莉", code="ML", next_order_sequence=1)
    spu = Spu(code="CPYL", product_name="裁判", style_name="圆领裁判")
    db_session.add_all([admin, company, spu])
    db_session.commit()
    formal_order = create_sales_order(
        db_session,
        company.id,
        spu.id,
        "",
        "",
        "2026-05-22",
        [{"size": "M", "quantity": 100, "customer_sku": ""}],
    )
    order_line = formal_order.lines[0]
    report = ShipmentReport(
        user_id=admin.id,
        order_id=formal_order.id,
        ship_date="2026-07-17",
        company_name="广东茉莉",
        product_name="裁判",
        style_name="圆领裁判",
        status="auto_approved",
    )
    db_session.add(report)
    db_session.flush()
    db_session.add(ShipmentLine(report_id=report.id, order_line_id=order_line.id, size="M", quantity=50))
    db_session.commit()
    waybill = create_waybill_record(db_session, admin.id, "广东茉莉", "2026-07-17", "800209579798", weight_kg=262.3, package_count=9)
    link_reports_to_waybill(db_session, waybill.id, [report.id])
    return formal_order, order_line
```

Add this test:

```python
def test_balance_projection_exposes_formal_order_number_and_date(db_session):
    from app.services.orders import get_order_balances

    formal_order, _order_line = _setup(db_session)

    row = get_order_balances(db_session, company_name="广东茉莉")[0]

    assert row["system_order_no"] == formal_order.system_order_no
    assert row["formal_order_date"] == "2026-05-22"
```

- [ ] **Step 2: Run the focused test and verify the RED state**

Run:

```powershell
python -m pytest tests/test_customer_export.py::test_balance_projection_exposes_formal_order_number_and_date -q
```

Expected: FAIL with `KeyError: 'system_order_no'` because balance rows do not yet project formal-order fields.

- [ ] **Step 3: Add the formal-order outer join and projection**

In `app/services/orders.py`, import `SalesOrder` and extend `order_query`:

```python
from app.models import (
    Company,
    OrderAdjustment,
    OrderLine,
    OrderLineClose,
    ReturnRework,
    SalesOrder,
    ShipmentLine,
    ShipmentReport,
    User,
)
```

Add the two labeled columns and outer join without changing the existing `OrderLine.order_date` field used by allocation and sorting:

```python
SalesOrder.system_order_no.label("system_order_no"),
SalesOrder.order_date.label("formal_order_date"),
```

```python
.join(Company, Company.id == OrderLine.company_id)
.outerjoin(SalesOrder, SalesOrder.id == OrderLine.order_id)
```

Add both fields to the initial merged balance dictionary:

```python
"system_order_no": row.system_order_no or "",
"formal_order_date": row.formal_order_date or "",
```

Do not replace `order_ref`, `order_date`, the merge key, or allocation logic; they remain internal compatibility fields.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```powershell
python -m pytest tests/test_customer_export.py::test_balance_projection_exposes_formal_order_number_and_date -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit the balance projection change**

```powershell
git add app/services/orders.py tests/test_customer_export.py
git commit -m "feat: expose formal order fields in balances"
```

---

### Task 2: Update Customer and Internal Export Columns

**Files:**
- Modify: `tests/test_customer_export.py`
- Modify: `app/services/exports.py:180-330`

**Interfaces:**
- Consumes: `system_order_no` and `formal_order_date` from Task 1 balance rows.
- Produces: all balance sheets with adjacent `订单` and `下单时间` columns; shipment sheets resolve `SalesOrder` per shipment line.

- [ ] **Step 1: Write failing assertions for all shared export sheet types**

Update the customer export assertions so the main and detail sheets require the confirmed column names and values:

```python
formal_order, _order_line = _setup(db_session)
export_customer_company_workbook(db_session, "广东茉莉", output)

main = wb["客户发货明细"]
headers = [cell.value for cell in main[1]]
assert headers[:6] == ["公司", "产品", "款式", "订单", "下单时间", "尺码"]
main_row = [cell.value for cell in main[2]]
assert main_row[3:5] == [formal_order.system_order_no, "2026-05-22"]

detail = wb["发货明细"]
detail_headers = [cell.value for cell in detail[1]]
assert detail_headers[7:9] == ["订单", "下单时间"]
detail_row = [cell.value for cell in detail[2]]
assert detail_row[7:9] == [formal_order.system_order_no, "2026-05-22"]
```

Update the internal export test:

```python
formal_order, _order_line = _setup(db_session)
export_company_workbook(db_session, "广东茉莉", output)

main = wb["订单发货明细"]
main_headers = [cell.value for cell in main[1]]
assert main_headers[:6] == ["公司", "产品", "款式", "订单", "下单时间", "尺码"]
main_row = [cell.value for cell in main[2]]
assert main_row[3:5] == [formal_order.system_order_no, "2026-05-22"]

shipments = wb["发货流水"]
shipment_headers = [cell.value for cell in shipments[1]]
order_index = shipment_headers.index("订单")
assert shipment_headers[order_index + 1] == "下单时间"
shipment_row = [cell.value for cell in shipments[2]]
assert shipment_row[order_index:order_index + 2] == [formal_order.system_order_no, "2026-05-22"]
```

Add coverage for both total-export `未发货明细` sheets:

```python
def test_total_exports_keep_order_and_add_order_time_on_unshipped_sheets(db_session, tmp_path: Path):
    from app.services.exports import export_customer_total_workbook, export_total_workbook

    formal_order, _order_line = _setup(db_session)
    internal_output = tmp_path / "内部总表.xlsx"
    customer_output = tmp_path / "客户总表.xlsx"

    export_total_workbook(db_session, internal_output)
    export_customer_total_workbook(db_session, customer_output)

    for path in (internal_output, customer_output):
        wb = load_workbook(path)
        ws = wb["未发货明细"]
        headers = [cell.value for cell in ws[1]]
        assert headers[:6] == ["公司", "产品", "款式", "订单", "下单时间", "尺码"]
        row = [cell.value for cell in ws[2]]
        assert row[3:5] == [formal_order.system_order_no, "2026-05-22"]
```

Add the unbound-history requirement before implementation so it fails on the current legacy fallback:

```python
def test_customer_export_leaves_formal_order_fields_blank_when_unbound(db_session, tmp_path: Path):
    from app.services.orders import create_order_line

    create_order_line(db_session, "无绑定公司", "测试产品", "测试款式", "S", 10, order_date="2026-05-01")
    output = tmp_path / "未绑定客户版.xlsx"

    export_customer_company_workbook(db_session, "无绑定公司", output)

    wb = load_workbook(output)
    row = [cell.value for cell in wb["客户发货明细"][2]]
    assert row[3] in (None, "")
    assert row[4] in (None, "")
```

- [ ] **Step 2: Run both export tests and verify the RED state**

Run:

```powershell
python -m pytest tests/test_customer_export.py -q
```

Expected: the new assertions FAIL because balance sheets lack “下单时间”, shipment sheets still use “系统订单号”/“下单日期”, and the old “订单” field exposes a legacy date for an unbound row.

- [ ] **Step 3: Modify the shared balance sheet builders**

In `add_balance_sheet`, keep “订单” in column 4, insert “下单时间” immediately after it, and use the formal fields:

```python
ws.append(["公司", "产品", "款式", "订单", "下单时间", "尺码", "SKU", "发货明细", "下单数量", "已发数量", "未发数量", "超发数量", "快递单号", "客户SKU"])
```

```python
row["company"], row["product"], row["style"], row.get("system_order_no", ""), row.get("formal_order_date", ""),
row["size"], row.get("sku", ""), shipment_details.get(key, ""), row["ordered"], row["shipped"],
row["remaining"], row["over_shipped"], waybill_numbers.get(key, ""), row.get("customer_sku", ""),
```

Apply the same placement to `add_customer_balance_sheet`:

```python
ws.append(["公司", "产品", "款式", "订单", "下单时间", "尺码", "SKU", "下单数量", "已发数量", "未发数量", "快递单号", "客户SKU"])
```

```python
row["company"], row["product"], row["style"], row.get("system_order_no", ""), row.get("formal_order_date", ""),
row["size"], row.get("sku", ""), row["ordered"], row["shipped"], row["remaining"],
waybill_numbers.get(key, ""), row.get("customer_sku", ""),
```

- [ ] **Step 4: Resolve shipment order identity per line and update the headers**

Add this helper above `shipment_rows`:

```python
def _formal_order_for_shipment_line(report: ShipmentReport, line):
    if line.order_line is not None and line.order_line.order is not None:
        return line.order_line.order
    return report.order
```

In both `shipment_rows` and `add_customer_detail_sheet`, move order resolution inside the line loop:

```python
for line in report.lines:
    order = _formal_order_for_shipment_line(report, line)
```

For `add_shipments_sheet`, replace the three identity headers `系统订单号`, `客户订单号`, `下单日期` with this order while retaining customer order data:

```python
"订单", "下单时间", "客户订单号", "颜色", "SPU", "客户SKU",
```

Reorder the corresponding row values to:

```python
order.system_order_no if order else "",
order.order_date if order else "",
order.customer_order_no if order else "",
```

For `add_customer_detail_sheet`, use:

```python
"发货日期", "公司", "产品", "款式", "尺码", "数量", "快递单号",
"订单", "下单时间", "客户订单号", "颜色", "SPU", "客户SKU",
```

and write the same formal-order value order in each detail row.

- [ ] **Step 5: Run the focused export tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_customer_export.py -q
```

Expected: all tests in `tests/test_customer_export.py` PASS.

- [ ] **Step 6: Commit the export column change**

```powershell
git add app/services/exports.py tests/test_customer_export.py
git commit -m "feat: add order date to customer and internal exports"
```

---

### Task 3: Verify Total Exports and Regression Safety

**Files:**
- Modify: `tests/test_customer_export.py`
- Modify: `E:/CODEX/1-项目/仓库系统管理/07-更新日志.md`

**Interfaces:**
- Consumes: completed export behavior from Tasks 1 and 2.
- Produces: full regression evidence and a project maintenance record.

- [ ] **Step 1: Run export and formal-order regression tests**

Run:

```powershell
python -m pytest tests/test_customer_export.py tests/test_shipment_order_display.py tests/test_formal_orders.py tests/test_legacy_order_migration.py -q
```

Expected: all selected tests PASS with no warnings or errors.

- [ ] **Step 2: Run the complete test suite**

Run:

```powershell
python -m pytest -q
```

Expected: all tests PASS with zero failures.

- [ ] **Step 3: Generate and inspect representative workbooks**

Run the two focused export tests without cleanup interruption, open the produced workbooks through the test helpers, and programmatically assert each relevant sheet contains exactly one `订单` header followed immediately by `下单时间`:

```powershell
python -m pytest tests/test_customer_export.py -q
```

Expected checks:

```text
客户发货明细: 订单, 下单时间
发货明细: 订单, 下单时间
订单发货明细: 订单, 下单时间
发货流水: 订单, 下单时间
未绑定正式订单: both cells blank
```

- [ ] **Step 4: Record the completed behavior in the Obsidian project log**

Add under `## 2026-08-10` in `E:/CODEX/1-项目/仓库系统管理/07-更新日志.md`:

```markdown
- 客户版与内部版导出补齐正式订单信息：已有“订单”栏保留，缺少的工作表新增；所有相关明细表在其后增加“下单时间”。订单栏统一显示系统正式订单号，未绑定正式订单的历史行保持空白。
```

Run the required wiki lint:

```powershell
python E:\CODEX\scripts\lint-wiki.py
```

Expected: `LINT OK`.

- [ ] **Step 5: Commit tests and project log**

```powershell
git add tests/test_customer_export.py
git commit -m "test: cover export formal order fields"
```

The Obsidian project log is outside the Git repository and is not included in the commit.
