# 正式订单号与内部 SPU Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立正式订单主表、公司内递增订单号、跨公司共用内部 SPU、订单行可选客户 SKU，并让员工发货和照片只归属一个订单。

**Architecture:** 保留现有 `OrderLine`、`ShipmentReport`、`PackingDraft` 的业务能力，在其上增加 `Spu` 与 `SalesOrder` 两层主数据，并通过外键把订单行、包货草稿和发货主记录收拢到唯一订单。历史数据采用“预览—人工确认—本地演练—生产执行”四阶段迁移；腾讯云 PostgreSQL 与服务器照片目录是生产真源，本地 SQLite 和旧 Supabase 均不得反向覆盖生产。

**Tech Stack:** Python 3、FastAPI、SQLAlchemy、SQLite/PostgreSQL、Jinja2、Vue 3、Element Plus、pytest、Vite

## Global Constraints

- 一个正式订单只能对应一个公司、一个内部 SPU、一个产品、一个款式和一个颜色，可包含多个尺码。
- 不同款式或不同颜色必须拆成不同订单。
- 系统订单号格式为 `公司代码-公司内五位序号-SPU编码[-颜色编码]`，生成后不可修改。
- 公司序号分别从 `00001` 开始，并通过数据库锁与唯一约束防止并发重复。
- 客户订单号可空，与系统订单号分开保存。
- 客户 SKU 只是订单尺码行上的可选文本；不建映射、不自动生成、不沿用上一订单。
- 员工一次上报只能绑定一个订单，所有发货行都必须属于该订单。
- 本阶段不修改条形码生成、打印或扫码规则。
- 历史缺少下单日期或无法唯一归组的记录必须进入人工确认清单，不得猜测。
- 生产数据库与服务器 `data/uploads/`、`data/waybills/` 必须在迁移前备份。
- 旧 Supabase 不是生产真源，不得用于生产迁移。

---

### Task 1: 移除临时“日期代替订单号”补丁并建立数据模型测试

**Files:**
- Modify: `app/models.py`
- Modify: `tests/test_db.py`
- Create: `tests/test_formal_orders.py`
- Revert by patch: `app/api_v1.py`, `web/src/views/Shipments.vue`, `tests/test_api_v1_more.py`

**Interfaces:**
- Produces: `Spu`, `SalesOrder`, `Company.code`, `Company.next_order_sequence`, `OrderLine.order_id`, `OrderLine.customer_sku`, `PackingDraft.order_id`, `ShipmentReport.order_id`

- [ ] **Step 1: 用 `apply_patch` 删除未提交的临时订单日期展示代码**

删除 `_report_dict()` 中临时拼装的 `order_label`、页面临时“订单号/下单日期”列及对应临时测试，恢复到提交 `3012564` 的设计基线。不要使用 `git checkout --`，不要覆盖用户的其他改动。

- [ ] **Step 2: 写失败的模型测试**

```python
def test_formal_order_schema_has_required_links(db_session):
    company = Company(name="源兴发", code="YXF", next_order_sequence=1)
    spu = Spu(code="JS", product_name="啦啦队", style_name="僵尸啦啦队")
    db_session.add_all([company, spu])
    db_session.flush()
    order = SalesOrder(
        system_order_no="YXF-00001-JS-RED",
        customer_order_no="",
        company_id=company.id,
        company_sequence=1,
        spu_id=spu.id,
        product_name="啦啦队",
        style_name="僵尸啦啦队",
        color_name="红色",
        color_code="RED",
        order_date="2026-08-09",
    )
    db_session.add(order)
    db_session.flush()
    line = OrderLine(
        order_id=order.id,
        company_id=company.id,
        product_name=order.product_name,
        style_name=order.style_name,
        size="S",
        quantity=100,
        customer_sku="FZB1209001-01-red-S",
    )
    db_session.add(line)
    db_session.commit()
    assert line.order.system_order_no == "YXF-00001-JS-RED"
    assert line.customer_sku == "FZB1209001-01-red-S"
```

