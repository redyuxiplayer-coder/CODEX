import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.db import engine_kwargs_for_url  # noqa: E402
from app.models import Company, OrderLine, SalesOrder, ShipmentLine, ShipmentReport  # noqa: E402
from app.services.aliases import canonical_item  # noqa: E402
from app.services.ledger import recompute_for_report  # noqa: E402
from app.services.orders import APPROVED_STATUSES  # noqa: E402


def clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def shipment_base_key(session: Session, report: ShipmentReport, line: ShipmentLine) -> tuple[str, str, str, str]:
    canonical_product, canonical_style = canonical_item(
        session,
        report.company_name,
        report.product_name,
        report.style_name,
    )
    return (
        clean_text(report.company_name),
        canonical_product,
        canonical_style,
        clean_text(line.size),
    )


def candidate_base_key(session: Session, company_name: str, line: OrderLine) -> tuple[str, str, str, str]:
    canonical_product, canonical_style = canonical_item(
        session,
        company_name,
        line.product_name,
        line.style_name,
    )
    return (
        clean_text(company_name),
        canonical_product,
        canonical_style,
        clean_text(line.size),
    )


def build_candidate_map(session: Session) -> dict[tuple[str, str, str, str], list[dict]]:
    rows = (
        session.query(OrderLine, SalesOrder, Company)
        .join(SalesOrder, SalesOrder.id == OrderLine.order_id)
        .join(Company, Company.id == OrderLine.company_id)
        .filter(
            OrderLine.is_active.is_(True),
            OrderLine.order_id.is_not(None),
            SalesOrder.status == "active",
        )
        .order_by(Company.name, SalesOrder.system_order_no, OrderLine.id)
        .all()
    )
    candidates: dict[tuple[str, str, str, str], list[dict]] = {}
    for order_line, order, company in rows:
        key = candidate_base_key(session, company.name, order_line)
        candidates.setdefault(key, []).append(
            {
                "order_line_id": int(order_line.id),
                "order_id": int(order.id),
                "system_order_no": order.system_order_no,
                "order_date": order.order_date,
                "size": clean_text(order_line.size),
                "quantity": int(order_line.quantity or 0),
            }
        )
    return candidates


def classify_unbound_lines(session: Session) -> dict:
    candidates = build_candidate_map(session)
    rows = (
        session.query(ShipmentReport, ShipmentLine)
        .join(ShipmentLine, ShipmentLine.report_id == ShipmentReport.id)
        .filter(
            ShipmentReport.status.in_(APPROVED_STATUSES),
            ShipmentLine.order_line_id.is_(None),
        )
        .order_by(ShipmentReport.id, ShipmentLine.id)
        .all()
    )
    result = {"summary": {"scanned": 0, "unique": 0, "ambiguous": 0, "unmatched": 0}, "unique": [], "ambiguous": [], "unmatched": []}
    for report, line in rows:
        key = shipment_base_key(session, report, line)
        result["summary"]["scanned"] += 1
        item = {
            "shipment_line_id": int(line.id),
            "report_id": int(report.id),
            "ship_date": clean_text(report.ship_date),
            "company_name": clean_text(report.company_name),
            "product_name": clean_text(report.product_name),
            "style_name": clean_text(report.style_name),
            "canonical_product": key[1],
            "canonical_style": key[2],
            "size": clean_text(line.size),
            "quantity": int(line.quantity or 0),
        }
        matches = candidates.get(key, [])
        if len(matches) == 1:
            match = matches[0]
            result["summary"]["unique"] += 1
            result["unique"].append(
                {
                    **item,
                    "order_line_id": match["order_line_id"],
                    "order_id": match["order_id"],
                    "system_order_no": match["system_order_no"],
                    "candidate_system_order_nos": [match["system_order_no"]],
                }
            )
            continue
        if len(matches) > 1:
            result["summary"]["ambiguous"] += 1
            result["ambiguous"].append(
                {
                    **item,
                    "candidate_order_line_ids": [row["order_line_id"] for row in matches],
                    "candidate_order_ids": [row["order_id"] for row in matches],
                    "candidate_system_order_nos": sorted(row["system_order_no"] for row in matches),
                }
            )
            continue
        result["summary"]["unmatched"] += 1
        result["unmatched"].append(item)
    return result


