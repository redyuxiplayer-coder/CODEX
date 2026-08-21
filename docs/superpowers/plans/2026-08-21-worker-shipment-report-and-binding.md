# 员工发货上报与历史订单绑定实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成员工发货日期、订单筛选和物流必填优化，统一发货明细订单显示，并安全修复能够唯一匹配正式订单的历史未绑定发货行。

**Architecture:** 保留 FastAPI + SQLAlchemy + Jinja2 手机端结构，在 `PackingDraft` 保存发货方式、包裹件数和重量，由草稿提交事务统一创建或复用 `WaybillRecord`。历史修复使用独立的“默认预览、显式应用”脚本，通过现有产品别名规范化后只绑定唯一候选，并重建受影响订单流水；有歧义的数据保持不动。

**Tech Stack:** Python 3、FastAPI、SQLAlchemy、Jinja2、原生 JavaScript、Vue 3、PostgreSQL/SQLite、pytest、Vite。

## Global Constraints

- 生产真源是腾讯云本机 PostgreSQL `zy_shipping`，不得通过 Supabase 读写或覆盖生产数据。
- 上线前必须停止 `zy-shipping`、备份 PostgreSQL 和照片目录，迁移与数据修复成功后再重启。
- 发货日期必填、默认今天、不得晚于服务器当前日期；员工只能修改自己的未提交草稿。
- 一张草稿只能对应一张有效且未归档的正式订单。
- 发货方式只能是 `courier` 或 `huolala`；两者都必须填写大于 0 的包裹件数和总重量。
- 快递必须填写真实运单号；货拉拉新车次格式固定为 `货拉拉-YYYYMMDD-NNN`。
- 相同物流识别号必须复用一条 `WaybillRecord`，且公司、日期、件数、重量必须一致。
- 客户版导出结构保持不变；内部导出的“快递记录”继续直接读取 `waybill_records`。
- 历史自动绑定只处理已审核、当前未绑定且规范化后恰好一个候选订单行的数据；0 个或多个候选均不得修改。
- 图一的订单信息统一只在“订单号/下单日期”列逐尺码展示，尺码列不再按是否跨订单重复显示。

---

### Task 1: 草稿物流字段、校验和单事务提交

**Files:**
- Modify: `app/models.py`
- Modify: `app/db.py`
- Modify: `app/services/shipments.py`
- Modify: `app/services/packing_drafts.py`
- Create: `scripts/migration_2026_08_21_packing_logistics.sql`
- Test: `tests/test_packing_drafts.py`
- Test: `tests/test_waybill_no.py`

**Interfaces:**
- Produces: `PackingDraft.shipping_method: str`, `PackingDraft.package_count: int`, `PackingDraft.weight_kg: float`。
- Produces: `validate_shipping_details(...) -> tuple[str, str, int, float]`，返回规范化后的方式、识别号、件数和重量。
- Produces: `submit_shipment_report(..., commit: bool = True)`，默认行为不变；草稿提交传 `commit=False`。
- Produces: `matching_waybill_or_none(...) -> WaybillRecord | None`，存在时严格核对公司、日期、件数、重量。

- [ ] **Step 1: 写字段、日期、物流和事务失败测试**

```python
def test_create_draft_rejects_future_date_without_persisting(db_session, monkeypatch):
    with pytest.raises(ValueError, match="发货日期不能晚于今天"):
        create_packing_draft(..., pack_date="2099-01-01", shipping_method="courier", waybill_no="YT-1", package_count=1, weight_kg=2.5)
    assert db_session.query(PackingDraft).count() == 0

def test_submit_two_drafts_reuses_one_waybill(db_session):
    first = create_packing_draft(..., shipping_method="courier", waybill_no="YT-1", package_count=2, weight_kg=10)
    second = create_packing_draft(..., shipping_method="courier", waybill_no="YT-1", package_count=2, weight_kg=10)
    first_report = submit_packing_draft(db_session, first.id, worker.id)
    second_report = submit_packing_draft(db_session, second.id, worker.id)
    assert first_report.waybill_id == second_report.waybill_id
    assert db_session.query(WaybillRecord).count() == 1

def test_waybill_conflict_does_not_create_partial_report(db_session):
    draft = create_packing_draft(..., shipping_method="courier", waybill_no="YT-1", package_count=3, weight_kg=10)
    with pytest.raises(ValueError, match="包裹件数"):
        submit_packing_draft(db_session, draft.id, worker.id)
    assert draft.submitted_report_id is None
    assert db_session.query(ShipmentReport).count() == 0
```

- [ ] **Step 2: 运行定向测试并确认因缺少字段/校验失败**

Run: `python -m pytest tests/test_packing_drafts.py tests/test_waybill_no.py -q`

