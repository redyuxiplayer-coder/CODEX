# Final Review Fix Report

- 日期：2026-08-21
- 分支：`feature/worker-shipment-report-binding`
- 隔离工作树：`E:\CODEX\1-项目\仓库系统管理\订单报表系统\.worktrees\worker-shipment-report-binding`
- 起始提交：`8be3221`
- 代码修复提交：`2a5d1bc`
- 结论：`DONE_WITH_CONCERNS`
- 边界：未访问生产环境，未合并、推送或部署，未修改 `E:\CODEX\wiki`。

## 逐项修复与自查

| # | 级别 | 结果 | 最终实现与回归覆盖 |
|---|---|---|---|
| 1 | Critical | 已修复 | 为 `??` 与 `||` 添加明确括号；新增 Node 解析契约测试并运行 `node --check`。 |
| 2 | Critical | 已修复 | 认证员工旧入口 `POST /mobile/report` 返回 410，不再导入或调用 `submit_shipment_report`；回归证明绕过载荷不会创建草稿或正式发货单。 |
| 3 | Important | 已修复 | 草稿提交在事务内以 `SELECT ... FOR UPDATE` 加锁并 `populate_existing()` 重读提交状态；独立复查进一步要求并完成 update/delete 同等加锁。 |
| 4 | Important | 已修复 | create/update/submit 及正式提交共享边界拒绝清洗后空行；覆盖空值、零值及旧入口。 |
| 5 | Important | 已修复 | 页面到服务传递单一 `trip_mode`；新货拉拉车次空号由服务端生成，已有车次只能引用同公司同日期的货拉拉草稿/记录并复制权威件数和重量；快递/货拉拉标识隔离。PostgreSQL 路径增加按物流标识的事务级 advisory lock，Waybill create/update 同样参与并校验完整元数据。 |
| 6 | Important | 已修复 | 员工已提交记录编辑表单移除运单号；路由忽略恶意 `waybill_no`/`waybill_id`，保留原物流绑定及既有照片、备注、数量权限。 |
| 7 | Important | 已修复 | 包货重量解析要求 `math.isfinite(weight)` 且 `weight > 0`，覆盖 NaN、Infinity、-Infinity；物流记录匹配路径也拒绝非有限值。为保持既有“未知重量”导出语义，独立 Waybill 记录仍允许 0，但一旦与草稿匹配便必须满足草稿的正重量规则。 |
| 8 | Important | 已修复 | 正式订单汇总改为“已批准余额 shipped + pending_review”，remaining 在已批准余额上扣 pending；覆盖历史未绑定批准 30 加直接待审 20 得到 shipped 50 / remaining 50。 |
| 9 | Important | 已修复 | 审计 SQL 的 unique/ambiguous/unmatched 共用一个 CTE，使用与 CLI 相同的批准未绑定、规范别名、有效订单行和有效父订单谓词；别名字段统一 BTRIM，重复键按 CLI 的确定性覆盖顺序处理。 |
| 10 | Important | 已修复 | preview/audit 输出预检与 SQLite 数据库路径隔离并拒绝覆盖；apply 先写同目录临时 JSON、flush/fsync 文件及目录，再提交数据库，以原子硬链接无覆盖发布；提交前失败清理，提交后发布失败保留并报告精确恢复路径；commit+rollback 双失败保留原始提交异常。 |
| 11 | Minor | 已修复 | `date.fromisoformat` 前先以完整正则强制 `YYYY-MM-DD`，拒绝紧凑日期。 |
| 12 | Minor | 已修复 | 草稿更新显式刷新 `updated_at`，最近更新排序可见。 |
| 13 | Minor | 已修复 | 实施计划末尾多余空行已删除，并新增格式契约；`git diff --check` 干净。 |

独立复查结论：代码层面无剩余 Critical、Important 或 Minor；其唯一指出的剩项是本报告当时尚未写入。本报告现已补齐。

## TDD RED / GREEN 记录

以下均遵循先添加回归、观察预期失败，再实施最小修复并重跑覆盖测试。

### 1. JavaScript 解析

