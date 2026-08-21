# Internal Export Waybill Sheet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在全部公司内部总表和单个公司内部版 Excel 中新增“快递记录”工作表，每张快递单一行显示快递单号、重量和实际发货日期。

**Architecture:** 在 `app/services/exports.py` 增加一个直接查询 `WaybillRecord` 主表的工作表生成函数，由两种内部导出函数调用。专项测试用内存 SQLite 创建已关联和未关联的快递记录，打开实际生成的 `.xlsx` 检查内容、排序、筛选和样式，同时回归验证客户版工作表列表未变化。

**Tech Stack:** Python 3、SQLAlchemy、openpyxl、pytest、SQLite（测试）、PostgreSQL（生产）

## Global Constraints

- 工作表名称固定为 `快递记录`。
- 列顺序固定为 `快递单号`、`重量(kg)`、`发货日期`。
- 时间使用 `WaybillRecord.ship_date`，不使用 `created_at`。
- 全部公司内部总表包含所有 `waybill_records`；单公司内部版仅包含 `company_name` 精确匹配的记录。
- 每张快递单只导出一行，未挂靠发货明细的快递单也必须导出。
- 先按发货日期升序、再按快递单号升序排序。
- `weight_kg` 为 `0` 或未填写时导出空白单元格。
- 无数据时仍创建工作表和表头。
- 复用现有 `style_sheet` 样式。
- 客户版、发货流水、订单余额计算和数据库结构不变，不新增数据库迁移。

---

## File Structure

- Create: `tests/test_internal_export_waybills.py` — 覆盖内部总表、单公司内部版和客户版不变的导出回归测试。
- Modify: `app/services/exports.py` — 定义 `add_waybill_records_sheet` 并接入两种内部导出。
- Modify: `E:\CODEX\1-项目\仓库系统管理\07-更新日志.md` — 记录功能、验证和部署结果。
- Create: `E:\CODEX\raw\2026-08-21-内部导出新增快递记录页.md` — 仅在部署完成后新增当天事实记录，不修改既有 raw 文件。
- Modify: `E:\CODEX\wiki\发货系统生产架构.md` — 记录生产已启用“快递记录”页，保持 PostgreSQL 直连、无 Supabase 的现状描述。

### Task 1: 用专项测试锁定快递记录页契约

**Files:**
- Create: `tests/test_internal_export_waybills.py`

**Interfaces:**
- Consumes: `export_total_workbook(session, output_path) -> Path`、`export_company_workbook(session, company_name, output_path) -> Path`、`export_customer_total_workbook(session, output_path) -> Path`、`export_customer_company_workbook(session, company_name, output_path) -> Path`。
- Produces: 一组会在功能尚未实现时失败、实现完成后通过的 Excel 行为测试。

- [ ] **Step 1: 写内部总表失败测试，覆盖表头、排序、零重量、未关联记录、去重和样式**

```python
from pathlib import Path

from openpyxl import load_workbook

from app.models import ShipmentReport, User
from app.services.exports import (
    export_company_workbook,
    export_customer_company_workbook,
    export_customer_total_workbook,
    export_total_workbook,
)
from app.services.logistics import create_waybill_record, link_reports_to_waybill


def _create_admin(db_session) -> User:
    admin = User(
        username="waybill_export_admin",
        display_name="老板",
        password_hash="x",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    return admin


def _add_report(db_session, admin: User, company_name: str, ship_date: str) -> ShipmentReport:
    report = ShipmentReport(
        user_id=admin.id,
        ship_date=ship_date,
        company_name=company_name,
        product_name="测试产品",
        style_name="测试款式",
        status="auto_approved",
    )
    db_session.add(report)
    db_session.commit()
    return report


def test_internal_total_export_adds_sorted_unique_waybill_sheet(db_session, tmp_path: Path):
    admin = _create_admin(db_session)
    zero_weight = create_waybill_record(
        db_session, admin.id, "甲公司", "2026-07-02", "WB-200", weight_kg=0
    )
    create_waybill_record(
        db_session, admin.id, "乙公司", "2026-07-01", "WB-300", weight_kg=12.5
    )
    linked = create_waybill_record(
        db_session, admin.id, "甲公司", "2026-07-01", "WB-100", weight_kg=8
    )
    first_report = _add_report(db_session, admin, "甲公司", "2026-07-01")
    second_report = _add_report(db_session, admin, "甲公司", "2026-07-01")
    link_reports_to_waybill(db_session, linked.id, [first_report.id, second_report.id])

    output = export_total_workbook(db_session, tmp_path / "内部总表.xlsx")

    workbook = load_workbook(output)
    assert workbook.sheetnames == ["订单发货明细", "发货流水", "未发货明细", "快递记录"]
    sheet = workbook["快递记录"]
    assert list(sheet.values) == [
        ("快递单号", "重量(kg)", "发货日期"),
        ("WB-100", 8, "2026-07-01"),
        ("WB-300", 12.5, "2026-07-01"),
        ("WB-200", None, "2026-07-02"),
    ]
    assert sheet.freeze_panes == "A2"
    assert sheet["A1"].font.bold is True
    assert zero_weight.weight_kg == 0
```