def _report_order_id(report: ShipmentReport) -> int | None:
    if not report.lines:
        return None
    order_ids = set()
    for line in report.lines:
        if line.order_line_id is None or line.order_line is None or line.order_line.order_id is None:
            return None
        order_ids.add(int(line.order_line.order_id))
    if len(order_ids) != 1:
        return None
    return next(iter(order_ids))


def apply_unique_bindings(session: Session, *, commit: bool = True) -> dict:
    classification = classify_unbound_lines(session)
    bindings = []
    affected_report_ids: set[int] = set()
    bound_report_count = 0
    for item in classification["unique"]:
        line = session.get(ShipmentLine, int(item["shipment_line_id"]))
        if line is None or line.order_line_id is not None:
            continue
        line.order_line_id = int(item["order_line_id"])
        bindings.append(
            {
                "shipment_line_id": int(line.id),
                "report_id": int(line.report_id),
                "order_line_id": int(item["order_line_id"]),
                "order_id": int(item["order_id"]),
                "system_order_no": item["system_order_no"],
                "quantity": int(line.quantity or 0),
                "size": clean_text(line.size),
            }
        )
        affected_report_ids.add(int(line.report_id))
    session.flush()

    report_updates = []
    for report_id in sorted(affected_report_ids):
        report = session.get(ShipmentReport, report_id)
        if report is None:
            continue
        before_order_id = report.order_id
        report.order_id = _report_order_id(report)
        if report.order_id != before_order_id:
            bound_report_count += 1
            report_updates.append(
                {
                    "report_id": int(report.id),
                    "before_order_id": before_order_id,
                    "after_order_id": report.order_id,
                }
            )
        recompute_for_report(session, report.id, commit=False)

    if commit:
        session.commit()

    return {
        "summary": classification["summary"],
        "bound_line_count": len(bindings),
        "bound_report_count": bound_report_count,
        "bindings": bindings,
        "report_updates": report_updates,
        "ambiguous": classification["ambiguous"],
        "unmatched": classification["unmatched"],
    }


def resolve_database_url(database: str | None, database_url_env: str | None) -> str:
    if database_url_env:
        value = clean_text(os.environ.get(database_url_env))
        if not value:
            raise ValueError(f"环境变量 {database_url_env} 未设置")
        database = value
    if not database:
        raise ValueError("必须显式提供 --database 或 --database-url-env")
    if "://" in database:
        return database
    return f"sqlite:///{Path(database).resolve().as_posix()}"


def open_session(database_url: str) -> Session:
    engine = create_engine(database_url, **engine_kwargs_for_url(database_url))
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return session_factory()


def write_json(path: str | None, payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    if path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    else:
        print(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repair uniquely matched historical shipment/order bindings.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--database", help="Database URL or SQLite file path.")
    source.add_argument("--database-url-env", help="Environment variable name holding the database URL/path.")
    parser.add_argument("--preview", help="Write preview JSON in read-only mode.")
    parser.add_argument("--apply", action="store_true", help="Apply unique bindings.")
    parser.add_argument("--audit", help="Write apply audit JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.apply and not args.audit:
        parser.error("--apply requires --audit")
    if not args.apply and not args.preview:
        parser.error("preview mode requires --preview")
    if not args.apply and args.audit:
        parser.error("--audit is only valid with --apply")

    database_url = resolve_database_url(args.database, args.database_url_env)
    session = open_session(database_url)
    try:
        if args.apply:
            payload = apply_unique_bindings(session)
            write_json(args.audit, payload)
        else:
            payload = classify_unbound_lines(session)
            write_json(args.preview, payload)
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
