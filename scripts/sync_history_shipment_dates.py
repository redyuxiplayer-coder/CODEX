"""把历史导入发货单备注里的日期同步进系统。

用法：
    预览（不写库）：
        ./.venv/bin/python scripts/sync_history_shipment_dates.py
    真正执行：
        ./.venv/bin/python scripts/sync_history_shipment_dates.py --apply

规则：
  A 类：备注一个"MM-DD 发 N件"且数量=行合计 → ship_date 改为 2026-MM-DD
  B 类：备注多个日期且合计=行合计 → 拆成多个发货单（原单保留第一段，其余新建）
  C 类：人工填写的日期（MANUAL_DATES，来自用户填表）
  D 类：特殊处理（SPECIAL_DATES）
"""

import re
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.config import DATABASE_URL  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import ShipmentLine, ShipmentReport  # noqa: E402

DATE_QTY_RE = re.compile(r"(\d{1,2})-(\d{1,2})[^\d]{0,6}发\s*(\d+)\s*件")
NO_DATE_RE = re.compile(r"(?:^|[；;])\s*已发\s*(\d+)\s*件")
YEAR = 2026

# C 类：用户填写的真实发货日期（2026 年）
MANUAL_DATES: dict[int, list[tuple[str, int]]] = {
    119: [("2026-06-19", 150)],
    120: [("2026-06-19", 250)],
    121: [("2026-06-19", 150)],
    122: [("2026-06-17", 280)],
    123: [("2026-06-17", 280)],
    130: [("2026-06-14", 450)],
    131: [("2026-06-14", 400)],
    132: [("2026-06-14", 120)],
    133: [("2026-06-19", 400)],
    134: [("2026-06-19", 350)],
    135: [("2026-06-16", 220)],
    136: [("2026-06-16", 450)],
    137: [("2026-06-16", 175), ("2026-06-17", 175)],
    138: [("2026-06-16", 300)],
    139: [("2026-06-24", 70)],
    140: [("2026-06-24", 500)],
    141: [("2026-06-24", 500)],
    142: [("2026-06-24", 150)],
    124: [("2026-06-10", 150), ("2026-06-11", 150), ("2026-06-12", 224)],
    125: [("2026-06-08", 450), ("2026-06-10", 300), ("2026-06-11", 150), ("2026-06-12", 513)],
    126: [("2026-06-08", 325), ("2026-06-10", 299), ("2026-06-11", 150), ("2026-06-12", 600), ("2026-06-16", 494)],
    127: [("2026-06-08", 302), ("2026-06-10", 150), ("2026-06-11", 285), ("2026-06-12", 150), ("2026-06-16", 505)],
    128: [("2026-06-08", 125), ("2026-06-11", 123), ("2026-06-16", 399)],
    129: [("2026-06-16", 90)],
}

# D 类：特殊处理
# 41: 已发573件(无日期) + 07-13 发27件 → 27件拆出新单，原单573件保持"历史导入"
# 48: 07-06 发286已退回、07-09 发119、07-11 发281 → 净400=119+281，拆两单
SPECIAL_DATES: dict[int, list[tuple[str, int]]] = {
    41: [("2026-07-13", 27)],
    48: [("2026-07-09", 119), ("2026-07-11", 281)],
}


def to_full_date(mm_dd: str) -> str:
    parsed = datetime.strptime(f"{YEAR}-{mm_dd}", "%Y-%m-%d")
    return parsed.strftime("%Y-%m-%d")


def apply_targets(session, report: ShipmentReport, targets: list[tuple[str, int]]) -> int:
    """把日期目标应用到发货单：单日期直接改，多日期拆分，数量不足的保留原单。"""
    lines = list(report.lines)
    line_total = sum(int(line.quantity or 0) for line in lines)
    total = sum(qty for _, qty in targets)
    if total > line_total:
        raise ValueError(f"#{report.id} 拆分数量 {total} 超过行合计 {line_total}")

    def make_new_report(date: str, qty: int) -> None:
        new_report = ShipmentReport(
            user_id=report.user_id,
            ship_date=date,
            company_name=report.company_name,
            product_name=report.product_name,
            style_name=report.style_name,
            waybill_no=report.waybill_no or "",
            note=report.note,
            status=report.status,
            review_reason=report.review_reason,
            created_at=report.created_at,
        )
        session.add(new_report)
        session.flush()
        for line in lines:
            session.add(
                ShipmentLine(
                    report_id=new_report.id,
                    order_line_id=line.order_line_id,
                    size=line.size,
                    quantity=qty,
                )
            )

    if total == line_total and len(targets) == 1:
        report.ship_date = targets[0][0]
        return 1
    if total < line_total:
        # 部分拆分：带日期的新建，原单保留剩余（ship_date 保持"历史导入"）
        for date, qty in targets:
            make_new_report(date, qty)
        if lines:
            lines[0].quantity = line_total - total
        return len(targets)
    # 完整拆分：第一段留在原单，其余新建
    first_date, first_qty = targets[0]
    report.ship_date = first_date
    if lines:
        lines[0].quantity = first_qty
    for date, qty in targets[1:]:
        make_new_report(date, qty)
    return len(targets)


def main() -> int:
    apply = "--apply" in sys.argv
    if DATABASE_URL.startswith("sqlite"):
        print(f"注意：当前连接 SQLite（{DATABASE_URL}）")
    else:
        print(f"已连接生产库: {DATABASE_URL.split('@')[-1].split('/')[0]}")
    if not apply:
        print("== 预览模式（未写库），加 --apply 才执行 ==")

    session = SessionLocal()
    try:
        reports = (
            session.query(ShipmentReport)
            .filter(ShipmentReport.ship_date == "历史导入")
            .order_by(ShipmentReport.id)
            .all()
        )
        a_ids, b_plans, unresolved = [], [], []
        for report in reports:
            if report.id in MANUAL_DATES or report.id in SPECIAL_DATES:
                continue
            line_total = sum(int(line.quantity or 0) for line in report.lines)
            pairs = [
                (f"{m.group(1)}-{m.group(2)}", int(m.group(3)))
                for m in DATE_QTY_RE.finditer(report.note or "")
            ]
            if not pairs:
                unresolved.append(report.id)
                continue
            total_parsed = sum(qty for _, qty in pairs)
            if len(pairs) == 1 and total_parsed == line_total:
                a_ids.append((report.id, to_full_date(pairs[0][0])))
            elif len(pairs) > 1 and total_parsed == line_total:
                b_plans.append((report, pairs))
            else:
                unresolved.append(report.id)

        print(f"\nA 类（单日期改 ship_date）: {len(a_ids)} 笔")
        print(f"B 类（多日期拆分）: {len(b_plans)} 笔")
        print(f"C 类（人工填日期）: {len(MANUAL_DATES)} 笔")
        print(f"D 类（特殊处理）: {len(SPECIAL_DATES)} 笔")
        print(f"仍未处理: {len(unresolved)} 笔 -> {unresolved}")

        if not apply:
            return 0

        for report_id, full_date in a_ids:
            session.get(ShipmentReport, report_id).ship_date = full_date

        for report, pairs in b_plans:
            apply_targets(session, report, [(to_full_date(mm_dd), qty) for mm_dd, qty in pairs])

        for report_id, targets in MANUAL_DATES.items():
            report = session.get(ShipmentReport, report_id)
            if report is not None:
                apply_targets(session, report, targets)

        for report_id, targets in SPECIAL_DATES.items():
            report = session.get(ShipmentReport, report_id)
            if report is not None:
                apply_targets(session, report, targets)

        session.commit()
        print("\n已执行完成。")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
