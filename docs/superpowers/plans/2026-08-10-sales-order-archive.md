# 正式订单归档实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增可审计、可恢复的正式订单独立归档系统；归档订单不再提供给员工新建发货，但历史、导出和管理端查询完整保留，并首次批量归档当前已发完订单。

**Architecture:** 新建 `sales_order_archives` 历史表，以“存在 `restored_at IS NULL` 的记录”表示当前归档。归档服务集中负责余额校验、归档/恢复和批量状态查询；员工端候选数据和发货提交在服务端过滤/拒绝，管理端通过 API 和 Vue 页面操作。生产首次归档使用复用同一服务的预览/应用脚本。

**Tech Stack:** FastAPI、SQLAlchemy、PostgreSQL、SQLite 测试、Vue 3、Element Plus、pytest、Vite。

## Global Constraints

- 归档采用独立表，不修改 `sales_orders.status`，也不停用 `order_lines`。
- 只有管理员可以归档和恢复。
- 订单所有尺码剩余数量都 `<= 0` 才能归档；超发允许归档。
- 归档只影响员工订单列表、新建发货候选和新发货绑定。
- 历史发货、照片、快递、订单详情、内部版导出和客户版导出不得过滤或改写。
- 恢复必须保留历史归档记录；不自动归档、不自动恢复。
- 生产数据库是腾讯云本机 PostgreSQL，部署不经过 Supabase。
- 所有实现遵循 TDD；每个任务先看到目标测试失败，再写最小实现并提交。

---

## 文件结构

- 新建 `app/services/order_archives.py`：归档状态、完成条件、归档、恢复、员工可见余额过滤的唯一业务入口。
- 修改 `app/models.py`：只定义 `SalesOrderArchive` 数据模型及关系。
- 新建 `scripts/migration_2026_08_10_sales_order_archives.sql`：生产 PostgreSQL 幂等建表/索引。
- 新建 `scripts/archive_completed_sales_orders.py`：首次批量归档预览与 `--apply`。
- 修改 `app/api_v1.py`：管理端归档状态、筛选、归档与恢复接口。
- 修改 `app/services/shipments.py`、`app/main.py`：员工候选过滤与提交防绕过。
- 修改 `web/src/api.js`、`web/src/views/SalesOrders.vue`、`web/src/views/SalesOrderDetail.vue`：管理端交互。
- 重新生成 `web/dist/`：生产静态资源。
- 新建归档专项测试文件，现有导出与同步测试增加不回归断言。

---

### Task 1: 归档数据模型、迁移与本地同步

**Files:**
- Modify: `app/models.py`
- Create: `scripts/migration_2026_08_10_sales_order_archives.sql`
- Modify: `tests/test_db.py`
- Modify: `tests/test_cloud_sync.py`

**Interfaces:**
- Produces: `SalesOrderArchive(order_id, archived_by, archived_at, restored_by, restored_at)`。
- Produces: PostgreSQL 表 `sales_order_archives`，供 Task 2 服务层使用。

- [ ] **Step 1: 写失败的模型与同步测试**

```python
def test_sales_order_archive_schema_tracks_restore_history(db_session):
    archive = SalesOrderArchive(order_id=1, archived_by=2)
    db_session.add(archive)
    db_session.flush()
    assert archive.restored_at is None
    assert archive.restored_by is None

def test_cloud_sync_copies_sales_order_archives(source_engine, tmp_path):
    # 在源库插入一条归档记录，运行 sync_database 后断言目标 SQLite 同表同值。
    assert report["tables"]["sales_order_archives"]["copied_rows"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_db.py tests/test_cloud_sync.py -q`

Expected: FAIL，原因是 `SalesOrderArchive` 或 `sales_order_archives` 尚不存在。

- [ ] **Step 3: 添加 SQLAlchemy 模型**

在 `app/models.py` 的 `SalesOrder` 之后加入：

```python
class SalesOrderArchive(Base):
    __tablename__ = "sales_order_archives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"), index=True)
    archived_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    archived_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    restored_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    order: Mapped[SalesOrder] = relationship()
    archiver: Mapped[User] = relationship(foreign_keys=[archived_by])
    restorer: Mapped[User | None] = relationship(foreign_keys=[restored_by])
```

新表由 `Base.metadata.create_all()` 自动进入 SQLite 测试和云端快照同步，不把归档状态塞进 `sales_orders`。

