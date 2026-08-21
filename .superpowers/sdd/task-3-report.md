# Task 3 Report

## 改动摘要

- `web/src/views/Shipments.vue` 的尺码数量/客户 SKU 列现在只显示尺码、数量和客户 SKU，不再根据 `row.has_multiple_orders` 重复渲染订单号/下单日期。
- 尺码行 key 统一使用 `l.id || `${l.size}-${l.order_line_id || 'unbound'}``，与订单列逐行标识保持一致。
- 保留订单号/下单日期列逐行显示 `l.order_label`；未绑定行继续以红色“未绑定订单”显示。
- `tests/test_admin_assets.py` 增加源码契约测试，锁定统一显示行为。

## RED

- 命令：`python -m pytest tests/test_admin_assets.py tests/test_shipment_order_display.py -q`
- 结果：`1 failed, 8 passed`
- 失败原因：`Shipments.vue` 仍包含 `row.has_multiple_orders && l.system_order_no` 条件，证明测试能捕获旧行为。

## GREEN

- 命令：`python -m pytest tests/test_admin_assets.py tests/test_shipment_order_display.py -q`
- 结果：`9 passed`

## 构建

- 命令：`npm run build`（目录：`web`）
- 结果：Vite build exit 0。
- 保留仓库既有 warning：`@vueuse/core` 的 Rollup `#__PURE__` 注释位置提示及 bundle chunk size 提示；构建产物已恢复，未纳入提交。

## 提交 Hash

- `4bad5c3`（`fix: make shipment order display consistent`）

## 关注事项

- 未修改 API 数据语义、后端 `_report_dict()` 或历史数据。
- 订单列的逐行链接和未绑定红色提示未改变；本次只移除尺码列的重复订单身份信息。