```text
python -m pytest tests/test_mobile_upload_script.py::test_mobile_app_javascript_passes_node_syntax_check -q
RED: 1 failed；Node 报 SyntaxError: Unexpected token '||'
GREEN: 1 passed
```

### 2. 旧入口与空行服务边界

```text
python -m pytest tests/test_packing_drafts.py -k "empty_cleaned_lines or uses_a_for_update_query or refreshes_submitted_state" tests/test_shipment_order_binding.py -k "empty_cleaned_lines or legacy_mobile_report_post" -q
RED: 4 failed（最后一个 -k 选择 empty_cleaned_lines / legacy_mobile_report_post）
GREEN: 4 passed
```

覆盖 create、update、正式 service 和认证旧 POST；旧 POST 的 RED 会创建/直提数据，GREEN 为 410 且 ShipmentReport/PackingDraft 均不新增。

### 3. 草稿提交与修改竞态

```text
python -m pytest tests/test_packing_drafts.py -k "uses_a_for_update_query or refreshes_submitted_state" -q
RED: 2 failed
GREEN: 2 passed

python -m pytest tests/test_packing_drafts.py -k "mutation_lock or mutations_refresh" -q
RED: 2 failed

python -m pytest tests/test_packing_drafts.py::test_update_and_delete_packing_drafts_use_for_update_queries -q
RED: 1 failed

python -m pytest tests/test_packing_drafts.py -k "update_and_delete_packing_drafts_use_for_update_queries or draft_mutations_refresh_submitted_state" -q
GREEN: 3 passed
```

### 4. 日期、非有限重量、更新时间

```text
python -m pytest tests/test_packing_drafts.py -k "compact_iso_date or non_finite or refreshes_updated_at" -q
RED: 4 failed, 1 passed（-Infinity 已被旧的 <= 0 检查挡住；紧凑日期、NaN、Infinity、updated_at 暴露缺陷）
GREEN: 5 passed
```

### 5. 货拉拉 provenance、trip_mode 与渠道隔离

```text
python -m pytest tests/test_packing_drafts.py -k "huolala or identifier_cannot" -q
RED: 7 failed
GREEN: 7 passed

python -m pytest tests/test_pages.py -k "explicit_existing_trip_provenance or submits_trip_mode_under_one_server_field" -q
RED: 2 failed
GREEN: 2 passed
```

覆盖新建/更新空号生成、已有草稿与 WaybillRecord 权威复制、跨公司、跨日期、快递转货拉拉、货拉拉转快递，以及页面字段名与服务参数。

### 6. 员工提交后物流不可变

```text
python -m pytest tests/test_waybill_no.py::test_worker_my_reports_update_cannot_change_or_relink_waybill tests/test_pages.py::test_mobile_my_reports_shows_update_form_without_photo_delete -q
RED: 2 failed
GREEN: 2 passed
```

### 7. 正式订单汇总

```text
python -m pytest tests/test_shipment_order_binding.py -k "order_summary" -q
RED: 1 failed, 1 passed（历史已批准 30 + 待审 20 被错误算为 30）
GREEN: 2 passed（结果 50 / 50）
```

### 8. 审计 SQL 与 CLI 别名一致性

```text
python -m pytest tests/test_audit_orders_sql.py -q
RED: 2 failed
GREEN: 2 passed

python -m pytest tests/test_audit_orders_sql.py::test_repair_bucket_alias_keys_are_trimmed_paired_and_deterministic tests/test_repair_unique_shipment_bindings.py::test_classification_normalizes_persisted_alias_whitespace -q
RED: 2 failed（修正测试前置条件后，CLI 分类仍有 1 个真实 unmatched 失败）

python -m pytest tests/test_audit_orders_sql.py tests/test_repair_unique_shipment_bindings.py::test_classification_normalizes_persisted_alias_whitespace -q
GREEN: 4 passed
```

### 9. 修复审计持久性与路径安全

首次回归批次覆盖数据库/输出碰撞、现存输出、写失败、提交失败及发布失败：

```text
RED: 7 failed
GREEN: 7 passed
```

显式 SQLite driver URL 路径碰撞：

