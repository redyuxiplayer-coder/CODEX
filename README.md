# 发货系统

面向小团队服装订单与发货管理的 Web 系统：订单管理、发货上报、审核、快递单挂靠、导出与统计，电脑端和手机端共用一套数据。

## 部署现状

- 正式环境：腾讯云 Lighthouse（`139.155.144.14`），systemd 服务 `zy-shipping`
- 数据库：PostgreSQL `zy_shipping`（应用账号 `zy_shipping`；表结构由 postgres 管理员维护，迁移见下方「数据库变更」）
- 管理端：Vue 3 + Element Plus，部署在 `/app`（电脑端、手机端浏览器均可访问）
- 手机端：服务端渲染页面 `/mobile`（员工发货上报）
- 照片：统一存服务器本地 `data/uploads/公司名/`，按公司分文件夹隔离
- 代码仓库：GitHub `redyuxiplayer-coder/CODEX`（main 分支），云端 `git pull` 更新

## 访问入口

- 管理端：`http://139.155.144.14/app`
- 手机端：`http://139.155.144.14/mobile/login`

## 功能

### 管理端（/app）

- 首页统计：待审核数、今日发货、超发合计等
- 新增订单 / 订单查询：订单行余额 = 下单 − 已发 + 退回 − 核销 − 关闭；订单行详情含流水、退货/返工、盘点/调整（支持负数冲超发）、关闭、沟通记录
- 待审核：超发、无订单、重复嫌疑进入待审核，老板通过或驳回
- 发货明细：按日期/公司/款式查看，可按快递单号搜索
- 每日统计：按真实发货日期汇总
- 快递记录：
  - 快递单增删改查，含「快递公司」字段（中通/顺丰/货拉拉/跨越等，默认中通）
  - 快递单详情可勾选关联/移除发货明细
  - 「只看未挂靠发货」：列出已审核未挂单的发货单，渠道自动从备注判断（顺丰/货拉拉/跨越/中通，无关键词显示「待确认」）；支持「填单挂靠」（选快递公司+填单号直接建单并挂靠，顺丰等非中通单号也可）和「标原因」（手工维护未挂原因）
- SKU/条码：SKU 管理，条码扫码带出公司/产品/款式
- 作业信息 / 今日目标 / 账号管理 / 操作日志
- 导出：客户版 / 内部版 Excel，含「快递单号」列（关联单号顿号合并），客户版单开「发货明细」工作表

### 手机端（/mobile）

- 发货上报：按订单行拆分，点选公司/产品/款式/尺码数量，可上传照片
- 我的上报：补录/修改，老板审核留痕
- 今日目标、作业信息

## 开发与测试

```bash
# 后端测试
pytest tests

# 前端构建（打包到 web/dist）
cd web && npm run build
```

本地默认连 `data/zy_shipping.sqlite3`；设置 `SUPABASE_DATABASE_URL` 环境变量可切换数据库（正式环境指向云端 PostgreSQL）。

## 数据库变更

新表/加列由 postgres 管理员执行迁移脚本（应用账号无 ALTER 权限）：

```bash
sudo -u postgres psql -d zy_shipping -f scripts/<迁移脚本>.sql
```

新表建成后需授权应用账号并确保未开启 RLS：

```sql
GRANT ALL PRIVILEGES ON TABLE <表名> TO zy_shipping;
GRANT ALL PRIVILEGES ON SEQUENCE <表名>_id_seq TO zy_shipping;
ALTER TABLE <表名> DISABLE ROW LEVEL SECURITY;
```

## 数据备份

- 重要数据：PostgreSQL 库 + `data/uploads/`（照片）+ `data/waybills/`（面单照片）
- 云端导出快照供本地复现：

```bash
cd /home/ubuntu/zy-shipping && set -a && source ./.env && set +a && ./.venv/bin/python scripts/sync_cloud_to_sqlite.py data/cloud_sync.sqlite3
```

生成的文件下载后替换本地 `data/zy_shipping.sqlite3` 即可。

## 账号

系统不在公开文档中写明真实账号密码。首次部署空数据库时通过环境变量初始化管理员：

- `ZY_INITIAL_ADMIN_USERNAME`
- `ZY_INITIAL_ADMIN_PASSWORD`

仓库员工账号由老板登录后在「账号管理」中新增。