Expected: FAIL，失败原因是新参数、字段或校验尚不存在。

- [ ] **Step 3: 添加模型和幂等结构迁移**

```python
shipping_method: Mapped[str] = mapped_column(String(20), default="", server_default="")
package_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
weight_kg: Mapped[float] = mapped_column(Float, default=0, server_default="0")
```

`ensure_schema_updates()` 与 PostgreSQL SQL 同时补齐三列，SQL 使用 `ADD COLUMN IF NOT EXISTS`。

- [ ] **Step 4: 实现服务端规范化与冲突校验**

```python
def validate_shipping_details(session, *, shipping_method, company_name, ship_date, waybill_no, package_count, weight_kg):
    # parse YYYY-MM-DD; reject blank/invalid/future
    # require courier|huolala, positive integer count and positive float weight
    # require a non-empty identifier; verify matching drafts and WaybillRecord metadata
    return method, normalized_waybill, count, weight
```

新建货拉拉草稿先 `flush()` 得到草稿 ID，再生成：

```python
draft.waybill_no = f"货拉拉-{pack_date.replace('-', '')}-{draft.id:03d}"
```

- [ ] **Step 5: 让正式发货与物流关联在一个外层事务内完成**

```python
report = submit_shipment_report(..., commit=False)
waybill = get_or_create_matching_waybill(...)
report.waybill_id = waybill.id
draft.submitted_report_id = report.id
session.commit()
```

任何异常先 `session.rollback()` 再抛出，不能留下正式发货或重复物流记录。

- [ ] **Step 6: 运行定向测试直至通过**

Run: `python -m pytest tests/test_packing_drafts.py tests/test_waybill_no.py -q`

Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add app/models.py app/db.py app/services/shipments.py app/services/packing_drafts.py scripts/migration_2026_08_21_packing_logistics.sql tests/test_packing_drafts.py tests/test_waybill_no.py
git commit -m "feat: validate draft logistics and link waybills"
```

### Task 2: 员工页面日期、订单筛选和物流交互

**Files:**
- Modify: `app/main.py`
- Modify: `app/templates/mobile/report.html`
- Modify: `app/static/app.js`
- Modify: `app/static/app.css`
- Test: `tests/test_pages.py`
- Test: `tests/test_shipment_order_binding.py`
- Test: `tests/test_mobile_upload_script.py`

**Interfaces:**
- Consumes: Task 1 的新草稿字段和服务参数。
- Produces: `formal_order_options_payload()` 每项新增 `remaining_summary`。
- Produces: `/mobile/report` 返回员工全部未提交草稿和同公司同日期可复用的货拉拉车次。

- [ ] **Step 1: 写页面和路由失败测试**

```python
def test_mobile_report_shows_editable_required_date_and_all_open_drafts(db_session):
    page = client.get("/mobile/report")
    assert 'name="pack_date"' in page.text
    assert 'type="date"' in page.text
    assert 'max="' in page.text
    assert old_draft.package_no in page.text

def test_order_option_contains_remaining_summary(db_session):
    option = formal_order_options_payload(db_session)[0]
    assert option["remaining_summary"] == "L98 / XL63"

def test_mobile_new_requires_complete_logistics(db_session):
    response = client.post("/mobile/today/new", data={...})
    assert response.status_code == 400
    assert response.json()["detail"] == "请选择发货方式"
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest tests/test_pages.py tests/test_shipment_order_binding.py tests/test_mobile_upload_script.py -q`

Expected: FAIL，页面仍为隐藏日期和单一长订单下拉框。

- [ ] **Step 3: 扩展订单候选摘要和草稿查询**

```python
option["remaining_summary"] = " / ".join(
    f"{line['size']}{line['remaining']}" for line in lines if line["remaining"] > 0
) or "已发完"
```

`/mobile/report` 去掉 `PackingDraft.pack_date == today`，保留用户和未提交条件以及原倒序。

- [ ] **Step 4: 修改路由表单参数**

新建和修改路由接收并传递：

```python
shipping_method: str = Form("")
package_count: str = Form("")
weight_kg: str = Form("")
pack_date: str = Form("")
```

更新草稿也必须传 `pack_date`；服务端负责最终校验。

- [ ] **Step 5: 实现公司、款式/颜色、订单号组合筛选**

模板为每个订单 option 提供 `data-company`、`data-style-color`、`data-search`，JavaScript 在浏览器端过滤：

```javascript
const visible = (!company || option.dataset.company === company)
  && (!styleColor || option.dataset.styleColor === styleColor)
  && (!query || option.dataset.search.toLowerCase().includes(query.toLowerCase()));