- [ ] **Step 3: 运行测试并确认因模型缺失而失败**

Run: `python -m pytest tests/test_formal_orders.py::test_formal_order_schema_has_required_links -q`

Expected: FAIL，提示无法导入 `Spu` 或 `SalesOrder`。

- [ ] **Step 4: 实现最小模型**

在 `app/models.py` 中增加唯一约束并建立关系：

```python
class Spu(Base):
    __tablename__ = "spus"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    product_name: Mapped[str] = mapped_column(String(160), index=True)
    style_name: Mapped[str] = mapped_column(String(160), index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SalesOrder(Base):
    __tablename__ = "sales_orders"
    __table_args__ = (
        UniqueConstraint("company_id", "company_sequence", name="uq_sales_orders_company_sequence"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    system_order_no: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    customer_order_no: Mapped[str] = mapped_column(String(160), default="", index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    company_sequence: Mapped[int] = mapped_column(Integer)
    spu_id: Mapped[int] = mapped_column(ForeignKey("spus.id"), index=True)
    product_name: Mapped[str] = mapped_column(String(160))
    style_name: Mapped[str] = mapped_column(String(160))
    color_name: Mapped[str] = mapped_column(String(120), default="")
    color_code: Mapped[str] = mapped_column(String(40), default="")
    order_date: Mapped[str] = mapped_column(String(30), index=True)
    delivery_date: Mapped[str] = mapped_column(String(80), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
```

给 `Company` 增加 `code` 和 `next_order_sequence`；给 `OrderLine` 增加可空 `order_id` 与 `customer_sku`；给 `PackingDraft` 和 `ShipmentReport` 增加可空 `order_id`。迁移完成前外键允许为空，生产迁移验收后再由业务校验强制新数据必填。

- [ ] **Step 5: 运行模型测试**

Run: `python -m pytest tests/test_db.py tests/test_formal_orders.py -q`

Expected: PASS。

- [ ] **Step 6: 提交模型基线**

```bash
git add app/models.py tests/test_db.py tests/test_formal_orders.py app/api_v1.py web/src/views/Shipments.vue tests/test_api_v1_more.py
git commit -m "feat: add formal order and SPU schema"
```

### Task 2: 实现公司代码、SPU 与事务安全订单号

**Files:**
- Create: `app/services/spus.py`
- Create: `app/services/sales_orders.py`
- Modify: `tests/test_formal_orders.py`

**Interfaces:**
- Produces: `normalize_code(value: str) -> str`
- Produces: `create_spu(session, code, product_name, style_name, note="") -> Spu`
- Produces: `create_sales_order(session, company_id, spu_id, color_name, color_code, order_date, lines, customer_order_no="", delivery_date="", note="") -> SalesOrder`

- [ ] **Step 1: 写订单编号失败测试**

```python
def test_company_sequences_are_independent_and_color_is_optional(db_session):
    yxf = Company(name="源兴发", code="YXF", next_order_sequence=1)
    zp = Company(name="张鹏", code="ZP", next_order_sequence=1)
    spu = Spu(code="JS", product_name="啦啦队", style_name="僵尸啦啦队")
    db_session.add_all([yxf, zp, spu])
    db_session.commit()
    first = create_sales_order(db_session, yxf.id, spu.id, "红色", "RED", "2026-08-09", [{"size": "S", "quantity": 100, "customer_sku": "SKU-S"}])
    second = create_sales_order(db_session, yxf.id, spu.id, "", "", "2026-08-10", [{"size": "M", "quantity": 50, "customer_sku": ""}])
    other = create_sales_order(db_session, zp.id, spu.id, "红色", "RED", "2026-08-09", [{"size": "S", "quantity": 30, "customer_sku": ""}])
    assert first.system_order_no == "YXF-00001-JS-RED"
    assert second.system_order_no == "YXF-00002-JS"
    assert other.system_order_no == "ZP-00001-JS-RED"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_formal_orders.py::test_company_sequences_are_independent_and_color_is_optional -q`

