# 管理端 Vue 新界面设计（路线 B，暂不做桌面壳）

日期：2026-08-04

## 背景

用户希望发货系统管理端界面达到 ERPNext 的观感。选择路线 B：保留 FastAPI 后端与手机端页面，管理端前端用 Vue 3 重写，先本地运行验证效果，再部署上云。桌面壳（Electron/Tauri）暂缓。

## 架构

- 后端：现有 FastAPI 不动，新增 `app/api_v1.py` 路由（JSON API），复用现有 services；手机端模板原样保留。
- 前端：`web/` 目录，Vue 3 + Vite + 组件库（先试 Frappe UI，效果不满意换 Element Plus）。
- 开发模式：Vite dev server（5173）代理 `/api`、`/photos` 到本地 FastAPI（8000）。
- 生产模式：FastAPI 挂载 `web/dist` 静态文件（后续步骤实现）。
- 登录：SPA 内登录页调用 `POST /api/v1/login`，复用现有 cookie 会话（`zy_user_id`）。

## 首批页面（原型范围）

1. 登录
2. 订单查询（筛选、状态页签、表格：公司/产品/款式/订单/尺码/SKU/下单/已发/未发/超发/退货核销关闭/操作）
3. 订单行处理（订单信息、进度、已发记录、订单流水、退货/返工、盘点/调整、关闭、沟通记录）

其余管理页（仪表盘、新增订单、待审核、发货明细、SKU/条码、面单、导出、统计、目标、用户、日志、作业信息）保留旧页面入口，第二批起逐个切换。

## JSON API（`/api/v1`）

- `POST /api/v1/login`：账号密码登录，返回用户 JSON 并种 cookie
- `POST /api/v1/logout`：登出
- `GET /api/v1/me`：当前用户
- `GET /api/v1/orders/balances?company=&item=&status=`：余额列表（含 returned/adjusted/closed）、公司列表、货物选项
- `GET /api/v1/order-lines/{id}`：订单行详情（totals/ledger/returns/adjustments/closes/comments/shipments）
- `POST /api/v1/order-lines/{id}/returns`（multipart 照片）
- `POST /api/v1/order-lines/{id}/returns/{return_id}/status`
- `POST /api/v1/order-lines/{id}/adjustments`
- `POST /api/v1/order-lines/{id}/closes`
- `POST /api/v1/order-lines/{id}/comments`

所有接口复用现有 services（`get_order_balances`、`order_line_totals`、`recompute_order_ledger`、`create_return_rework` 等），JSON 序列化不含密码等敏感字段。

## 前端结构

```
web/
  package.json
  vite.config.js      # dev 代理 /api、/photos
  index.html
  src/
    main.js           # 挂载 Vue + 组件库 + 路由
    App.vue           # 登录态判断 + 布局（顶栏/侧栏/内容区）
    router.js
    api.js            # fetch 封装，带 cookie
    views/
      Login.vue
      Orders.vue      # 订单查询
      OrderLine.vue   # 订单行处理
```

## 验证

- 后端 API：pytest 覆盖新接口（登录、余额列表、详情、四个写接口）
- 前端：本地 Vite + FastAPI 运行，浏览器人工验证登录、筛选、处理页表单、余额变化
- 全量 `pytest` 保持通过

## 暂不做

- Electron/Tauri 桌面壳（等界面定稿后再评估）
- 生产部署挂载 dist（等原型确认后再做）
- 手机端页面改动
