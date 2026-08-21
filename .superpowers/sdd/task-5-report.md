# Task 5 Report

## Scope

- 本轮仅完成本地阶段：更新仓库 `README.md`、执行全量回归与前端构建、核对迁移/repair 安全性、记录结果。
- 未连接生产、未修改 `E:/CODEX/wiki`、未合并/推送/部署。

## README Update

- 补充了 `/mobile/report` 员工页的真实行为：
  - 发货日期可编辑、必填且不能晚于服务器当天；`2026-08-21` 仅作为本次本地验证日期
  - 订单支持公司 / 款式颜色 / 订单号筛选
  - 下拉文案包含 `订单号｜下单日期｜颜色｜还差摘要`
  - 草稿列表展示全部未提交草稿
  - 物流字段按渠道校验：`courier` 必填真实运单号；`huolala` 新建可留空自动生成，复用时由系统带出；`package_count` 与 `weight_kg` 始终必填
  - `huolala` 支持复用同公司同日期已有车次
- 补充了 `scripts/migration_2026_08_21_packing_logistics.sql` 的执行方式与“先备份再执行”要求。
- 补充了 `scripts/audit_orders.sql` 与 `scripts/repair_unique_shipment_order_bindings.py` 的 preview/apply 流程，明确 `--apply` 会重新分类当前数据库、不读取 preview JSON，并要求比较 `preview` 与 `audit`。
- 补充了 PostgreSQL 完整示例：`--database-url-env SUPABASE_DATABASE_URL --apply --audit ... --confirm-production-backup`。
- 明确说明：数据库当前不依赖 Supabase；`SUPABASE_DATABASE_URL` 只是历史遗留环境变量名，生产上实际指向腾讯云机器上的 PostgreSQL。

## Verification

### Full pytest

Command:

```bash
python -m pytest tests -q
```

Result:

- `275 passed, 15195 warnings in 30.88s`
- warnings 为仓库既有 FastAPI / Starlette deprecation warnings，本轮未处理。

### Frontend build

Command:

```bash
cd web
npm run build
```

Result:

- Vite build exit 0
- 保留既有 warnings：
  - Rollup 无法解释 `@vueuse/core` 中的 `#__PURE__` 注释位置
  - admin SPA bundle chunk size warning

### Build artifact cleanup

- 构建后检查到 `web/dist` 生成噪声。
- 已恢复跟踪产物并删除新增的 `web/dist/assets/index-CzyrbLdw.js`。
- 最终保留源码/文档 diff，不让构建产物混入提交。

## Code and Test Inspection

### Migration idempotence

- `scripts/migration_2026_08_21_packing_logistics.sql` 对 `packing_drafts` 的三个新字段都使用 `ADD COLUMN IF NOT EXISTS`。
- 脚本中的 `UPDATE ... WHERE ... IS NULL` 仅做空值回填，重复执行仍安全。
- `tests/test_db.py::test_postgres_packing_logistics_migration_is_idempotent_and_grants_app_access` 锁定了该迁移的关键 idempotent 语句与授权语句。

### Repair preview/apply safety

- `scripts/repair_unique_shipment_order_bindings.py` 使用 mutually exclusive CLI：`--preview` 与 `--apply` 不能同时传。
- `main(...)` 中 `--apply` 强制要求 `--audit`，`--preview` 路径只调用 `classify_unbound_lines(...)`，不写库。
- `apply_unique_bindings(session)` 内部会调用 `classify_unbound_lines(session)`，重新按当前数据库状态分类；它不会读取已有 `preview` JSON 文件作为输入。
- 非 SQLite `--apply` 会在 `open_session(...)` 之前强制检查 `--confirm-production-backup`。
- `tests/test_repair_unique_shipment_bindings.py` 覆盖了：
  - preview/apply 互斥
  - non-SQLite apply 缺少 `--confirm-production-backup` 时直接报错且不会打开连接
  - apply 只绑定 unique，重复执行第二次 `bound_line_count == 0`

### Ambiguous shipments stay unbound

- `apply_unique_bindings(...)` 只遍历 `classification["unique"]`；`classification["ambiguous"]` 与 `classification["unmatched"]` 仅出现在返回审计 payload 中，不参与写入。
- `tests/test_repair_unique_shipment_bindings.py::test_apply_binds_only_unique_lines_updates_report_and_stays_idempotent` 明确断言：
  - `ambiguous_line.order_line_id is None`
  - `unmatched_line.order_line_id is None`
- 因此，基于代码与测试可确认：生产先前核出的 5 条歧义记录不会被该脚本自动绑定；它们只能继续留在 `ambiguous` 桶中等待人工处理。

## Diff Check

Before cleanup:

- `README.md`
- `web/dist/*` build noise

After cleanup:

- `README.md`
- `.superpowers/sdd/task-5-report.md`

## Attention Points

- 本轮没有改代码逻辑，只改文档与报告。
- 仓库仍保留少量与照片兼容有关的 Supabase 命名/逻辑，但数据库连接与本次迁移/repair 流程无关；README 已按当前真实架构澄清。
- `E:/CODEX/wiki/发货系统生产架构.md` 需等生产核验完成后由主代理写入真实结果。

## Review Fix Round

### Scope

- 本轮仅修复 Task 5 文档审查意见，不改业务代码，不重跑全量测试/构建。

### Changes

- 把“不得晚于 `2026-08-21`”修正为“不得晚于服务器当天”，并把 `2026-08-21` 明确为本次本地验证日期。
- 在 README 中明确：`--apply` 会重新分类当前数据库，不读取 `preview` JSON；执行前后要比较 `preview` 与 `audit`。
- 在 README 中把执行时序写清楚：先人工检查 `preview`；确认并备份后再 `--apply`；`--apply` 后再用 `audit` 对照 `preview` 核对 `unique` 数量/明细与 `ambiguous` / `unmatched`。
- 在 README 中补充了本地 SQLite 示例和生产 PostgreSQL 完整示例，并强调 `SUPABASE_DATABASE_URL` 变量名虽沿用历史命名，但在线上实际指向腾讯云 PostgreSQL，且 `--apply` 前必须先备份。
- 在 README 和报告中把物流必填规则改成按渠道描述：`courier` 真实运单号必填；`huolala` 新建可留空自动生成、复用由系统带出；件数和重量始终必填。
- 复核文档内未引入任何真实连接串、账号、密码或其他敏感值。

### Doc Checks

Commands:

```bash
git diff --check
Select-String -Path README.md,'.superpowers/sdd/task-5-report.md' -Pattern '2026-08-21|服务器当天|preview|audit|SUPABASE_DATABASE_URL|confirm-production-backup|courier|huolala'
```

Expected:

- `git diff --check` 无输出
- 关键字符串均能在修订后的文档中找到，且不存在把 `2026-08-21` 误写成线上固定上限日期的描述