- [ ] **Step 4: 添加 PostgreSQL 幂等迁移**

```sql
CREATE TABLE IF NOT EXISTS sales_order_archives (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES sales_orders(id),
    archived_by INTEGER NOT NULL REFERENCES users(id),
    archived_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    restored_by INTEGER REFERENCES users(id),
    restored_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_sales_order_archives_order_id ON sales_order_archives(order_id);
CREATE INDEX IF NOT EXISTS ix_sales_order_archives_archived_at ON sales_order_archives(archived_at);
CREATE INDEX IF NOT EXISTS ix_sales_order_archives_restored_at ON sales_order_archives(restored_at);
```

- [ ] **Step 5: 运行测试并提交**

Run: `python -m pytest tests/test_db.py tests/test_cloud_sync.py -q`

Expected: PASS。

```bash
git add app/models.py scripts/migration_2026_08_10_sales_order_archives.sql tests/test_db.py tests/test_cloud_sync.py
git commit -m "feat: add sales order archive history schema"
```

---

### Task 2: 归档业务服务与完成条件

**Files:**
- Create: `app/services/order_archives.py`
- Create: `tests/test_order_archives.py`

**Interfaces:**
- Consumes: `get_order_balances(session, company_name)`、`SalesOrderArchive`、`OperationLog`。
- Produces: `get_open_archive(session, order_id) -> SalesOrderArchive | None`。
- Produces: `archived_order_ids(session) -> set[int]`。
- Produces: `archive_state(session, order) -> dict`，含 `is_archived`、`can_archive`、`blocking_sizes`、`current_archive`、`history`。
- Produces: `archive_sales_order(session, order_id, admin_id) -> SalesOrderArchive`。
- Produces: `restore_sales_order(session, order_id, admin_id) -> SalesOrderArchive`。

- [ ] **Step 1: 写失败的服务测试**

```python
def test_archive_rejects_order_with_remaining_size(db_session, completed_order, admin):
    completed_order.lines[0].quantity = 100
    with pytest.raises(ValueError, match="S 码还需 100 件"):
        archive_sales_order(db_session, completed_order.id, admin.id)

def test_archive_accepts_exact_and_over_shipped_orders(db_session, completed_order, approved_report, admin):
    archive = archive_sales_order(db_session, completed_order.id, admin.id)
    assert archive.restored_at is None
    assert completed_order.id in archived_order_ids(db_session)

def test_restore_closes_current_record_and_preserves_history(db_session, completed_order, approved_report, admin):
    first = archive_sales_order(db_session, completed_order.id, admin.id)
    restore_sales_order(db_session, completed_order.id, admin.id)
    second = archive_sales_order(db_session, completed_order.id, admin.id)
    assert first.restored_at is not None
    assert second.id != first.id

def test_duplicate_archive_and_restore_without_archive_are_rejected(db_session, completed_order, approved_report, admin):
    archive_sales_order(db_session, completed_order.id, admin.id)
    with pytest.raises(ValueError, match="订单已经归档"):
        archive_sales_order(db_session, completed_order.id, admin.id)
    restore_sales_order(db_session, completed_order.id, admin.id)
    with pytest.raises(ValueError, match="订单尚未归档"):
        restore_sales_order(db_session, completed_order.id, admin.id)

def test_archive_operation_is_logged(db_session, completed_order, approved_report, admin):
    archive_sales_order(db_session, completed_order.id, admin.id)
    log = db_session.query(OperationLog).filter_by(action="archive_sales_order").one()
    assert log.actor_id == admin.id
    assert log.target == completed_order.system_order_no
```

空订单和超发场景分别建立没有有效行、发货量大于下单量的 fixture，断言前者拒绝、后者成功。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_order_archives.py -q`

Expected: FAIL，模块或函数不存在。

- [ ] **Step 3: 实现余额归属和状态查询**

```python
def _order_balance_rows(session: Session, order: SalesOrder) -> list[dict]:
    line_ids = {line.id for line in order.lines if line.is_active}
    return [
        row for row in get_order_balances(session, company_name=order.company.name)
        if line_ids.intersection(int(value) for value in row.get("order_ids", []))
    ]

def get_open_archive(session: Session, order_id: int) -> SalesOrderArchive | None:
    return (
        session.query(SalesOrderArchive)
        .filter_by(order_id=order_id, restored_at=None)
        .order_by(SalesOrderArchive.id.desc())
        .first()
    )
