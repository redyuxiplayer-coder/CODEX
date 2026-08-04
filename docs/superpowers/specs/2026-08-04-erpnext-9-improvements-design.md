# 参考 ERPNext 的发货系统九项改进设计

日期：2026-08-04

## 背景

用户确认以 ERPNext 为参考，为当前发货系统补齐九项能力，覆盖"库存流水、退货返工、订单关闭、盘点调整、SKU/SPU、条码、箱号、沟通记录、运单号"。所有改动沿用现有 FastAPI + SQLAlchemy + Jinja2 结构，本地 SQLite 自动迁移，腾讯云 PostgreSQL 上线时手动补列。

## 数据模型（新增/变更）

### 新增表

- `order_ledger_entries` 订单行流水
  - `order_line_id` FK、`movement_type`（shipped/returned/adjusted/closed）、`quantity`（正数）、`reason`、`ref_report_id`、`ref_return_id`、`ref_adjustment_id`、`ref_close_id`、`created_by` FK、`created_at`
- `return_reworks` 退货/返工
  - `order_line_id` FK、`report_id` FK 可空、`quantity`、`reason_type`（退回返工/质量问题/其他）、`reason`、`status`（pending_rework/reworked/scrapped）、`created_by`、`created_at`、`updated_at`
- `return_rework_photos` 返工照片
  - `return_id` FK、`file_path`、`original_name`
- `order_adjustments` 盘点/调整
  - `order_line_id` FK、`quantity`、`reason`（盘点/少发核销/报废/其他）、`created_by`、`created_at`
- `order_line_closes` 订单行关闭
  - `order_line_id` FK、`quantity`、`reason`、`created_by`、`created_at`
- `order_line_comments` 沟通记录
  - `order_line_id` FK、`user_id` FK、`content`、`created_at`

### 变更表（`ensure_schema_updates` 加列）

- `order_lines.sku` VARCHAR(255) DEFAULT ''
- `sku_mappings.barcode` VARCHAR(255) DEFAULT ''
- `packing_drafts.package_no` VARCHAR(40) DEFAULT ''
- `packing_drafts.waybill_no` VARCHAR(80) DEFAULT ''
- `shipment_reports.waybill_no` VARCHAR(80) DEFAULT ''（带 index）

## 余额公式（核心）

```
remaining = ordered − shipped + returned − adjusted − closed
```

- `shipped`：已通过发货行合计（沿用现有聚合，含未绑定行的按款聚合）
- `returned`：退货/返工记录合计（退回后待重新发货）
- `adjusted`：`order_adjustments` 合计 + 状态为 `scrapped` 的返工记录合计（报废 = 退回后又核销，净效果抵消）
- `closed`：`order_line_closes` 合计（客户不再要）
- `over_shipped = max(0, -remaining)`

退货/返工记录无论状态都先 +returned；状态改为 `scrapped` 时额外计入 adjusted，两者抵消。`get_order_balances` 返回的每行增加 `returned`、`adjusted`、`closed` 字段。

## 流水重建

`recompute_order_ledger(session, order_line_id)`：删除该订单行旧流水，按来源表重建：

- shipped ← 已通过报告的 `ShipmentLine`（有 order_line_id 的）
- returned ← `ReturnRework` 全部
- adjusted ← `OrderAdjustment` + `ReturnRework.status == "scrapped"`
- closed ← `OrderLineClose`

在以下时机调用：审批通过/驳回/修改后通过、员工更新、删除上报、新增/修改/删除返工、调整、关闭。余额计算直接用来源表（与流水同源），流水表用于详情页展示历史。

## UI 变更

### 新增：订单行详情页 `/admin/order-lines/{line_id}`

- 订单基本信息、已发记录
- 订单流水（类型/数量/时间/操作人）
- 退货/返工：列表 + 新增表单（数量、类型、原因、状态、照片上传）；可改状态
- 盘点/调整：列表 + 新增表单
- 关闭：列表 + 新增表单
- 沟通记录：列表 + 新增
- 订单查询页每行加「处理」入口

### SKU/条码

- 新增 `/admin/skus` 管理页：sku_mappings 列表、SKU/条码编辑、按条码搜索
- 新增订单自动按 sku_mappings 解析写入 `order_lines.sku`；批量编辑同步更新
- 移动端上报加「扫码」框：扫描/输入条码 → `/mobile/report/scan` → 自动带出公司/产品/款式

### 箱号与装箱单

- 新建包货草稿自动编号 `PKG-YYYYMMDD-NNN`
- 装箱单打印页 `/admin/packing/{draft_id}/print`、`/mobile/packing/{draft_id}/print`（打印 CSS）

### 运单号

- 包货草稿与发货单各加 `waybill_no`，上报可选填；提交草稿时复制到发货单
- 发货明细显示/按运单号搜索；admin 可修改；我的上报更新表单可填

## 借鉴 ERPNext 的对应关系

| ERPNext | 本项目 |
|---|---|
| Delivery Note（负数量退货） | ReturnRework（退回增加待发量） |
| Sales Order Close | OrderLineClose |
| Stock Reconciliation | OrderAdjustment |
| Stock Ledger Entry | OrderLedgerEntry |
| Item Variants（模板/变体） | SkuMapping + order_lines.sku |
| Item Barcode + 扫码 | sku_mappings.barcode + 扫码带出 |
| Packing Slip | package_no + 装箱单打印 |

## 兼容与迁移

- `ensure_schema_updates` 自动为本地 SQLite 加列；腾讯云 PostgreSQL 需手动执行对应 ALTER（见实施计划）
- 新表由 `Base.metadata.create_all` 创建
- 历史发货不重建流水；未绑定订单行的发货行继续按款聚合，余额行为不变
- 数据目录改动前运行 `scripts\backup_data.ps1`

## 验证

- 每个功能 TDD：先写失败测试再实现
- 全量 `pytest` 通过；本地启动 `uvicorn app.main:app --port 8000` 人工验证页面
