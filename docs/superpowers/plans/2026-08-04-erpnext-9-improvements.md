# ERPNext 九项改进实施计划

> **For agentic workers:** 按任务顺序执行，每项先写失败测试（RED），再实现（GREEN），全量测试通过后提交。

**Goal:** 为发货系统补齐库存流水、退货返工、订单关闭、盘点调整、SKU/SPU、条码、箱号、沟通记录、运单号九项能力。

**Architecture:** 沿用 FastAPI + SQLAlchemy + Jinja2。新增六张表和五列；余额公式 remaining = ordered − shipped + returned − adjusted − closed；流水表由来源表重建，余额直接算来源表。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, SQLite/PostgreSQL, pytest, Jinja2

## Global Constraints

- TDD：生产代码前必须有失败测试
- 运行命令：`C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -q`
- 改动 `data\` 前运行 `scripts\backup_data.ps1`
- `docs/` 被 gitignore，提交文档用 `git add -f`
- 腾讯云 PostgreSQL 加列需手动 `sudo -u postgres psql -d zy_shipping -c "ALTER TABLE ..."`
- 状态枚举：return status ∈ {pending_rework, reworked, scrapped}；movement_type ∈ {shipped, returned, adjusted, closed}
- 所有新增路由沿用 `require_admin`/`require_user` 鉴权

---

### Task 1: 数据模型与自动迁移

**Files:**
- Modify: `app/models.py`
- Modify: `app/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: 现有 `Base`, `now()`, `ensure_schema_updates`
- Produces: `OrderLedgerEntry`, `ReturnRework`, `ReturnReworkPhoto`, `OrderAdjustment`, `OrderLineClose`, `OrderLineComment`；`OrderLine.sku`, `SkuMapping.barcode`, `PackingDraft.package_no/waybill_no`, `ShipmentReport.waybill_no`

- [ ] **Step 1: 写失败测试**（`tests/test_db.py` 增加）

```python
def test_schema_updates_add_new_columns_and_tables(db_session):
    from sqlalchemy import inspect
    from app.db import engine
    tables = inspect(engine).get_table_names()
    for name in ["order_ledger_entries", "return_reworks", "return_rework_photos", "order_adjustments", "order_line_closes", "order_line_comments"]:
        assert name in tables, name
    cols = {c["name"] for c in inspect(engine).get_columns("order_lines")}
    assert "sku" in cols
```

注意：该测试需要先注册新表到 `Base.metadata` 才能通过 `create_all`。`ensure_schema_updates` 加列后再验证。

- [ ] **Step 2: 运行验证失败**：`python -m pytest tests/test_db.py -q` → FAIL（表不存在）
- [ ] **Step 3: 实现模型**：在 `app/models.py` 添加上述六张表；`OrderLine` 加 `sku`，`SkuMapping` 加 `barcode`，`PackingDraft` 加 `package_no/waybill_no`，`ShipmentReport` 加 `waybill_no`
- [ ] **Step 4: 实现迁移**：`app/db.py` 的 `ensure_schema_updates` 为五个新列加 `ALTER TABLE ... ADD COLUMN`（参照现有 work_info_lines 模式）
- [ ] **Step 5: 验证通过**：`python -m pytest tests/test_db.py -q` → PASS；全量 `python -m pytest -q`
- [ ] **Step 6: 提交**：`git add -A && git commit -m "feat: add ledger/return/adjust/close/comment models and migrations"`

### Task 2: 余额公式与流水重建（服务层）

**Files:**
- Modify: `app/services/orders.py`
- Create: `app/services/ledger.py`
- Test: `tests/test_ledger.py`

**Interfaces:**
- Produces: `recompute_order_ledger(session, order_line_id)`；`get_order_balances` 每行增加 `returned/adjusted/closed`

- [ ] **Step 1: 写失败测试** `tests/test_ledger.py`：

```python
def test_balance_formula_with_return_adjust_close(db_session):
    from app.models import OrderLine, ReturnRework, OrderAdjustment, OrderLineClose
    from app.services.orders import create_order_line, get_order_balances
    from app.services.ledger import recompute_order_ledger
    order = create_order_line(db_session, "源兴发", "裁判", "圆领裁判", "M", 100)
    db_session.add(ReturnRework(order_line_id=order.id, quantity=5, reason="返工", status="pending_rework"))
    db_session.add(OrderAdjustment(order_line_id=order.id, quantity=1, reason="报废"))
    db_session.add(OrderLineClose(order_line_id=order.id, quantity=2, reason="客户不要"))
    db_session.commit()
    recompute_order_ledger(db_session, order.id)
    row = get_order_balances(db_session)[0]
    assert row["returned"] == 5 and row["adjusted"] == 1 and row["closed"] == 2
    assert row["remaining"] == 100 - 0 + 5 - 1 - 2
```