```

`archive_state` 将所有 `remaining > 0` 的行转换为：

```python
{"size": row["size"], "remaining": int(row["remaining"])}
```

如果无有效订单行则 `can_archive=False`；超发行为 `remaining < 0`，不进入阻塞列表。

- [ ] **Step 4: 实现归档与恢复事务**

```python
def archive_sales_order(session: Session, order_id: int, admin_id: int) -> SalesOrderArchive:
    order = session.query(SalesOrder).filter_by(id=order_id).with_for_update().one_or_none()
    if order is None:
        raise ValueError("订单不存在")
    state = archive_state(session, order)
    if state["is_archived"]:
        raise ValueError("订单已经归档")
    if not state["can_archive"]:
        details = "、".join(f'{row["size"]} 码还需 {row["remaining"]} 件' for row in state["blocking_sizes"])
        raise ValueError(f"{details}，不能归档")
    archive = SalesOrderArchive(order_id=order.id, archived_by=admin_id)
    session.add_all([archive, OperationLog(actor_id=admin_id, action="archive_sales_order", target=order.system_order_no, detail="手动归档已发完订单")])
    session.commit()
    session.refresh(archive)
    return archive
```

`restore_sales_order` 锁定当前开放记录，填写 `restored_by`、`restored_at=now()`，写 `restore_sales_order` 操作日志并提交。

- [ ] **Step 5: 运行测试并提交**

Run: `python -m pytest tests/test_order_archives.py -q`

Expected: PASS。

```bash
git add app/services/order_archives.py tests/test_order_archives.py
git commit -m "feat: add manual order archive service"
```

---

### Task 3: 员工端隐藏和发货提交防绕过

**Files:**
- Modify: `app/services/order_archives.py`
- Modify: `app/services/shipments.py`
- Modify: `app/main.py`
- Modify: `tests/test_shipment_order_binding.py`
- Modify: `tests/test_pages.py`

**Interfaces:**
- Produces: `archived_order_line_ids(session) -> set[int]`。
- Produces: `worker_visible_balances(session, company_name=None) -> list[dict]`。
- Consumes: Task 2 的 `get_open_archive`。

- [ ] **Step 1: 写失败的员工端测试**

```python
def test_worker_orders_hide_archived_order(client, archived_completed_order):
    response = client.get("/mobile/orders")
    assert response.status_code == 200
    balance_section = response.text.split("<h2>当前下单 / 已发 / 还差</h2>", 1)[1].split("<h2>最近发货明细</h2>", 1)[0]
    assert archived_completed_order.system_order_no not in balance_section

def test_submit_rejects_archived_selected_order(db_session, archived_completed_order, worker):
    with pytest.raises(ValueError, match="订单已归档，请先恢复"):
        submit_shipment_report(
            db_session, worker.id, "2026-08-10", "", "", "",
            [{"size": "S", "quantity": 1, "order_line_id": archived_completed_order.lines[0].id}],
            order_id=archived_completed_order.id,
        )

def test_resolver_skips_archived_preferred_line(db_session, archived_completed_order):
    line = archived_completed_order.lines[0]
    assert resolve_order_line_id(
        db_session, line.company.name, line.product_name, line.style_name, line.size, preferred=line.id
    ) is None

def test_historical_report_keeps_archived_order_number(client, archived_completed_order):
    response = client.get("/mobile/orders")
    history_section = response.text.split("<h2>最近发货明细</h2>", 1)[1]
    assert archived_completed_order.system_order_no in history_section
```

再建立一个同款未归档订单，断言自动匹配返回该订单行，从而覆盖“跳过归档但保留未归档行为”。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_shipment_order_binding.py tests/test_pages.py -q`

Expected: 至少归档隐藏和提交拒绝测试 FAIL。

- [ ] **Step 3: 实现员工可见余额过滤**

```python
def worker_visible_balances(session: Session, company_name: str | None = None) -> list[dict]:
    hidden_line_ids = archived_order_line_ids(session)
    return [
        row for row in get_order_balances(session, company_name=company_name)
        if not hidden_line_ids.intersection(int(value) for value in row.get("order_ids", []))
    ]
```

只在员工订单页、员工发货提示和员工订单候选使用该函数；管理端余额和导出继续直接调用 `get_order_balances`。

- [ ] **Step 4: 在发货服务做强制校验**

在 `resolve_order_line_id` 中，preferred 行和自动候选都必须确认其正式订单不在 `archived_order_ids(session)`。

