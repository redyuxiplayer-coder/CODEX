import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.db import engine_kwargs_for_url  # noqa: E402
from app.models import Company, OrderLine, SalesOrder, ShipmentLine, ShipmentReport  # noqa: E402
from app.services.aliases import canonical_item  # noqa: E402
from app.services.ledger import order_line_totals, recompute_order_ledger  # noqa: E402
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


def serialize_canonical_key(key: tuple[str, str, str, str]) -> dict[str, str]:
    return {
        "company_name": key[0],
        "canonical_product": key[1],
        "canonical_style": key[2],
        "size": key[3],
    }


def related_order_lines_for_key(session: Session, key: tuple[str, str, str, str]) -> list[dict]:
    company_name, canonical_product, canonical_style, size = key
    rows = (
        session.query(OrderLine, Company, SalesOrder)
        .join(Company, Company.id == OrderLine.company_id)
        .outerjoin(SalesOrder, SalesOrder.id == OrderLine.order_id)
        .filter(
            Company.name == company_name,
            OrderLine.size == size,
            OrderLine.is_active.is_(True),
        )
        .order_by(OrderLine.order_date, OrderLine.id)
        .all()
    )
    related = []
    for order_line, company, order in rows:
        line_key = candidate_base_key(session, company.name, order_line)
        if line_key != key:
            continue
        related.append(
            {
                "order_line_id": int(order_line.id),
                "order_id": int(order.id) if order is not None else None,
                "system_order_no": order.system_order_no if order is not None else "",
                "canonical_key": serialize_canonical_key(key),
            }
        )
    return related


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
    canonical_keys = {
        (
            item["company_name"],
            item["canonical_product"],
            item["canonical_style"],
            item["size"],
        )
        for item in classification["unique"]
    }
    recompute_targets = {}
    before_totals = {}
    for key in sorted(canonical_keys):
        for target in related_order_lines_for_key(session, key):
            order_line_id = target["order_line_id"]
            recompute_targets.setdefault(order_line_id, target)
            before_totals.setdefault(order_line_id, order_line_totals(session, order_line_id))
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
                "canonical_key": serialize_canonical_key(
                    (
                        item["company_name"],
                        item["canonical_product"],
                        item["canonical_style"],
                        item["size"],
                    )
                ),
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

    recomputed_order_lines = []
    for order_line_id in sorted(recompute_targets):
        recompute_order_ledger(session, order_line_id, commit=False)
        recomputed_order_lines.append(
            {
                **recompute_targets[order_line_id],
                "before_totals": before_totals[order_line_id],
                "after_totals": order_line_totals(session, order_line_id),
            }
        )

    if commit:
        session.commit()

    return {
        "summary": classification["summary"],
        "bound_line_count": len(bindings),
        "bound_report_count": bound_report_count,
        "bindings": bindings,
        "report_updates": report_updates,
        "recomputed_order_lines": recomputed_order_lines,
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


class AuditRecoveryError(RuntimeError):
    pass


def sqlite_database_path(database_url: str) -> Path | None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).expanduser().resolve()


def preflight_output_path(database_url: str, path: str) -> Path:
    output_path = Path(path).expanduser().resolve()
    database_path = sqlite_database_path(database_url)
    same_as_database = database_path is not None and output_path == database_path
    if not same_as_database and database_path is not None and output_path.exists() and database_path.exists():
        same_as_database = os.path.samefile(output_path, database_path)
    if same_as_database:
        raise ValueError("输出路径不能与 SQLite 数据库相同")
    if output_path.exists():
        raise FileExistsError(f"输出文件已存在，拒绝覆盖：{output_path}")
    return output_path


def _remove_temp_file(temp_path: Path | None) -> None:
    if temp_path is not None:
        temp_path.unlink(missing_ok=True)


def _rollback_and_remove_temp(session: Session, temp_path: Path | None) -> None:
    try:
        session.rollback()
    except Exception as exc:
        print(f"回滚失败，保留原始错误：{exc}", file=sys.stderr)
    try:
        _remove_temp_file(temp_path)
    except Exception as exc:
        print(f"临时审计文件清理失败：{exc}", file=sys.stderr)


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    directory_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def write_temp_json(output_path: Path, payload: dict) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
    )
    temp_path = Path(temp_name).resolve()
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(output_path.parent)
    except Exception:
        _remove_temp_file(temp_path)
        raise
    return temp_path


def publish_temp_json(temp_path: Path, output_path: Path) -> None:
    if output_path.exists():
        raise FileExistsError(f"输出文件已存在，拒绝覆盖：{output_path}")
    try:
        os.link(temp_path, output_path)
    except FileExistsError as exc:
        raise FileExistsError(f"输出文件已存在，拒绝覆盖：{output_path}") from exc
    _fsync_directory(output_path.parent)
    temp_path.unlink()
    _fsync_directory(output_path.parent)


def write_json(path: str | None, payload: dict) -> None:
    if not path:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False))
        return
    output_path = Path(path).expanduser().resolve()
    temp_path = write_temp_json(output_path, payload)
    try:
        publish_temp_json(temp_path, output_path)
    except Exception:
        _remove_temp_file(temp_path)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repair uniquely matched historical shipment/order bindings.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--database", help="Database URL or SQLite file path.")
    source.add_argument("--database-url-env", help="Environment variable name holding the database URL/path.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--preview", help="Write preview JSON in read-only mode.")
    action.add_argument("--apply", action="store_true", help="Apply unique bindings.")
    parser.add_argument("--audit", help="Write apply audit JSON.")
    parser.add_argument(
        "--confirm-production-backup",
        action="store_true",
        help="Required for non-SQLite apply runs after a verified backup.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.apply and not args.audit:
        parser.error("--apply requires --audit")
    if not args.apply and args.audit:
        parser.error("--audit is only valid with --apply")

    database_url = resolve_database_url(args.database, args.database_url_env)
    if args.apply and not database_url.startswith("sqlite") and not args.confirm_production_backup:
        raise ValueError("Non-SQLite apply requires --confirm-production-backup")
    output_path = preflight_output_path(database_url, args.audit if args.apply else args.preview)
    session = open_session(database_url)
    try:
        if args.apply:
            temp_path = None
            try:
                payload = apply_unique_bindings(session, commit=False)
                temp_path = write_temp_json(output_path, payload)
            except Exception:
                _rollback_and_remove_temp(session, temp_path)
                raise
            try:
                session.commit()
            except Exception:
                _rollback_and_remove_temp(session, temp_path)
                raise
            try:
                publish_temp_json(temp_path, output_path)
            except Exception as exc:
                recovery_path = temp_path.resolve() if temp_path.exists() else output_path.resolve()
                message = f"数据库已提交，但审计文件发布失败；审计文件恢复路径：{recovery_path}"
                print(message, file=sys.stderr)
                raise AuditRecoveryError(message) from exc
        else:
            payload = classify_unbound_lines(session)
            write_json(str(output_path), payload)
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