- [ ] **Step 2: 验证失败**：`python -m pytest tests/test_ledger.py -q` → FAIL（returned 字段不存在）
- [ ] **Step 3: 实现 `app/services/ledger.py`**：`recompute_order_ledger` 删除旧流水并按来源表重建（shipped←approved ShipmentLine、returned←ReturnRework、adjusted←OrderAdjustment+scrapped ReturnRework、closed←OrderLineClose）
- [ ] **Step 4: 修改 `get_order_balances`**：每行按 `order_ids` 汇总 returned/adjusted/closed，`remaining = ordered - shipped + returned - adjusted - closed`
- [ ] **Step 5: 验证通过** + 全量测试
- [ ] **Step 6: 提交**

### Task 3: 退货/返工服务与路由

**Files:**
- Create: `app/services/returns.py`
- Modify: `app/main.py`
- Test: `tests/test_returns.py`

**Interfaces:**
- Produces: `create_return_rework(session, order_line_id, user_id, quantity, reason_type, reason, status, photo_paths)`；`set_return_rework_status(...)`；`list_return_reworks(session, order_line_id)`；POST `/admin/order-lines/{line_id}/returns`

测试：创建返工记录后余额 +qty、流水出现 returned 条目；状态改为 scrapped 后额外出现 adjusted 条目；照片可上传并可访问。

### Task 4: 调整与关闭服务及路由

**Files:**
- Create: `app/services/adjustments.py`（含 closes）
- Modify: `app/main.py`
- Test: `tests/test_adjustments.py`

测试：新增调整后余额 −qty；新增关闭后余额 −qty 且 `_matches_order_status` 的 need 过滤不再包含该行。

### Task 5: 订单行详情页 UI

**Files:**
- Create: `app/templates/admin/order_line.html`
- Modify: `app/templates/admin/orders.html`, `app/main.py`, `app/static/app.css`

页面显示订单信息、已发记录、流水、返工/调整/关闭/沟通记录与新增表单。订单查询页每行加「处理」链接。

测试：登录 admin 后 GET `/admin/order-lines/{id}` 200 且包含「订单流水」「退货/返工」文案；POST 各表单 303。

### Task 6: SKU/SPU 与条码

**Files:**
- Modify: `app/services/orders.py`, `app/services/skus.py`, `app/main.py`
- Create: `app/templates/admin/skus.html`
- Modify: `app/templates/mobile/report.html`, `app/static/app.js`

测试：创建订单自动写 sku；batch-update 同步 sku；`/mobile/report/scan?code=` 返回公司/产品/款式；`/admin/skus` 页可编辑条码。

### Task 7: 箱号自动编号与装箱单打印

**Files:**
- Modify: `app/services/packing_drafts.py`, `app/main.py`
- Create: `app/templates/admin/packing_print.html`, `app/templates/mobile/packing_print.html`
- Modify: `app/templates/mobile/report.html`

测试：新建草稿自动生成 `PKG-YYYYMMDD-001`；打印页 200 且包含箱号。

### Task 8: 订单行沟通记录

**Files:**
- Modify: `app/services/ledger.py` 或新建 `app/services/comments.py`, `app/main.py`
- Modify: `app/templates/admin/order_line.html`

测试：POST 新增评论后详情页显示。

### Task 9: 运单号

**Files:**
- Modify: `app/main.py`, `app/services/packing_drafts.py`
- Modify: `app/templates/mobile/report.html`, `app/templates/mobile/my_reports_items.html`, `app/templates/admin/shipments.html`

测试：草稿提交后运单号复制到发货单；发货明细可按运单号筛选；admin 可修改运单号。

### Task 10: 全量验证、本地运行、更新日志

- [ ] 全量 `python -m pytest -q` 通过
- [ ] `scripts\backup_data.ps1` 备份后启动 `uvicorn app.main:app --port 8000`，人工过一遍关键页面
- [ ] 更新 `E:\CODEX\1-项目\仓库系统管理\07-更新日志.md`
- [ ] 提交并提示用户部署（含 PostgreSQL 手动 ALTER SQL）