```text
python -m pytest tests/test_repair_unique_shipment_bindings.py::test_cli_rejects_collision_for_explicit_sqlite_driver_url_before_opening -q
RED: 1 failed
GREEN: 1 passed
```

独立复查追加的目录持久性与无覆盖竞态：

```text
python -m pytest tests/test_repair_unique_shipment_bindings.py -k "fsyncs_temporary_audit_directory or racing_destination or directory_sync_failure" -q
RED: 3 failed

python -m pytest tests/test_repair_unique_shipment_bindings.py -k "fsyncs_temporary_audit_directory or racing_destination or rename_failure or directory_sync_failure" -q
GREEN: 4 passed
```

commit 与 rollback 同时失败：

```text
python -m pytest tests/test_repair_unique_shipment_bindings.py::test_apply_commit_and_rollback_failure_preserves_commit_error_and_removes_temp -q
RED: 1 failed（错误被 rollback 覆盖）

python -m pytest tests/test_repair_unique_shipment_bindings.py -k "commit_and_rollback_failure or commit_failure_removes" -q
GREEN: 2 passed
```

发布后的目录同步失败恢复路径也单独经历 `RED: 1 failed`，随后与 rename recovery 合跑 `GREEN: 2 passed`。

### 10. PostgreSQL 标识锁与 Waybill 写端完整校验

```text
python -m pytest tests/test_packing_drafts.py -k "postgres_logistics_identifier_lock or draft_validation_locks_identifier or waybill_writer_locks_identifier" -q
RED: 3 failed
GREEN: 3 passed

python -m pytest tests/test_packing_drafts.py -k "waybill_create_rejects_same_channel or waybill_update_rejects_retargeting" -q
RED: 6 failed
GREEN: 8 passed（增加 NaN/Infinity 覆盖后）
```

### 11. API 校验异常边界（最终自查追加）

```text
python -m pytest tests/test_logistics.py -k "returns_400" -q
RED: 3 failed（create/update/quick-link 均返回 500）
GREEN: 3 passed（均返回 400，且不创建、不修改、不关联数据）
```

### 12. 计划格式

```text
python -m pytest tests/test_plan_formatting.py -q
RED: 1 failed
GREEN: 1 passed
```

### 13. 受影响区域整合检查

```text
python -m pytest tests/test_packing_drafts.py tests/test_logistics.py tests/test_internal_export_waybills.py -q
GREEN: 48 passed

python -m pytest tests/test_audit_orders_sql.py tests/test_repair_unique_shipment_bindings.py -q
GREEN: 25 passed
```

## 最终必跑门禁

```text
python -m pytest tests -q
331 passed, 15988 warnings in 29.78s

node --check app/static/app.js
exit 0

cd web
npm run build
exit 0；1632 modules transformed；built in 7.64s

git diff --check
exit 0（仅 Git 的 LF→CRLF 工作区提示，无 whitespace error）
```

前端构建产生的 tracked `web/dist` 变化已用 `git restore --worktree -- web/dist` 恢复；唯一新生成的 `web/dist/assets/index-CzyrbLdw.js` 在确认解析路径位于该工作树的 `web/dist` 后删除。最终 `git status --short --untracked-files=all -- web/dist` 无输出。

构建只保留既有非阻断警告：`@vueuse/core` 的 PURE 注释位置提示，以及主 chunk 超过 500 kB。

## 剩余关注点

1. 当前本地测试使用 SQLite，无法证明 PostgreSQL 两会话同时提交同一草稿、以及相同物流标识的真实阻塞顺序；已用生成 SQL、`FOR UPDATE`/`populate_existing` 和 advisory-lock 调用顺序的回归测试覆盖本地可验证部分。上线前仍应在 PostgreSQL staging 做两会话集成检查。
2. 仓库没有 PostgreSQL SQL 执行 fixture；`scripts/audit_orders.sql` 通过 SQL 字符串契约和同语义 CLI 数据夹具验证，仍应在 PostgreSQL staging 对 representative 数据运行只读审计并核对 unique/ambiguous/unmatched 数量。

除上述环境级集成检查外，无已知未修复代码缺陷。