Expected: FAIL，提示 `create_sales_order` 不存在。

- [ ] **Step 3: 实现代码规范化与订单创建**

```python
CODE_PATTERN = re.compile(r"^[A-Z0-9]+$")

def normalize_code(value: str) -> str:
    code = str(value or "").strip().upper()
    if not code or not CODE_PATTERN.fullmatch(code):
        raise ValueError("编码只能包含大写英文字母和数字")
    return code

def build_system_order_no(company_code: str, sequence: int, spu_code: str, color_code: str = "") -> str:
    parts = [normalize_code(company_code), f"{sequence:05d}", normalize_code(spu_code)]
    if str(color_code or "").strip():
        parts.append(normalize_code(color_code))
    return "-".join(parts)
```

`create_sales_order()` 必须用 `with_for_update()` 锁定公司行，读取并递增 `next_order_sequence`，复制 SPU 产品/款式快照，创建尺码行，并在同一事务提交。客户 SKU 只写当前订单行，不查询旧订单。

`create_spu()` 在用户手工填写编码时使用规范化后的编码；留空时按 SPU 主键序列生成 `SPU00001`、`SPU00002`。自动编码同样写入唯一索引，订单号示例为 `YXF-00001-SPU00001-RED`。

- [ ] **Step 4: 增加非法编码、重复尺码、空尺码和空数量测试并实现校验**

Run: `python -m pytest tests/test_formal_orders.py -q`

Expected: PASS。

- [ ] **Step 5: 提交服务层**

```bash
git add app/services/spus.py app/services/sales_orders.py tests/test_formal_orders.py
git commit -m "feat: generate company-scoped order numbers"
```

### Task 3: 增加 PostgreSQL/SQLite 迁移脚本

**Files:**
- Create: `scripts/migration_2026_08_09_formal_orders.sql`
- Modify: `app/db.py`
- Modify: `tests/test_db.py`

**Interfaces:**
- Produces: 可在腾讯云由 postgres 管理员执行的幂等 SQL
- Produces: SQLite 本地启动时的兼容加列逻辑

- [ ] **Step 1: 写数据库升级失败测试**

测试旧 SQLite 结构启动后包含 `spus`、`sales_orders`、`companies.code`、`order_lines.order_id/customer_sku`、`packing_drafts.order_id`、`shipment_reports.order_id`。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_db.py -q`

Expected: FAIL，缺少新增表或列。

- [ ] **Step 3: 编写 SQL 迁移**

SQL 必须包含：新表、外键、唯一索引、旧表加列、应用账号授权和关闭 RLS：

```sql
ALTER TABLE companies ADD COLUMN IF NOT EXISTS code VARCHAR(40) DEFAULT '';
ALTER TABLE companies ADD COLUMN IF NOT EXISTS next_order_sequence INTEGER DEFAULT 1;
CREATE UNIQUE INDEX IF NOT EXISTS uq_companies_code_nonempty ON companies(code) WHERE code <> '';

