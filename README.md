# 发货系统

> 当前接手与部署状态以 `E:\CODEX\1-项目\仓库系统管理\11-共享接手状态.md` 为准；旧腾讯云记录仅供历史参考。

面向小团队服装订单与发货管理的 Web 系统：订单管理、发货上报、审核、快递单挂靠、导出与统计，电脑端和手机端共用一套数据。

## 部署现状

- 正式环境：阿里云，systemd 服务 `zy-shipping`
- 数据库：PostgreSQL `zy_shipping`（应用账号 `zy_shipping`；表结构由 postgres 管理员维护，迁移见下方「数据库变更」）
- 管理端：Vue 3 + Element Plus，部署在 `/app`（电脑端、手机端浏览器均可访问）
- 手机端：服务端渲染页面 `/mobile`（员工发货上报）
- 照片：统一存服务器本地 `data/uploads/公司名/`，按公司分文件夹隔离
- 代码仓库：GitHub `redyuxiplayer-coder/CODEX`（main 分支），云端 `git pull` 更新

## 访问入口

当前通过以下域名访问：

- 管理端：`http://www.zyfahuo.cn/app/`
- 手机端：`http://www.zyfahuo.cn/mobile/login`

## 功能

### 管理端（/app）

- 首页统计：待审核数、今日发货、超发合计等
- 新增订单 / 订单查询：订单行余额 = 下单 − 已发 + 退回 − 核销 − 关闭；订单行详情含流水、退货/返工、盘点/调整（支持负数冲超发）、关闭、沟通记录
- 正式订单与发货明细中的订单号进入同一张完整订单详情页，顶部显示系统和客户订单号、各尺码进度；从发货明细进入时自动选中对应尺码并显示发货流水与原有处理操作。未绑定正式订单的历史行仍打开原订单行页面。
- 管理员新建正式订单时可为每个尺码填写人民币商品单价，也可留空，之后在订单详情逐尺码补录、修改或清空；每次修改写入操作日志。单价最多三位小数且不能为负数。
- 尺码金额按下单数量 × 单价计算，精确到三位小数。所有有效尺码均已填写时显示订单总金额；仍有空值时显示“总金额待补全”、已填写小计和未填写尺码数。空值表示未知价格，明确填写的 `0.000` 表示零单价。
- 待审核：超发、无订单、重复嫌疑进入待审核，老板通过或驳回
- 发货明细：按日期/公司/款式查看，可按快递单号搜索；页面右上角「新增发货」打开电脑可用的发货上报页，保存包货草稿后提交审核
- 每日统计：按真实发货日期汇总
- 快递记录：
  - 快递单增删改查，含「快递公司」字段（中通/顺丰/货拉拉/跨越等，默认中通）
  - 可按快递单号部分内容搜索，并与公司、日期筛选组合使用
  - 快递单详情可勾选关联/移除发货明细
  - 「只看未挂靠发货」：列出已审核未挂单的发货单，渠道自动从备注判断（顺丰/货拉拉/跨越/中通，无关键词显示「待确认」）；支持「填单挂靠」（选快递公司+填单号直接建单并挂靠，顺丰等非中通单号也可）和「标原因」（手工维护未挂原因）
- SKU/条码：SKU 管理，条码扫码带出公司/产品/款式
- 作业信息 / 今日目标 / 账号管理 / 操作日志
- 导出：客户版 / 内部版 Excel，含「快递单号」列（关联单号顿号合并），客户版单开「发货明细」工作表
- 单价录入及金额仅出现在管理员新建订单页、订单详情页和内部版 Excel 的订单余额明细中；未填单价的内部版单元格留空。员工页面、员工接口及客户版 Excel 不展示价格。

### 手机端（/mobile）

- 所有已登录页面统一使用「主页｜发货上报｜补货查看｜我的上报｜发货统计」导航；退出入口紧邻用户名。
- 主页“前一日发货”仅显示上报单数和总件数，点击可进入对应日期的发货统计。
- 发货上报（`/mobile/report`）：
  - 员工可直接填写发货日期，日期必填且不能晚于服务器当天
  - 订单选择器支持公司、款式/颜色、订单号筛选；下拉文案显示 `订单号｜下单日期｜颜色｜还差摘要`
  - 草稿列表展示全部“未提交包货草稿”，不再只看当天
  - 物流字段按渠道校验：`courier` 必须填写真实运单号；`huolala` 新建时可留空自动生成车次号，复用已有车次时由系统带出车次号；`package_count` 和 `weight_kg` 两者始终必填
  - `huolala` 可复用同公司 + 同发货日期的已有车次；复用时件数和重量会沿用已有记录
