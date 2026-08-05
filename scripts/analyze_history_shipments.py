"""只读分析：历史导入发货单备注里的发货日期，输出可解析/不可解析报告。

用法（服务器，连生产库）：
    cd /home/ubuntu/zy-shipping && ./.venv/bin/python scripts/analyze_history_shipments.py

脚本不会写任何数据。若运行环境缺少 SUPABASE_DATABASE_URL，
会自动读取仓库根目录的 .env（KEY=VALUE 格式）作为兜底。
"""

import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    load_env_file(repo_root / ".env")

    from app.db import SessionLocal
    from app.models import ShipmentLine, ShipmentReport
    from sqlalchemy import func

    date_qty_re = re.compile(r"(\d{1,2})-(\d{1,2})[^\d]{0,6}发\s*(\d+)\s*件")
    no_date_re = re.compile(r"(?:^|[；;])\s*已发\s*(\d+)\s*件")

    session = SessionLocal()
    try:
        reports = (
            session.query(ShipmentReport)
            .filter(ShipmentReport.ship_date == "历史导入")
            .order_by(ShipmentReport.id)
            .all()
        )
        line_totals = {
            report_id: int(qty or 0)
            for report_id, qty in session.query(
                ShipmentLine.report_id, func.sum(ShipmentLine.quantity)
            )
            .filter(ShipmentLine.report_id.in_([report.id for report in reports]))
            .group_by(ShipmentLine.report_id)
            .all()
        }
    finally:
        session.close()

    categories = {
        "ok_single": [],
        "ok_multi": [],
        "no_date": [],
        "mismatch": [],
        "unparsed": [],
    }
    for report in reports:
        note = report.note or ""
        line_total = line_totals.get(report.id, 0)
        pairs = [
            (f"{m.group(1)}-{m.group(2)}", int(m.group(3)))
            for m in date_qty_re.finditer(note)
        ]
        if not pairs:
            if no_date_re.search(note):
                categories["no_date"].append(report)
            else:
                categories["unparsed"].append(report)
            continue
        total_parsed = sum(qty for _, qty in pairs)
        if len(pairs) == 1 and total_parsed == line_total:
            categories["ok_single"].append(report)
        elif len(pairs) > 1 and total_parsed == line_total:
            categories["ok_multi"].append(report)
        else:
            categories["mismatch"].append((report, pairs, line_total))

    print(f"历史导入发货单总数: {len(reports)}")
    for key, label in [
        ("ok_single", "A. 单日期可同步"),
        ("ok_multi", "B. 多日期可拆分"),
        ("no_date", "C. 只有'已发N件'没有日期"),
        ("mismatch", "D. 数量对不上/含退回等特殊"),
        ("unparsed", "E. 完全无法识别"),
    ]:
        items = categories[key]
        print(f"\n=== {label}: {len(items)} 笔 ===")
        if key in ("ok_single", "ok_multi"):
            for report in items[:8]:
                print(f"  #{report.id} {report.company_name}/{report.style_name} | {report.note}")
            if len(items) > 8:
                print(f"  ... 共 {len(items)} 笔")
        elif key == "mismatch":
            for report, pairs, line_total in items:
                print(
                    f"  #{report.id} {report.company_name}/{report.style_name} | 行合计{line_total} | "
                    f"解析{pairs} | {report.note}"
                )
        else:
            for report in items:
                print(f"  #{report.id} {report.company_name}/{report.style_name} | {report.note}")

    print("\n完成（只读，未写任何数据）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