在 `submit_shipment_report` 清洗完成后校验：

```python
if selected_order is not None and get_open_archive(session, selected_order.id):
    raise ValueError("订单已归档，请先恢复")
for line in cleaned_lines:
    bound = session.get(OrderLine, line["order_line_id"]) if line.get("order_line_id") else None
    if bound and bound.order_id and get_open_archive(session, bound.order_id):
        raise ValueError("订单已归档，请先恢复")
```

- [ ] **Step 5: 替换员工页面的数据源**

在 `app/main.py` 中将以下员工新发货相关调用改用 `worker_visible_balances`：

- `balances_for_report_hint`
- `active_order_companies`
- 正式订单候选 payload
- 旧式按公司/产品/款式生成的候选
- `/mobile/orders` 的 `all_balances`

不要替换管理员仪表盘、管理员订单余额页和导出入口。

- [ ] **Step 6: 运行测试并提交**

Run: `python -m pytest tests/test_shipment_order_binding.py tests/test_pages.py -q`

Expected: PASS。

```bash
git add app/services/order_archives.py app/services/shipments.py app/main.py tests/test_shipment_order_binding.py tests/test_pages.py
git commit -m "feat: hide archived orders from worker shipping"
```

---

### Task 4: 管理端归档 API 与筛选

**Files:**
- Modify: `app/api_v1.py`
- Create: `tests/test_order_archives_api.py`

**Interfaces:**
- Consumes: Task 2 的 `archive_state`、`archive_sales_order`、`restore_sales_order`、`archived_order_ids`。
- Produces: `GET /api/v1/sales-orders?archive_status=active|archived|all`。
- Produces: `POST /api/v1/sales-orders/{order_id}/archive` 和 `/restore`。

- [ ] **Step 1: 写失败的 API 测试**

```python
def test_admin_can_archive_restore_and_filter(client, completed_order):
    archived = client.post(f"/api/v1/sales-orders/{completed_order.id}/archive")
    assert archived.status_code == 200
    assert archived.json()["is_archived"] is True
    assert completed_order.system_order_no not in [row["system_order_no"] for row in client.get("/api/v1/sales-orders").json()["orders"]]
    assert completed_order.system_order_no in [row["system_order_no"] for row in client.get("/api/v1/sales-orders?archive_status=archived").json()["orders"]]
    restored = client.post(f"/api/v1/sales-orders/{completed_order.id}/restore")
    assert restored.json()["is_archived"] is False

def test_archive_api_rejects_worker_and_unfinished_order(client, worker_client, unfinished_order):
    assert worker_client.post(f"/api/v1/sales-orders/{unfinished_order.id}/archive").status_code == 403
    admin_response = client.post(f"/api/v1/sales-orders/{unfinished_order.id}/archive")
    assert admin_response.status_code == 400
    assert "还需" in admin_response.json()["detail"]

def test_archive_filter_rejects_unknown_value(client):
    assert client.get("/api/v1/sales-orders?archive_status=unknown").status_code == 400
```

恢复后重新读取详情，断言 `history` 同时包含归档时间和恢复时间。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_order_archives_api.py -q`

Expected: 404 或响应缺少归档字段。

- [ ] **Step 3: 扩展订单序列化和列表筛选**

将 `_sales_order_dict` 改为接收可选状态：

```python
def _sales_order_dict(order: SalesOrder, state: dict | None = None) -> dict:
    state = state or {"is_archived": False, "can_archive": False, "blocking_sizes": [], "history": []}
    return {**existing_fields, **state}
