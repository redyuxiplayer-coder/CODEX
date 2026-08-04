# 参考 ERPNext 的发货系统改进设计

日期：2026-08-04

## 背景

参考 ERPNext 的业务模型（Sales Order -> Delivery Note、部分发货、Packing Slip、审核留痕），对当前发货系统做了三项改进，目标是不引入完整 ERP，只补齐"订单绑定、修改留痕、包裹归档"三个关键缺口。

## 改进一：修改链路保留订单行绑定

### 问题

- 员工在"我的上报"补录/修改时，新增尺码行不写 `order_line_id`。
- 老板"修改后通过"和员工修改待审核记录时，重建明细行丢失 `order_line_id`。
- 结果：这些行只能按"公司+产品+款式+尺码"聚合估算，无法精确到具体订单批次，超发校验和导出明细会失真。

### 方案

- 新增 `resolve_order_line_id`：优先保留原绑定，尺码变更或无绑定时，从订单余量里自动匹配对应订单行。
- 员工"我的上报"更新、员工修改待审核记录、老板修改后通过三条链路统一复用。
- 顺带修复：`main.py` 更新路由新增尺码行时引用未导入的 `ShipmentLine`，之前会直接 500。

### 涉及文件

- `app/services/shipments.py`
- `app/main.py`
- `tests/test_worker_report_editing.py`
- `tests/test_pages.py`

## 改进二：员工更新写结构化审核留痕

### 问题

员工补录/修改只写一条摘要日志（"更新发货记录，补录N张照片"），没有记录尺码数量前后对比，无法还原修改历史。

### 方案

- 员工每次补录/修改写 `AuditLog`，与老板审核同格式：
  - `before_text`：修改前的尺码数量列表
  - `after_text`：修改后的尺码数量列表
  - `note`：补录照片张数
- 保留现有 `OperationLog` 摘要用于操作列表。

### 涉及文件

- `app/main.py`
- `tests/test_pages.py`

## 改进三：提交后保留包裹分组

### 问题

包货草稿提交后直接删除，"包 -> 照片 -> 面单"的分组信息丢失，面单与发货单无关联。

### 方案

- `PackingDraft` 新增可空外键 `submitted_report_id`，提交后草稿保留并指向发货单。
- `ShipmentPhoto` 新增可空外键 `draft_id`，照片保留"属于哪个包"的关联。
- "我的包货草稿"页面只显示未提交草稿；已提交的包禁止修改/删除。
- `ensure_schema_updates` 自动为已有库补列，SQLite 与 PostgreSQL 兼容，旧数据不受影响。

### 涉及文件

- `app/models.py`
- `app/db.py`
- `app/services/packing_drafts.py`
- `app/main.py`
- `tests/test_packing_drafts.py`
- `tests/test_pages.py`

## 验证

- 全量测试：124 passed。
- 本地真实数据库迁移实测：两列已加，行数不变。
- 改动前已备份本地数据；上线腾讯云前需对 `zy_shipping` 执行 `pg_dump`。