CREATE TABLE IF NOT EXISTS spus (
    id SERIAL PRIMARY KEY,
    code VARCHAR(40) NOT NULL UNIQUE,
    product_name VARCHAR(160) NOT NULL,
    style_name VARCHAR(160) NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS ix_spus_code ON spus(code);
CREATE INDEX IF NOT EXISTS ix_spus_product_name ON spus(product_name);
CREATE INDEX IF NOT EXISTS ix_spus_style_name ON spus(style_name);

CREATE TABLE IF NOT EXISTS sales_orders (
    id SERIAL PRIMARY KEY,
    system_order_no VARCHAR(160) NOT NULL UNIQUE,
    customer_order_no VARCHAR(160) NOT NULL DEFAULT '',
    company_id INTEGER NOT NULL REFERENCES companies(id),
    company_sequence INTEGER NOT NULL,
    spu_id INTEGER NOT NULL REFERENCES spus(id),
    product_name VARCHAR(160) NOT NULL,
    style_name VARCHAR(160) NOT NULL,
    color_name VARCHAR(120) NOT NULL DEFAULT '',
    color_code VARCHAR(40) NOT NULL DEFAULT '',
    order_date VARCHAR(30) NOT NULL,
    delivery_date VARCHAR(80) NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_sales_orders_company_sequence UNIQUE(company_id, company_sequence)
);
CREATE INDEX IF NOT EXISTS ix_sales_orders_system_order_no ON sales_orders(system_order_no);
CREATE INDEX IF NOT EXISTS ix_sales_orders_customer_order_no ON sales_orders(customer_order_no);
CREATE INDEX IF NOT EXISTS ix_sales_orders_company_id ON sales_orders(company_id);
CREATE INDEX IF NOT EXISTS ix_sales_orders_spu_id ON sales_orders(spu_id);
CREATE INDEX IF NOT EXISTS ix_sales_orders_order_date ON sales_orders(order_date);
CREATE INDEX IF NOT EXISTS ix_sales_orders_status ON sales_orders(status);
ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS order_id INTEGER REFERENCES sales_orders(id);
ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS customer_sku VARCHAR(255) DEFAULT '';
ALTER TABLE packing_drafts ADD COLUMN IF NOT EXISTS order_id INTEGER REFERENCES sales_orders(id);
ALTER TABLE shipment_reports ADD COLUMN IF NOT EXISTS order_id INTEGER REFERENCES sales_orders(id);

GRANT ALL PRIVILEGES ON TABLE spus, sales_orders TO zy_shipping;
GRANT ALL PRIVILEGES ON SEQUENCE spus_id_seq, sales_orders_id_seq TO zy_shipping;
ALTER TABLE spus DISABLE ROW LEVEL SECURITY;
ALTER TABLE sales_orders DISABLE ROW LEVEL SECURITY;
```

迁移脚本只包含上述正式订单与 SPU 字段，不加入条形码或 SKU 映射表。

- [ ] **Step 4: 实现 SQLite 兼容迁移并验证**

Run: `python -m pytest tests/test_db.py tests/test_formal_orders.py -q`

Expected: PASS。

- [ ] **Step 5: 提交迁移**

```bash
git add scripts/migration_2026_08_09_formal_orders.sql app/db.py tests/test_db.py
git commit -m "feat: add formal order database migration"
```

### Task 4: 增加公司代码、SPU 与正式订单 API

**Files:**
- Modify: `app/api_v1.py`
- Create: `tests/test_formal_orders_api.py`

**Interfaces:**
- Produces: `GET/POST /api/v1/spus`
- Produces: `POST /api/v1/spus/{spu_id}/update`
- Produces: `GET /api/v1/companies`
- Produces: `POST /api/v1/companies/{company_id}/code`
- Produces: `GET /api/v1/sales-orders`
- Produces: `GET /api/v1/sales-orders/{order_id}`
- Produces: `POST /api/v1/sales-orders`

- [ ] **Step 1: 写 API 失败测试**

```python
def test_create_sales_order_api_returns_generated_number(client, db_session):
    response = client.post("/api/v1/sales-orders", json={
        "company_id": 1,
        "spu_id": 1,
        "color_name": "红色",
        "color_code": "RED",
        "order_date": "2026-08-09",
        "customer_order_no": "",
        "lines": [{"size": "S", "quantity": 100, "customer_sku": "FZB1209001-01-red-S"}],
    })
    assert response.status_code == 200
    assert response.json()["system_order_no"] == "YXF-00001-JS-RED"
```

- [ ] **Step 2: 运行测试确认 404**

Run: `python -m pytest tests/test_formal_orders_api.py -q`

Expected: FAIL，接口不存在。

- [ ] **Step 3: 实现 API 与序列化**

订单详情返回订单头、尺码行、客户 SKU 和关联发货汇总。API 错误使用明确中文信息：公司未设置代码、SPU 停用、颜色有名称但无编码、重复尺码、订单不存在。

- [ ] **Step 4: 验证 API 测试**

Run: `python -m pytest tests/test_formal_orders_api.py tests/test_api_v1.py tests/test_api_v1_more.py -q`

Expected: PASS。

- [ ] **Step 5: 提交 API**

```bash
git add app/api_v1.py tests/test_formal_orders_api.py
git commit -m "feat: expose SPU and formal order APIs"
```

### Task 5: 改造 Vue 管理端订单流程

**Files:**
- Modify: `web/src/api.js`
- Modify: `web/src/router.js`
- Modify: `web/src/App.vue`
- Create: `web/src/views/Companies.vue`
- Create: `web/src/views/Spus.vue`
- Create: `web/src/views/SalesOrders.vue`
- Create: `web/src/views/SalesOrderDetail.vue`
- Modify: `web/src/views/NewOrder.vue`
- Modify: `web/src/views/Orders.vue`
- Create: `tests/test_admin_assets.py`

**Interfaces:**
- Consumes: Task 4 API
- Produces: SPU 管理、正式订单列表、正式订单详情和新版新增订单页面

- [ ] **Step 1: 写前端静态契约失败测试**

测试路由包含 `/companies`、`/spus`、`/sales-orders`、`/sales-orders/:id`；公司页能维护唯一公司代码；新增订单页包含公司、SPU、颜色名称、颜色编码、客户订单号、尺码、数量和客户 SKU 字段。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_admin_assets.py -q`

Expected: FAIL，缺少新路由和页面。

- [ ] **Step 3: 实现页面**

公司页列出公司名称、公司代码和下一个订单序号，只允许编辑公司代码。新增订单页选择 SPU 后只读显示产品和款式；颜色名称与颜色编码同时为空表示无颜色；客户 SKU 输入位于每个尺码行。保存成功后展示系统订单号并跳转订单详情。

- [ ] **Step 4: 构建与测试**

Run: `python -m pytest tests/test_admin_assets.py -q`

Run: `cd web && npm run build`

Expected: 测试 PASS，Vite build exit 0。

- [ ] **Step 5: 提交管理端**

```bash
git add web/src/api.js web/src/router.js web/src/App.vue web/src/views/Companies.vue web/src/views/Spus.vue web/src/views/SalesOrders.vue web/src/views/SalesOrderDetail.vue web/src/views/NewOrder.vue web/src/views/Orders.vue web/dist tests/test_admin_assets.py
git commit -m "feat: add formal order management UI"
```

### Task 6: 强制员工一次上报只属于一个订单

**Files:**
- Modify: `app/services/packing_drafts.py`
- Modify: `app/services/shipments.py`
- Modify: `app/main.py`
- Modify: `app/templates/mobile/report.html`
- Modify: `app/templates/mobile/today.html`
- Modify: `tests/test_packing_drafts.py`
- Create: `tests/test_shipment_order_binding.py`

**Interfaces:**
- Consumes: `SalesOrder` 与其订单尺码行
- Produces: `create_packing_draft(session, user_id: int, order_id: int, pack_date: str, lines: list[dict], note: str = "", photo_paths: list[str] | None = None, waybill_no: str = "") -> PackingDraft`
- Produces: `submit_shipment_report(session, user_id: int, order_id: int, ship_date: str, lines: list[dict], photo_paths: list[str] | None = None, note: str = "", waybill_no: str = "") -> ShipmentReport`

- [ ] **Step 1: 写跨订单上报失败测试**

```python
def test_shipment_rejects_line_from_another_order(db_session):
    with pytest.raises(ValueError, match="发货尺码不属于所选订单"):
        submit_shipment_report(
            db_session,
            user_id=worker.id,
            order_id=first_order.id,
            ship_date="2026-08-09",
            lines=[{"order_line_id": second_order.lines[0].id, "size": "S", "quantity": 10}],
            photo_paths=[],
            note="",
        )
```

- [ ] **Step 2: 运行测试确认现有服务无法执行该约束**

Run: `python -m pytest tests/test_shipment_order_binding.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现服务端强制校验**

服务端从订单快照填写公司、产品、款式和颜色，忽略客户端伪造的这些字段；逐行校验 `order_line.order_id == order_id`。草稿和正式发货都保存同一个 `order_id`。

- [ ] **Step 4: 改造手机端**

员工先搜索并选择系统订单号；页面仅加载该订单尺码行、剩余数量和客户 SKU。不同订单不能在同一个草稿中切换；需要切换时新建草稿。

- [ ] **Step 5: 运行相关测试**

Run: `python -m pytest tests/test_packing_drafts.py tests/test_shipment_order_binding.py tests/test_pages.py tests/test_worker_report_editing.py -q`

Expected: PASS。

- [ ] **Step 6: 提交员工上报改造**

```bash
git add app/services/packing_drafts.py app/services/shipments.py app/main.py app/templates/mobile/report.html app/templates/mobile/today.html tests/test_packing_drafts.py tests/test_shipment_order_binding.py
git commit -m "feat: bind each worker shipment to one order"
```

### Task 7: 在发货、照片、快递和导出中展示正式订单

**Files:**
- Modify: `app/api_v1.py`
- Modify: `web/src/views/Shipments.vue`
- Modify: `web/src/views/Logistics.vue`
- Modify: `app/services/exports.py`
- Modify: `tests/test_api_v1_more.py`
- Modify: `tests/test_logistics.py`
- Modify: `tests/test_customer_export.py`

**Interfaces:**
- Consumes: `ShipmentReport.order_id -> SalesOrder`
- Produces: 发货 API 的 `order` 对象，含 `id/system_order_no/customer_order_no/spu_code/color_name`

- [ ] **Step 1: 写发货明细失败测试**

```python
order = response.json()["reports"][0]["order"]
assert order == {
    "id": sales_order.id,
    "system_order_no": "YXF-00001-JS-RED",
    "customer_order_no": "",
    "spu_code": "JS",
    "color_name": "红色",
}
```

- [ ] **Step 2: 运行测试确认接口未返回正式订单**

Run: `python -m pytest tests/test_api_v1_more.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现展示和导出**

发货明细用单独列显示系统订单号、客户订单号、SPU、颜色，订单号链接到正式订单详情。快递详情展示相同信息。内部版和客户版导出增加系统订单号；客户订单号有值时另列输出。

- [ ] **Step 4: 验证相关测试与前端构建**

Run: `python -m pytest tests/test_api_v1_more.py tests/test_logistics.py tests/test_customer_export.py -q`

Run: `cd web && npm run build`

Expected: PASS，build exit 0。

- [ ] **Step 5: 提交追溯展示**

```bash
git add app/api_v1.py app/services/exports.py web/src/views/Shipments.vue web/src/views/Logistics.vue web/dist tests/test_api_v1_more.py tests/test_logistics.py tests/test_customer_export.py
git commit -m "feat: show formal orders across shipments"
```

### Task 8: 建立历史订单预览与人工确认迁移

**Files:**
- Create: `scripts/migrate_legacy_sales_orders.py`
- Create: `tests/test_legacy_order_migration.py`
- Modify: `scripts/sync_cloud_to_sqlite.py`
- Create: `tests/test_cloud_sync.py`

**Interfaces:**
- Produces: `python scripts/migrate_legacy_sales_orders.py --database data/cloud_sync.sqlite3 --preview work/legacy-order-preview.json`
- Produces: `python scripts/migrate_legacy_sales_orders.py --database data/cloud_sync.sqlite3 --apply work/legacy-order-decisions.json`

- [ ] **Step 1: 写历史归组失败测试**

覆盖：同公司按日期稳定编号、不同公司各自从 1 开始、缺日期进入 `needs_review`、颜色不猜测、跨候选订单发货进入 `needs_review`。

- [ ] **Step 2: 运行测试确认迁移器不存在**

Run: `python -m pytest tests/test_legacy_order_migration.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现只读预览**

预览 JSON 每项必须包含原订单行 ID、公司、产品、款式、批次、下单日期、候选 SPU、候选颜色、关联发货 ID 和原因。缺日期记录的原因固定为 `missing_order_date`，脚本不得生成系统订单号。

- [ ] **Step 4: 实现显式决定文件与执行模式**

决定文件逐项写明：

```json
{
  "order_line_ids": [101, 102, 103],
  "company_code": "YXF",
  "spu_code": "JS",
  "color_name": "红色",
  "color_code": "RED",
  "order_date": "2026-07-15",
  "customer_order_no": ""
}
```

执行模式只接受决定文件中的明确值。运行后输出迁移审计：订单行总数、已归组数、未确认数、发货总数、已绑定发货数、跨订单异常数、照片数和快递关联数。

- [ ] **Step 5: 修复云端同步脚本的结构漂移问题**

现有脚本按本地 ORM 全列查询，连接旧库时因缺列失败。改为反射源表，只复制源表与目标表的列交集，并打印缺失列；如果源数据库不是腾讯云生产连接，必须显示醒目警告并要求 `--allow-non-production-source` 才继续。

- [ ] **Step 6: 运行迁移和同步测试**

Run: `python -m pytest tests/test_legacy_order_migration.py tests/test_cloud_sync.py -q`

Expected: PASS。

- [ ] **Step 7: 提交迁移工具**

```bash
git add scripts/migrate_legacy_sales_orders.py scripts/sync_cloud_to_sqlite.py tests/test_legacy_order_migration.py tests/test_cloud_sync.py
git commit -m "feat: add reviewed legacy order migration"
```

### Task 9: 用腾讯云最新数据演练并逐条确认异常订单

**Files:**
- Runtime output only: `work/tencent-cloud-state.txt`
- Runtime output only: `work/legacy-order-preview.json`
- Runtime output only: `work/legacy-order-decisions.json`
- Runtime output only: `work/migration-audit.json`

**Interfaces:**
- Consumes: 腾讯云 `/home/ubuntu/zy-shipping/.env`、PostgreSQL `zy_shipping`、服务器照片目录
- Produces: 经用户逐条确认的历史迁移决定文件

- [ ] **Step 1: 通过腾讯云 Lighthouse Web 终端记录生产状态**

```bash
cd /home/ubuntu/zy-shipping
git rev-parse HEAD
systemctl is-active zy-shipping
curl -fsS http://127.0.0.1:8000/health
sudo -u postgres psql -d zy_shipping -Atc "select 'orders='||count(*) from order_lines union all select 'reports='||count(*) from shipment_reports union all select 'photos='||count(*) from shipment_photos;"
```

Expected: 服务为 `active`，健康检查成功，并记录三类数量。

- [ ] **Step 2: 在腾讯云生成迁移前备份**

```bash
cd /home/ubuntu/zy-shipping
backup_dir="/home/ubuntu/zy-shipping/backups/pre-formal-orders-20260809"
mkdir -p "$backup_dir"
sudo -u postgres pg_dump -Fc zy_shipping > "$backup_dir/zy_shipping.dump"
tar -C /home/ubuntu/zy-shipping/data -czf "$backup_dir/uploads-waybills.tar.gz" uploads waybills
```

Expected: dump 和 tar 文件均非空。

- [ ] **Step 3: 从腾讯云生成只读 SQLite 快照并下载到本地 `work/`**

```bash
cd /home/ubuntu/zy-shipping
set -a
source ./.env
set +a
./.venv/bin/python scripts/sync_cloud_to_sqlite.py data/formal_orders_source.sqlite3
```

通过 Lighthouse 文件管理下载为本地 `work/tencent_formal_orders_source.sqlite3`。不得用本地 `data/zy_shipping.sqlite3` 或旧 Supabase 替代。

- [ ] **Step 4: 在本地快照运行预览**

Run: `python scripts/migrate_legacy_sales_orders.py --database work/tencent_formal_orders_source.sqlite3 --preview work/legacy-order-preview.json`

Expected: 不修改快照，输出自动候选和 `needs_review`。

- [ ] **Step 5: 把每一条缺日期或歧义记录逐条展示给用户确认**

每次只询问一个订单分组，记录用户给出的下单日期、SPU、颜色和分组决定；所有答案写入 `work/legacy-order-decisions.json`。未确认完不得执行迁移。

- [ ] **Step 6: 复制快照并演练迁移**

Run: `Copy-Item -LiteralPath work\tencent_formal_orders_source.sqlite3 -Destination work\tencent_formal_orders_dry_run.sqlite3`

Run: `python scripts/migrate_legacy_sales_orders.py --database work/tencent_formal_orders_dry_run.sqlite3 --apply work/legacy-order-decisions.json --audit work/migration-audit.json`

Expected: 未确认数为 0、跨订单异常数为 0，订单行/发货/照片/快递数量与迁移前一致。

- [ ] **Step 7: 用户审核迁移审计**

向用户报告每家公司订单序号范围、订单数、缺日期确认数、发货绑定数、照片数和余额核对结果。收到明确批准前不得操作生产数据库。

### Task 10: 完整验证、推送与腾讯云发布

**Files:**
- Modify: `README.md`
- Modify: `E:\CODEX\1-项目\仓库系统管理\07-更新日志.md`

**Interfaces:**
- Produces: GitHub main 新提交、腾讯云已迁移数据库、已重启服务

- [ ] **Step 1: 运行完整验证**

Run: `python -m pytest -q`

Run: `cd web && npm run build`

Expected: 所有测试 PASS，Vite build exit 0。

- [ ] **Step 2: 更新部署文档与项目记忆**

README 记录正式订单、SPU、迁移脚本和生产备份流程；Obsidian 更新日志只写可复用结论，不写服务器密码、密钥或数据库连接串。

- [ ] **Step 3: 提交最终文档并确认工作树范围**

```bash
git add README.md web/dist
git commit -m "docs: document formal order deployment"
git status --short
git log --oneline origin/main..HEAD
```

Expected: 只包含本功能提交，无意外数据文件或密钥。

- [ ] **Step 4: 用户批准生产发布后推送 GitHub**

Run: `git push origin main`

Expected: GitHub main 指向本功能最终提交。

- [ ] **Step 5: 在腾讯云拉取代码、执行结构迁移**

```bash
cd /home/ubuntu/zy-shipping
git pull --ff-only origin main
sudo -u postgres psql -v ON_ERROR_STOP=1 -d zy_shipping -f scripts/migration_2026_08_09_formal_orders.sql
```

Expected: SQL 无错误，新增表、列、索引和授权存在。

- [ ] **Step 6: 在腾讯云执行经审核的历史迁移**

把已确认的决定文件放到服务器受限临时目录后运行迁移器；迁移器必须再次输出审计且未确认数为 0。决定文件不提交 GitHub，执行后移入备份目录。

- [ ] **Step 7: 重启并验收生产服务**

```bash
cd /home/ubuntu/zy-shipping
sudo systemctl restart zy-shipping
systemctl is-active zy-shipping
curl -fsS http://127.0.0.1:8000/health
```

人工验收：新建无颜色订单、新建有颜色订单、客户 SKU 留空、客户 SKU 填写、员工按订单上报、照片显示唯一订单、快递和导出显示订单号。

- [ ] **Step 8: 核对生产数据与备份可恢复性**

再次运行订单、订单行、发货、照片和快递数量审计，与迁移前记录及本地演练结果比较。若任何数量或余额不一致，停止使用新功能并从迁移前备份恢复，不继续手工修补。