option.hidden = !visible;
```

候选文字固定为：`订单号｜下单日期｜颜色｜还差摘要`。

- [ ] **Step 6: 实现快递/货拉拉表单**

快递显示必填运单号；货拉拉提供“新建车次/已有车次”。两种方式均提供：

```html
<input name="package_count" type="number" min="1" step="1" required>
<input name="weight_kg" type="number" min="0.01" step="0.01" required>
```

已有车次 option 带公司、日期、件数、重量，选中后带出并锁定件数和重量。

- [ ] **Step 7: 扩展浏览器草稿自动保存字段并重置不兼容物流**

`collectReportDraft()`/`restoreReportDraft()` 保存日期、筛选、方式、识别号、件数和重量。日期或公司变化时清空已有物流选择，避免静默沿用。

- [ ] **Step 8: 运行定向测试和前端构建**

Run: `python -m pytest tests/test_pages.py tests/test_shipment_order_binding.py tests/test_mobile_upload_script.py -q`

Run: `npm run build`（目录 `web`）

Expected: PASS；Vite build exit 0。

- [ ] **Step 9: 提交**

```bash
git add app/main.py app/templates/mobile/report.html app/static/app.js app/static/app.css tests/test_pages.py tests/test_shipment_order_binding.py tests/test_mobile_upload_script.py
git commit -m "feat: improve worker shipment report form"
```

### Task 3: 统一发货明细订单显示

**Files:**
- Modify: `web/src/views/Shipments.vue`
- Test: `tests/test_admin_assets.py`
- Test: `tests/test_shipment_order_display.py`

**Interfaces:**
- Consumes: `_report_dict()` 已有逐行 `order_label`、`order_line_id`。
- Produces: 尺码列只显示尺码、数量和客户 SKU；订单列对每一尺码始终显示订单号和下单日期。

- [ ] **Step 1: 写失败测试锁定统一显示**

```python
def test_shipments_vue_does_not_condition_order_identity_on_multiple_orders():
    source = Path("web/src/views/Shipments.vue").read_text(encoding="utf-8")
    assert "row.has_multiple_orders && l.system_order_no" not in source
    assert "{{ l.order_label }}" in source
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest tests/test_admin_assets.py tests/test_shipment_order_display.py -q`

Expected: FAIL，源码仍含 `row.has_multiple_orders` 条件。

- [ ] **Step 3: 删除尺码列的条件重复信息，保留订单列逐行链接**

```vue
<div v-for="l in row.lines" :key="l.id || `${l.size}-${l.order_line_id || 'unbound'}`">
  {{ l.size }} {{ l.quantity }}<span v-if="l.customer_sku"> · {{ l.customer_sku }}</span>
</div>
```

订单列继续为每行显示 `l.order_label`，未绑定显示红色“未绑定订单”。

- [ ] **Step 4: 运行测试和构建**

Run: `python -m pytest tests/test_admin_assets.py tests/test_shipment_order_display.py -q`

Run: `npm run build`（目录 `web`）

Expected: PASS；Vite build exit 0。

- [ ] **Step 5: 提交**

```bash
git add web/src/views/Shipments.vue tests/test_admin_assets.py tests/test_shipment_order_display.py
git commit -m "fix: make shipment order display consistent"
```

### Task 4: 唯一候选历史发货绑定修复工具

**Files:**
- Create: `scripts/repair_unique_shipment_order_bindings.py`
- Create: `tests/test_repair_unique_shipment_bindings.py`
- Modify: `scripts/audit_orders.sql`

**Interfaces:**
- Produces: `classify_unbound_lines(session) -> dict`，包含 `unique`、`ambiguous`、`unmatched` 明细。
- Produces: `apply_unique_bindings(session) -> dict`，只应用 `unique`，设置可安全确定的 `ShipmentReport.order_id`，重建受影响订单流水。
- CLI: `--database` 或 `--database-url-env` 二选一；默认 `--preview <json>`，执行必须显式 `--apply --audit <json>`。

- [ ] **Step 1: 写唯一、歧义、无候选和幂等失败测试**

```python
def test_preview_classifies_canonical_alias_unique_candidate(db_session):
    result = classify_unbound_lines(db_session)
    assert result["summary"] == {"unique": 1, "ambiguous": 0, "unmatched": 0}
    assert result["unique"][0]["system_order_no"] == "ZP-00015-PJJM"

def test_apply_only_unique_and_is_idempotent(db_session):
    first = apply_unique_bindings(db_session)
    second = apply_unique_bindings(db_session)
    assert first["bound_line_count"] == 1
    assert second["bound_line_count"] == 0

def test_apply_leaves_ambiguous_and_unmatched_unbound(db_session):
    apply_unique_bindings(db_session)
    assert ambiguous_line.order_line_id is None
    assert unmatched_line.order_line_id is None