- [ ] **Step 2: 写单公司筛选和空数据工作表失败测试**

```python
def test_internal_company_export_filters_waybills_and_keeps_empty_sheet(db_session, tmp_path: Path):
    admin = _create_admin(db_session)
    create_waybill_record(
        db_session, admin.id, "甲公司", "2026-07-02", "A-002", weight_kg=6.5
    )
    create_waybill_record(
        db_session, admin.id, "甲公司", "2026-07-01", "A-001", weight_kg=5
    )
    create_waybill_record(
        db_session, admin.id, "乙公司", "2026-07-01", "B-001", weight_kg=9
    )

    company_output = export_company_workbook(db_session, "甲公司", tmp_path / "甲公司内部版.xlsx")
    empty_output = export_company_workbook(db_session, "无快递公司", tmp_path / "空内部版.xlsx")

    company_workbook = load_workbook(company_output)
    assert company_workbook.sheetnames == ["订单发货明细", "发货流水", "快递记录"]
    assert list(company_workbook["快递记录"].values) == [
        ("快递单号", "重量(kg)", "发货日期"),
        ("A-001", 5, "2026-07-01"),
        ("A-002", 6.5, "2026-07-02"),
    ]
    assert list(load_workbook(empty_output)["快递记录"].values) == [
        ("快递单号", "重量(kg)", "发货日期"),
    ]
```

- [ ] **Step 3: 写客户版工作表列表不变的回归测试**

```python
def test_customer_exports_do_not_add_waybill_sheet(db_session, tmp_path: Path):
    admin = _create_admin(db_session)
    create_waybill_record(
        db_session, admin.id, "甲公司", "2026-07-01", "A-001", weight_kg=5
    )

    total_output = export_customer_total_workbook(db_session, tmp_path / "客户总表.xlsx")
    company_output = export_customer_company_workbook(
        db_session, "甲公司", tmp_path / "甲公司客户版.xlsx"
    )

    assert load_workbook(total_output).sheetnames == ["客户发货明细", "未发货明细", "发货明细"]
    assert load_workbook(company_output).sheetnames == ["客户发货明细", "发货明细"]
```

- [ ] **Step 4: 运行专项测试并确认按预期失败**

Run: `python -m pytest tests/test_internal_export_waybills.py -q`

Expected: 3 个测试因工作簿中不存在 `快递记录` 工作表而失败；不得出现测试数据构造错误。

- [ ] **Step 5: 提交失败测试**

```bash
git add tests/test_internal_export_waybills.py
git commit -m "test: define internal waybill export contract"
```

### Task 2: 在两种内部导出中生成快递记录页

**Files:**
- Modify: `app/services/exports.py:8`
- Modify: `app/services/exports.py:305-366`
- Test: `tests/test_internal_export_waybills.py`

**Interfaces:**
- Consumes: SQLAlchemy `Session`、`WaybillRecord` 模型、现有 `style_sheet(ws) -> None`。
- Produces: `add_waybill_records_sheet(wb: Workbook, session: Session, company_name: str | None = None) -> None`。