- 我的上报：补录/修改并可勾选删除自己上报中的错误照片；更新后进入待审核，记录审核留痕。若照片仍被包货草稿引用，删除发货明细照片时保留共享源文件。
- 今日目标、作业信息

## 开发与测试

```bash
# 后端测试
python -m pytest tests -q

# 前端构建（打包到 web/dist）
cd web
npm run build
```

本地默认连 `data/zy_shipping.sqlite3`。如需切换到 PostgreSQL，可设置 `SUPABASE_DATABASE_URL` 环境变量传入数据库 URL；这是沿用的历史变量名，当前数据库架构不依赖 Supabase。生产连接目标以阿里云服务实际环境为准。

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

本轮员工发货页物流字段迁移脚本：

```bash
sudo -u postgres psql -d zy_shipping -f scripts/migration_2026_08_21_packing_logistics.sql
```

该脚本使用 `ADD COLUMN IF NOT EXISTS`，可重复执行；执行前仍必须先备份生产数据库。

正式订单尺码单价迁移脚本：

```bash
sudo -u postgres psql -d zy_shipping -f scripts/migration_2026_09_24_order_line_price.sql
```

先备份并核对生产数据库目标，再执行迁移；迁移仅新增可空单价和价格修订号，不回填历史单价。执行后核对字段、非负约束、应用账号权限及历史单价仍为空，再部署应用代码。

已有环境将单价精度升级到三位小数：

```bash
sudo -u postgres psql -d zy_shipping -f scripts/migration_2026_10_17_order_line_price_three_decimals.sql
```

执行前备份 PostgreSQL；该迁移只把 `unit_price` 改为 `NUMERIC(13,3)`，保持原有整数位范围和单价，不回填或改写业务价格。核对字段类型及历史数据后再部署应用。

## 历史发货补绑修复

先用只读 SQL 核验，再决定是否运行 repair CLI：

```bash
sudo -u postgres psql -d zy_shipping -f scripts/audit_orders.sql
```

- `A1`：恰好 1 个正式活跃订单行候选，可安全补绑
- `B`：没有匹配候选，不会自动处理
- `C`：多个活跃候选，属于歧义，不会自动处理

repair CLI 默认分两步：

```bash
# 本地 SQLite 示例
python scripts/repair_unique_shipment_order_bindings.py --database /path/to/db.sqlite3 --preview repair-preview.json
# 本地 SQLite 示例
python scripts/repair_unique_shipment_order_bindings.py --database /path/to/db.sqlite3 --apply --audit repair-audit.json
```

- `--preview` 只读输出 JSON，不写库
- `--apply` 会重新扫描并分类“执行当下”的数据库状态，不会读取 `preview` JSON 回灌执行
- `--apply` 只会补绑它本次重新分类出的 `unique` 记录，`ambiguous` 和 `unmatched` 会保持不变
- 非 SQLite 数据库执行 `--apply` 前，必须先完成备份，并显式加 `--confirm-production-backup`
- 生产执行前至少备份 PostgreSQL、`data/uploads/`、`data/waybills/`
- 推荐时序：先人工检查 `preview`；确认可执行且已完成备份后再运行 `--apply`；`--apply` 完成后再把 `audit` 与 `preview` 比较，核对 `unique` 数量/明细，以及 `ambiguous` / `unmatched` 是否符合预期

生产 PostgreSQL 完整示例：

```bash
python scripts/repair_unique_shipment_order_bindings.py --database-url-env SUPABASE_DATABASE_URL --preview repair-preview.json
python scripts/repair_unique_shipment_order_bindings.py --database-url-env SUPABASE_DATABASE_URL --apply --audit repair-audit.json --confirm-production-backup
```

- `SUPABASE_DATABASE_URL` 是历史遗留变量名；执行前核对阿里云服务实际连接目标
- 生产流程同样遵循：先人工检查 `preview`，确认并备份后执行 `--apply`，最后再用 `audit` 对照 `preview` 复核 `unique` / `ambiguous` / `unmatched`

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