```

- [ ] **Step 2: 运行新测试确认 RED**

Run: `python -m pytest tests/test_repair_unique_shipment_bindings.py -q`

Expected: ERROR/FAIL，因为修复模块尚不存在。

- [ ] **Step 3: 实现规范化候选分类**

仅查询 `ShipmentReport.status in APPROVED_STATUSES` 且 `ShipmentLine.order_line_id IS NULL`。报告和订单行都调用：

```python
canonical_item(session, company_name, product_name, style_name)
```

候选键固定为 `(company_name, canonical_product, canonical_style, size)`，订单行必须 `is_active=True`、`order_id IS NOT NULL` 且所属正式订单 `status='active'`。

- [ ] **Step 4: 实现只应用唯一候选和报告头修复**

```python
for item in classification["unique"]:
    session.get(ShipmentLine, item["shipment_line_id"]).order_line_id = item["order_line_id"]

for report in affected_reports:
    order_ids = {line.order_line.order_id for line in report.lines if line.order_line_id}
    report.order_id = next(iter(order_ids)) if len(order_ids) == 1 and all(line.order_line_id for line in report.lines) else None
```

提交绑定后，对受影响 `order_line_id` 调用 `recompute_order_ledger()`；审计记录绑定前后数量、候选订单号、仍歧义和无候选明细。

- [ ] **Step 5: 扩展 SQL 审计并运行测试**

Run: `python -m pytest tests/test_repair_unique_shipment_bindings.py tests/test_ledger.py tests/test_shipment_order_display.py -q`

Expected: PASS。

- [ ] **Step 6: 本地 SQLite 演练两次验证幂等**

```bash
python scripts/repair_unique_shipment_order_bindings.py --database tmp/repair-binding.sqlite --preview tmp/repair-preview.json
python scripts/repair_unique_shipment_order_bindings.py --database tmp/repair-binding.sqlite --apply --audit tmp/repair-audit.json
python scripts/repair_unique_shipment_order_bindings.py --database tmp/repair-binding.sqlite --apply --audit tmp/repair-audit-second.json
```

Expected: 第二次 `bound_line_count` 为 `0`。

- [ ] **Step 7: 提交**

```bash
git add scripts/repair_unique_shipment_order_bindings.py scripts/audit_orders.sql tests/test_repair_unique_shipment_bindings.py
git commit -m "fix: bind uniquely matched historical shipments"
```

### Task 5: 全量回归、部署资产和项目记忆

**Files:**
- Modify: `README.md`
- Modify: `E:/CODEX/wiki/发货系统生产架构.md`

**Interfaces:**
- Consumes: Tasks 1-4 全部改动。
- Produces: 可重复执行的生产部署与核验记录；不在仓库或 Obsidian 中保存密码、私钥或数据库连接串。

- [ ] **Step 1: 更新 README 操作说明**

记录员工页面新字段、货拉拉复用规则、历史修复工具的 preview/apply 用法和备份前置条件。

- [ ] **Step 2: 运行完整验证**

Run: `python -m pytest tests -q`

Run: `npm run build`（目录 `web`）

Expected: 全部测试通过，Vite build exit 0。

- [ ] **Step 3: 审查数据库迁移和脚本默认安全性**

确认结构迁移幂等、修复脚本不带 `--apply` 时不写数据、5条歧义生产数据不会自动绑定。

- [ ] **Step 4: 提交文档**

```bash
git add README.md
git commit -m "docs: document worker logistics and binding repair"
```

- [ ] **Step 5: 合并并推送前复核**

检查完整分支差异、全量测试结果、前端构建和生产部署清单；经代码复核无阻断问题后合并到 `main` 并推送。

- [ ] **Step 6: 生产备份、迁移、修复和部署**

按 `E:/CODEX/wiki/发货系统生产架构.md` 顺序：停止服务、备份数据库和照片、运行结构迁移、先 preview 核对 `105 unique / 5 ambiguous / 0 unmatched`，再 apply、部署代码、重启服务。

- [ ] **Step 7: 生产核验**

检查 `/health`、`/mobile/report`、`/app/shipments`；确认图二张鹏啤酒节四行已关联 `ZP-00015-PJJM`，105条唯一项消失，5条歧义仍保持未绑定；抽查订单余额与部署前一致，内部导出快递页无重复物流行。

- [ ] **Step 8: 更新 Obsidian 活化记忆并 lint**

在 `E:/CODEX/wiki/发货系统生产架构.md` 记录生产版本、备份、迁移数量和核验结果，然后运行：

```bash
python E:/CODEX/scripts/lint-wiki.py
```

Expected: 0 errors。