- [ ] **Step 1: 导入 `WaybillRecord` 并增加工作表生成函数**

将模型导入改为：

```python
from app.models import ShipmentReport, WaybillRecord
```

在 `add_shipments_sheet` 后增加：

```python
def add_waybill_records_sheet(
    wb: Workbook,
    session: Session,
    company_name: str | None = None,
) -> None:
    ws = wb.create_sheet("快递记录")
    ws.append(["快递单号", "重量(kg)", "发货日期"])
    query = session.query(WaybillRecord)
    if company_name is not None:
        query = query.filter(WaybillRecord.company_name == company_name)
    records = query.order_by(WaybillRecord.ship_date, WaybillRecord.waybill_no).all()
    for record in records:
        ws.append([
            record.waybill_no,
            record.weight_kg or None,
            record.ship_date,
        ])
    style_sheet(ws)
```

- [ ] **Step 2: 只在内部总表和单公司内部版中调用新函数**

在 `export_total_workbook` 中、保存文件之前加入：

```python
    add_waybill_records_sheet(wb, session)
```

在 `export_company_workbook` 中、保存文件之前加入：

```python
    add_waybill_records_sheet(wb, session, company_name=company_name)
```

不要修改 `export_customer_total_workbook`、`export_customer_company_workbook`、`export_unshipped_workbook`、`export_daily_shipments_workbook` 或 `export_employee_shipments_workbook`。

- [ ] **Step 3: 运行专项测试并确认全部通过**

Run: `python -m pytest tests/test_internal_export_waybills.py -q`

Expected: `3 passed`。

- [ ] **Step 4: 运行既有客户导出回归测试**

Run: `python -m pytest tests/test_customer_export.py -q`

Expected: 既有测试全部通过，且客户版精确工作表列表断言不变。

- [ ] **Step 5: 提交最小实现**

```bash
git add app/services/exports.py
git commit -m "feat: add waybill sheet to internal exports"
```

### Task 3: 完整验证、部署腾讯云并核对生产导出

**Files:**
- Test: full repository test suite
- Modify: `E:\CODEX\1-项目\仓库系统管理\07-更新日志.md`
- Create: `E:\CODEX\raw\2026-08-21-内部导出新增快递记录页.md`
- Modify: `E:\CODEX\wiki\发货系统生产架构.md`

**Interfaces:**
- Consumes: Task 2 已通过测试的提交、服务器 `ubuntu@139.155.144.14`、应用目录 `/home/ubuntu/zy-shipping`、服务 `zy-shipping`。
- Produces: 已推送并部署的生产版本、生产导出验证证据、通过 lint 的 Obsidian 记忆更新。

- [ ] **Step 1: 运行完整测试套件**

Run: `python -m pytest -q`

Expected: 全部测试通过，无失败、错误或跳过数异常；记录实际通过数量。

- [ ] **Step 2: 检查差异和仓库状态**

Run: `git diff HEAD~2 --check`

Expected: 无输出。

Run: `git status --short`

Expected: 无未提交文件。

- [ ] **Step 3: 推送当前分支到远端**

Run: `git push origin main`

Expected: 远端 `main` 更新到本地最新实现提交。

- [ ] **Step 4: 在服务器生成部署前备份并更新代码**

Run:

```bash
ssh -i C:\Users\Administrator\.ssh\zy_shipping_ed25519 ubuntu@139.155.144.14 'set -e; stamp=$(date +%Y%m%d-%H%M%S); backup=/home/ubuntu/backups/zy-shipping/$stamp; mkdir -p $backup; sudo systemctl stop zy-shipping; trap "sudo systemctl start zy-shipping" EXIT; sudo -u postgres pg_dump -d zy_shipping > $backup/zy_shipping.sql; tar -czf $backup/local-files.tar.gz -C /home/ubuntu/zy-shipping data/uploads data/waybills; cd /home/ubuntu/zy-shipping; git fetch origin main; git checkout main; git pull --ff-only origin main; sudo systemctl start zy-shipping; trap - EXIT; sudo systemctl is-active zy-shipping'
```