```

列表一次查询开放归档订单 ID，按 `archive_status` 过滤后再序列化；详情调用 `archive_state` 返回完整历史。

- [ ] **Step 4: 添加归档与恢复接口**

```python
@router.post("/sales-orders/{order_id}/archive")
def api_archive_sales_order(request: Request, order_id: int, session: Session = Depends(get_session)):
    admin = require_admin(request, session)
    try:
        archive_sales_order(session, order_id, admin.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _sales_order_dict(session.get(SalesOrder, order_id), archive_state(session, session.get(SalesOrder, order_id)))
```

恢复接口使用相同结构调用 `restore_sales_order`。

- [ ] **Step 5: 运行测试并提交**

Run: `python -m pytest tests/test_order_archives_api.py tests/test_formal_orders_api.py -q`

Expected: PASS。

```bash
git add app/api_v1.py tests/test_order_archives_api.py
git commit -m "feat: expose order archive admin APIs"
```

---

### Task 5: 管理端归档界面

**Files:**
- Modify: `web/src/api.js`
- Modify: `web/src/views/SalesOrders.vue`
- Modify: `web/src/views/SalesOrderDetail.vue`
- Modify: `tests/test_admin_assets.py`
- Regenerate: `web/dist/`

**Interfaces:**
- Consumes: Task 4 的列表、归档、恢复接口和 `is_archived/can_archive/blocking_sizes` 字段。
- Produces: 老板端筛选、归档按钮、恢复按钮和归档信息展示。

- [ ] **Step 1: 写失败的静态资源契约测试**

```python
def test_sales_order_pages_include_archive_controls():
    list_source = Path("web/src/views/SalesOrders.vue").read_text(encoding="utf-8")
    detail_source = Path("web/src/views/SalesOrderDetail.vue").read_text(encoding="utf-8")
    assert "archiveStatus" in list_source
    assert "已归档" in list_source
    assert "archiveSalesOrder" in detail_source
    assert "restoreSalesOrder" in detail_source
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_admin_assets.py -q`

Expected: FAIL，页面没有归档控件。

- [ ] **Step 3: 添加前端 API**

```javascript
export function archiveSalesOrder(orderId) {
  return request(`/api/v1/sales-orders/${orderId}/archive`, { method: "POST" });
}
export function restoreSalesOrder(orderId) {
  return request(`/api/v1/sales-orders/${orderId}/restore`, { method: "POST" });
}
```

`fetchSalesOrders` 继续使用 URLSearchParams，因此传入 `archive_status` 即可。

- [ ] **Step 4: 实现列表筛选与详情操作**

列表增加：

```javascript
const archiveStatus = ref("active");
orders.value = (await fetchSalesOrders({ company_id: companyId.value, q: q.value, archive_status: archiveStatus.value })).orders;
```

模板增加“进行中 / 已归档 / 全部”选择器和状态标签。

详情页增加 Element Plus 二次确认：未归档且 `can_archive` 时调用 `archiveSalesOrder`；仍欠货时禁用并显示 `blocking_sizes`；已归档时显示归档人、时间并调用 `restoreSalesOrder`。

- [ ] **Step 5: 构建前端、运行测试并提交**

Run: `npm run build`（工作目录 `web`）

Expected: Vite build exit 0，`web/dist/index.html` 引用新 hash 资源。

Run: `python -m pytest tests/test_admin_assets.py tests/test_order_archives_api.py -q`

Expected: PASS。

```bash
git add web/src/api.js web/src/views/SalesOrders.vue web/src/views/SalesOrderDetail.vue web/dist tests/test_admin_assets.py
git commit -m "feat: add order archive controls"
```

---

### Task 6: 导出不回归与首次批量归档脚本

**Files:**
- Create: `scripts/archive_completed_sales_orders.py`
- Create: `tests/test_archive_completed_sales_orders.py`
- Modify: `tests/test_customer_export.py`

**Interfaces:**
- Consumes: Task 2 的 `archive_state` 和 `archive_sales_order`。
- Produces: `python scripts/archive_completed_sales_orders.py --admin-username "$archive_admin_username"` 只读预览。
- Produces: 加 `--apply` 后执行归档。

- [ ] **Step 1: 写失败的脚本和导出测试**

```python
def test_archive_script_preview_does_not_write(db_session, completed_order):
    result = collect_archive_candidates(db_session)
    assert result == [completed_order]
    assert db_session.query(SalesOrderArchive).count() == 0

def test_customer_and_internal_exports_keep_archived_order(db_session, archived_order, tmp_path):
    internal = export_total_workbook(db_session, tmp_path / "internal.xlsx")
    customer = export_customer_total_workbook(db_session, tmp_path / "customer.xlsx")
    assert archived_order.system_order_no in workbook_values(internal)
    assert archived_order.system_order_no in workbook_values(customer)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_archive_completed_sales_orders.py tests/test_customer_export.py -q`

Expected: 脚本模块不存在或候选函数不存在。

- [ ] **Step 3: 实现预览/应用脚本**

脚本接口：

```python
def collect_archive_candidates(session: Session) -> list[SalesOrder]:
    return [order for order in session.query(SalesOrder).order_by(SalesOrder.company_id, SalesOrder.company_sequence) if archive_state(session, order)["can_archive"] and not archive_state(session, order)["is_archived"]]
```

命令行规则：

- `--admin-username` 必填，必须对应 active admin。
- 默认打印候选数量、订单号、下单日期，不写数据库。
- 只有 `--apply` 才逐张调用 `archive_sales_order`。
- 应用结束重新查询，若任一候选仍未归档则退出码 1。
- 不在脚本中保存密码、SSH 信息或数据库连接串。

- [ ] **Step 4: 运行专项与完整测试**

Run: `python -m pytest tests/test_archive_completed_sales_orders.py tests/test_customer_export.py -q`

Expected: PASS。

Run: `python -m pytest -q`

Expected: 全部测试通过，0 failures。

- [ ] **Step 5: 提交**

```bash
git add scripts/archive_completed_sales_orders.py tests/test_archive_completed_sales_orders.py tests/test_customer_export.py
git commit -m "feat: add completed order archive rollout"
```

---

### Task 7: 代码审查、生产部署和首次归档

**Files:**
- Modify after verification: `E:/CODEX/raw/2026-08-10-发货系统订单归档上线核验.md`
- Modify after verification: `E:/CODEX/wiki/发货系统生产架构.md`

**Interfaces:**
- Consumes: 所有前序任务。
- Produces: 腾讯云生产部署、首次归档结果、可恢复备份和知识库记录。

- [ ] **Step 1: 审查变更和再次验证**

Run: `base_commit="$(git merge-base HEAD main)"; git diff "$base_commit"..HEAD --check`

Run: `python -m pytest -q`

Run: `npm run build`（工作目录 `web`）

Expected: diff check 0 errors；pytest 0 failures；Vite exit 0。

- [ ] **Step 2: 生产只读预览**

在腾讯云应用环境执行：

```bash
archive_admin_username="$(PYTHONPATH=. python -c 'from app.db import SessionLocal; from app.models import User; s=SessionLocal(); print(s.query(User).filter_by(role="admin", is_active=True).order_by(User.id).one().username)')"
PYTHONPATH=. python scripts/archive_completed_sales_orders.py --admin-username "$archive_admin_username"
```

保存候选总数和订单号清单；核对清单中所有订单每个尺码 `remaining <= 0`，任何仍欠货订单都不得出现。

- [ ] **Step 3: 备份并部署**

按 `wiki/发货系统生产架构.md`：停止 `zy-shipping`，完整备份 PostgreSQL 和 `data/uploads`，执行 `scripts/migration_2026_08_10_sales_order_archives.sql`，部署已验证提交，启动服务。

Expected: `systemctl is-active zy-shipping` 输出 `active`；`/health`、`/app/` 和新静态资源均返回 200。

- [ ] **Step 4: 执行首次批量归档**

```bash
PYTHONPATH=. python scripts/archive_completed_sales_orders.py --admin-username "$archive_admin_username" --apply
```

Expected: 应用数量等于预览候选数量，重新预览为 0 个待归档完成订单。

- [ ] **Step 5: 生产验收**

- 用管理员接口确认进行中/已归档/全部筛选数量相符。
- 抽查正好发完和超发订单均已归档。
- 抽查仍欠货订单保持进行中。
- 用员工账号确认归档订单不出现在 `/mobile/orders` 和新建发货候选。
- 对已归档订单直接提交新发货返回“订单已归档，请先恢复”。
- 历史发货、照片和快递关联数量与部署前一致。
- 实际生成内部版和客户版工作簿，确认已归档订单仍存在。

- [ ] **Step 6: 记录知识库并校验**

新建当天 raw 核验记录，更新生产架构 wiki 的归档规则与部署验证，禁止写入密码、密钥、IP 等敏感信息。

Run: `python E:\CODEX\scripts\lint-wiki.py`

Expected: `LINT OK`。

---

## 最终验收清单

- [ ] 独立归档表保留多次归档/恢复历史。
- [ ] 只有管理员能归档和恢复。
- [ ] 剩余数量大于 0 的任一尺码会阻止归档并明确提示。
- [ ] 正好发完和超发订单可归档。
- [ ] 员工端所有新发货入口隐藏归档订单，服务端拒绝绕过提交。
- [ ] 管理端可筛选、查看、归档和恢复。
- [ ] 历史、快递、照片和两种导出不受影响。
- [ ] 首次批量归档预览、备份、执行和复核完整。
- [ ] 腾讯云服务健康，知识库同步并通过 lint。
