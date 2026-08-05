"""把历史导入发货单备注里的日期同步进系统（A/B 类），C/D 类只列出不动。

用法：
    预览（不写库）：
        ./.venv/bin/python scripts/sync_history_shipment_dates.py
    真正执行：
        ./.venv/bin/python scripts/sync_history_shipment_dates.py --apply

规则：
  A 类：备注只有一个"MM-DD 发 N件"且数量=行合计 → ship_date 改为 2026-MM-DD
  B 类：备注多个日期且合计=行合计 → 拆成多个发货单（原单保留为第一段，其余新建）
  C 类：只有"已发 N件"没日期 → 不动（列出）
  D 类：数量对不上/含退回 → 不动（列出）
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


def parse_note(note: str) -> list[tuple[str, int]]:
    return [
        (f"{m.group(1)}-{m.group(2)}", int(m.group(3)))
        for m in DATE_QTY_RE.finditer(note or "")
    ]


def to_full_date(mm_dd: str) -> str:
    parsed = datetime.strptime(f"{YEAR}-{mm_dd}", "%Y-%m-%d")
    return parsed.strftime("%Y-%m-%d")


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
        a_ids, b_plans, c_ids, d_ids = [], [], [], []
        for report in reports:
            line_total = sum(int(line.quantity or 0) for line in report.lines)
            pairs = parse_note(report.note)
            if not pairs:
                if NO_DATE_RE.search(report.note or ""):
                    c_ids.append(report.id)
                else:
                    d_ids.append(report.id)
                continue
            total_parsed = sum(qty for _, qty in pairs)
            if len(pairs) == 1 and total_parsed == line_total:
                a_ids.append((report.id, to_full_date(pairs[0][0])))
            elif len(pairs) > 1 and total_parsed == line_total:
                b_plans.append((report, pairs))
            else:
                d_ids.append(report.id)

        print(f"\nA 类（单日期改 ship_date）: {len(a_ids)} 笔")
        print(f"B 类（多日期拆分）: {len(b_plans)} 笔")
        print(f"C 类（无日期，不动）: {len(c_ids)} 笔 -> {c_ids}")
        print(f"D 类（特殊，不动）: {len(d_ids)} 笔 -> {d_ids}")

        if not apply:
            return 0

        for report_id, full_date in a_ids:
            report = session.get(ShipmentReport, report_id)
            report.ship_date = full_date

        for report, pairs in b_plans:
            lines = list(report.lines)
            first_date, first_qty = pairs[0]
            report.ship_date = to_full_date(first_date)
            if lines:
                lines[0].quantity = first_qty
            for mm_dd, qty in pairs[1:]:
                new_report = ShipmentReport(
                    user_id=report.user_id,
                    ship_date=to_full_date(mm_dd),
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
        session.commit()
        print("\n已执行完成。")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