Expected: 备份命令成功、`git pull` 快进到最新提交、最后输出 `active`。此功能无数据库结构变更，不运行迁移。

- [ ] **Step 5: 核验生产服务和实际内部导出**

Run: `ssh -i C:\Users\Administrator\.ssh\zy_shipping_ed25519 ubuntu@139.155.144.14 "curl -fsS http://127.0.0.1:8000/health || curl -fsS http://127.0.0.1:8000/"`

Expected: HTTP 请求成功。

随后在服务器加载生产 `.env`，从 `waybill_records` 选择第一家有快递记录的公司，直接调用与网页入口相同的导出服务生成两种内部版和一个客户版，再用 openpyxl 检查：

```python
from openpyxl import load_workbook
from pathlib import Path

from app.db import SessionLocal
from app.models import WaybillRecord
from app.services.exports import (
    export_company_workbook,
    export_customer_company_workbook,
    export_total_workbook,
)

output_dir = Path("/tmp/waybill-export-verification")
output_dir.mkdir(exist_ok=True)
with SessionLocal() as session:
    first_company = (
        session.query(WaybillRecord.company_name)
        .order_by(WaybillRecord.company_name)
        .first()
    )
    assert first_company is not None
    company_name = first_company[0]
    internal_total = export_total_workbook(session, output_dir / "internal-total.xlsx")
    internal_company = export_company_workbook(
        session, company_name, output_dir / "internal-company.xlsx"
    )
    customer_company = export_customer_company_workbook(
        session, company_name, output_dir / "customer-company.xlsx"
    )

for path in (internal_total, internal_company):
    workbook = load_workbook(path, read_only=True, data_only=True)
    assert "快递记录" in workbook.sheetnames
    sheet = workbook["快递记录"]
    assert next(sheet.iter_rows(values_only=True)) == ("快递单号", "重量(kg)", "发货日期")

assert "快递记录" not in load_workbook(customer_company, read_only=True).sheetnames
```

通过以下 PowerShell 命令把上面脚本作为标准输入交给生产 Python；执行前将脚本保存为本机临时文件 `C:\Users\Administrator\AppData\Local\Temp\verify_waybill_export.py`，验证后保留该临时文件即可：

```powershell
Get-Content -LiteralPath 'C:\Users\Administrator\AppData\Local\Temp\verify_waybill_export.py' -Raw |
  ssh -i 'C:\Users\Administrator\.ssh\zy_shipping_ed25519' ubuntu@139.155.144.14 `
    "cd /home/ubuntu/zy-shipping && set -a && . ./.env && set +a && ./.venv/bin/python -"
```

Expected: 两个生产导出均包含正确表头；抽查行按日期和单号升序、0 重量为空，客户版导出不含 `快递记录`。

- [ ] **Step 6: 更新项目记忆并执行 wiki 校验**

先重新读取 `E:\CODEX\AGENTS.md`，然后：

- 新建 2026-08-21 raw 事实记录，写明提交号、测试数量、部署时间和生产核验结果；
- 更新项目 wiki 现状页，注明两种内部导出已新增 `快递记录`，客户版不变；
- 更新项目更新日志；
- 不写入 SSH 私钥、密码、数据库口令或 `.env` 内容。

Run: `python E:\CODEX\scripts\lint-wiki.py`

Expected: lint 成功，无错误。

- [ ] **Step 7: 确认应用仓库干净且 Obsidian 记忆已进入同步目录**

```powershell
git -C 'E:\CODEX\1-项目\仓库系统管理\订单报表系统' status --short
Get-Item -LiteralPath `
  'E:\CODEX\raw\2026-08-21-内部导出新增快递记录页.md', `
  'E:\CODEX\wiki\发货系统生产架构.md', `
  'E:\CODEX\1-项目\仓库系统管理\07-更新日志.md'
```

Expected: 应用 Git 工作区无未提交文件，三个记忆文件均存在于 `E:\CODEX` Obsidian 官方云同步目录；不把库外文件错误暂存到应用仓库。
