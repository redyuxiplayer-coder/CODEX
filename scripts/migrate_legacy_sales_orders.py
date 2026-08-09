"""Preview and apply an explicitly reviewed legacy-order migration.

Preview mode never writes to the database and never generates system order
numbers. Apply mode accepts only values present in the reviewed decision file.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.models import (  # noqa: E402
    Company,
    OrderLine,
    SalesOrder,
    ShipmentPhoto,
    ShipmentReport,
    Spu,
    WaybillRecord,
)
from app.services.sales_orders import build_system_order_no  # noqa: E402
from app.services.spus import normalize_code  # noqa: E402


def _group_key(line: OrderLine) -> tuple:
    return (
        line.company_id,
        line.product_name,
        line.style_name,
        line.batch or "",
        line.order_date or "",
    )


def preview_legacy_orders(session: Session) -> dict:
    lines = (
        session.query(OrderLine)
        .filter(OrderLine.order_id.is_(None), OrderLine.is_active.is_(True))
        .order_by(OrderLine.company_id, OrderLine.order_date, OrderLine.batch, OrderLine.id)
        .all()
    )
    grouped: dict[tuple, list[OrderLine]] = defaultdict(list)
    for line in lines:
        grouped[_group_key(line)].append(line)

    exact_spus = {(spu.product_name, spu.style_name): spu for spu in session.query(Spu).filter(Spu.is_active.is_(True)).all()}
    groups = []
    line_group_index = {}
    for rows in grouped.values():
        first = rows[0]
        spu = exact_spus.get((first.product_name, first.style_name))
        reasons = []
        if not first.order_date:
            reasons.append("missing_order_date")
        if not first.company.code:
            reasons.append("missing_company_code")
        if spu is None:
            reasons.append("missing_spu")
        item = {
            "order_line_ids": [row.id for row in rows],
            "company_id": first.company_id,
            "company": first.company.name,
            "product": first.product_name,
            "style": first.style_name,
            "sizes": sorted({row.size for row in rows}),
            "batch": first.batch or "",
            "order_date": first.order_date or "",
            "candidate_spu_code": spu.code if spu else "",
            "candidate_color_name": "",
            "candidate_color_code": "",
            "linked_shipment_report_ids": [],
            "reasons": reasons,
        }
        index = len(groups)
        groups.append(item)
        for row in rows:
            line_group_index[row.id] = index

    for report in session.query(ShipmentReport).order_by(ShipmentReport.id).all():
        indexes = {
            line_group_index[line.order_line_id]
            for line in report.lines
            if line.order_line_id in line_group_index
        }
        for index in indexes:
            groups[index]["linked_shipment_report_ids"].append(report.id)
        if len(indexes) > 1:
            for index in indexes:
                if "cross_candidate_shipment" not in groups[index]["reasons"]:
                    groups[index]["reasons"].append("cross_candidate_shipment")
        for shipment_line in (line for line in report.lines if not line.order_line_id):
            matches = [
                index
                for index, group in enumerate(groups)
                if group["company"] == report.company_name
                and group["product"] == report.product_name
                and group["style"] == report.style_name
                and shipment_line.size in group["sizes"]
            ]
            if len(matches) == 1:
                index = matches[0]
                if report.id not in groups[index]["linked_shipment_report_ids"]:
                    groups[index]["linked_shipment_report_ids"].append(report.id)
            else:
                for index in matches:
                    if "ambiguous_unbound_shipment" not in groups[index]["reasons"]:
                        groups[index]["reasons"].append("ambiguous_unbound_shipment")

    needs_review = [group for group in groups if group["reasons"]]
    return {
        "groups": groups,
        "needs_review": needs_review,
        "summary": {
            "legacy_order_line_count": len(lines),
            "candidate_group_count": len(groups),
            "needs_review_count": len(needs_review),
        },
    }


def _decision_rows(session: Session, decision: dict) -> list[OrderLine]:
    ids = sorted({int(value) for value in decision.get("order_line_ids", [])})
    rows = session.query(OrderLine).filter(OrderLine.id.in_(ids)).order_by(OrderLine.id).all() if ids else []
    if len(rows) != len(ids):
        raise ValueError("决定文件包含不存在的订单行")
    if any(row.order_id is not None for row in rows):
        raise ValueError("决定文件包含已迁移的订单行")
    if len({(row.company_id, row.product_name, row.style_name) for row in rows}) != 1:
        raise ValueError("一个决定分组只能包含同一公司、产品和款式")
    return rows


def apply_decisions(session: Session, decisions: list[dict]) -> dict:
    legacy_ids = {
        row_id
        for (row_id,) in session.query(OrderLine.id)
        .filter(OrderLine.order_id.is_(None), OrderLine.is_active.is_(True))
        .all()
    }
    decided_ids = []
    prepared = []
    company_codes = {}
    for decision in decisions:
        rows = _decision_rows(session, decision)
        if not rows:
            raise ValueError("每个决定至少包含一个订单行")
        decided_ids.extend(row.id for row in rows)
        company_code = normalize_code(decision.get("company_code", ""))
        spu_code = normalize_code(decision.get("spu_code", ""))
        order_date = str(decision.get("order_date", "")).strip()
        product_name = str(decision.get("product_name", rows[0].product_name)).strip()
        style_name = str(decision.get("style_name", rows[0].style_name)).strip()
        color_name = str(decision.get("color_name", "")).strip()
        color_code_raw = str(decision.get("color_code", "")).strip()
        color_code = normalize_code(color_code_raw) if color_code_raw else ""
        if not company_code or not spu_code or not product_name or not style_name or not order_date:
            raise ValueError("公司代码、SPU 编码、产品、款式和下单日期必须明确填写")
        if bool(color_name) != bool(color_code):
            raise ValueError("颜色名称和颜色编码必须同时填写或同时留空")
        company = rows[0].company
        prior = company_codes.setdefault(company.id, company_code)
        if prior != company_code:
            raise ValueError("同一公司的公司代码必须一致")
        raw_customer_skus = decision.get("customer_skus", {})
        if not isinstance(raw_customer_skus, dict):
            raise ValueError("客户 SKU 必须按订单行 ID 填写")
        row_ids = {row.id for row in rows}
        customer_skus = {int(row_id): str(value).strip() for row_id, value in raw_customer_skus.items()}
        if not set(customer_skus).issubset(row_ids):
            raise ValueError("客户 SKU 只能填写到当前决定分组中的订单行")
        raw_size_overrides = decision.get("size_overrides", {})
        if not isinstance(raw_size_overrides, dict):
            raise ValueError("尺码修正必须按订单行 ID 填写")
        size_overrides = {int(row_id): str(value).strip() for row_id, value in raw_size_overrides.items()}
        if not set(size_overrides).issubset(row_ids) or any(not value for value in size_overrides.values()):
            raise ValueError("尺码修正只能填写到当前决定分组中的订单行，且不能为空")
        prepared.append(
            (
                company.id,
                order_date,
                min(row.id for row in rows),
                decision,
                rows,
                company_code,
                spu_code,
                product_name,
                style_name,
                color_name,
                color_code,
                customer_skus,
                size_overrides,
            )
        )

    if len(decided_ids) != len(set(decided_ids)):
        raise ValueError("同一订单行不能出现在多个决定分组")
    if set(decided_ids) != legacy_ids:
        raise ValueError("决定文件必须完整覆盖全部未迁移订单行")
    if len(set(company_codes.values())) != len(company_codes):
        raise ValueError("不同公司不能使用相同公司代码")

    for company_id, code in company_codes.items():
        conflict = session.query(Company).filter(Company.code == code, Company.id != company_id).first()
        if conflict:
            raise ValueError(f"公司代码 {code} 已被其他公司使用")
        company = session.get(Company, company_id)
        company.code = code
        company.next_order_sequence = max(1, int(company.next_order_sequence or 1))
    session.flush()

    line_to_order = {}
    for company_id, order_date, _min_id, decision, rows, _company_code, spu_code, product_name, style_name, color_name, color_code, customer_skus, _size_overrides in sorted(prepared, key=lambda item: (item[0], item[1], item[2])):
        company = session.get(Company, company_id)
        spu = session.query(Spu).filter(Spu.code == spu_code).one_or_none()
        if spu is None:
            spu = Spu(code=spu_code, product_name=product_name, style_name=style_name, is_active=True)
            session.add(spu)
            session.flush()
        elif (spu.product_name, spu.style_name) != (product_name, style_name):
            raise ValueError(f"SPU {spu_code} 已属于其他产品或款式")
        sequence = int(company.next_order_sequence or 1)
        system_order_no = build_system_order_no(company.code, sequence, spu.code, color_code)
        order = SalesOrder(
            system_order_no=system_order_no,
            customer_order_no=str(decision.get("customer_order_no", "")).strip(),
            company_id=company.id,
            company_sequence=sequence,
            spu_id=spu.id,
            product_name=product_name,
            style_name=style_name,
            color_name=color_name,
            color_code=color_code,
            order_date=order_date,
            delivery_date=str(decision.get("delivery_date", rows[0].delivery_date or "")).strip(),
            note=str(decision.get("note", rows[0].note or "")).strip(),
            status="active",
        )
        session.add(order)
        session.flush()
        company.next_order_sequence = sequence + 1
        for row in rows:
            row.order_id = order.id
            row.order_date = order_date
            row.batch = system_order_no
            if row.id in customer_skus:
                row.customer_sku = customer_skus[row.id]
            line_to_order[row.id] = order.id
    session.flush()

    candidate_lines = defaultdict(list)
    for row in session.query(OrderLine).filter(OrderLine.id.in_(line_to_order)).all():
        candidate_lines[(row.company.name, row.product_name, row.style_name, row.size)].append(row)
    uniquely_matched_shipment_lines = 0
    ambiguous_shipment_lines = 0
    for report in session.query(ShipmentReport).all():
        for shipment_line in report.lines:
            if shipment_line.order_line_id:
                continue
            matches = candidate_lines.get(
                (report.company_name, report.product_name, report.style_name, shipment_line.size),
                [],
            )
            if len(matches) == 1:
                shipment_line.order_line_id = matches[0].id
                uniquely_matched_shipment_lines += 1
            elif len(matches) > 1:
                ambiguous_shipment_lines += 1
    for prepared_item in prepared:
        for row_id, size in prepared_item[-1].items():
            session.get(OrderLine, row_id).size = size
    session.flush()

    cross_order_reports = 0
    bound_reports = 0
    for report in session.query(ShipmentReport).all():
        mapped = {line_to_order.get(line.order_line_id) for line in report.lines if line.order_line_id}
        mapped.discard(None)
        has_unbound = any(not line.order_line_id for line in report.lines)
        if len(mapped) == 1 and not has_unbound:
            report.order_id = next(iter(mapped))
            bound_reports += 1
        elif len(mapped) > 1:
            cross_order_reports += 1
    session.commit()

    return {
        "order_line_count": session.query(OrderLine).count(),
        "grouped_order_line_count": session.query(OrderLine).filter(OrderLine.order_id.is_not(None)).count(),
        "unconfirmed_group_count": 0,
        "sales_order_count": session.query(SalesOrder).count(),
        "shipment_report_count": session.query(ShipmentReport).count(),
        "bound_shipment_report_count": bound_reports,
        "cross_order_report_count": cross_order_reports,
        "uniquely_matched_shipment_line_count": uniquely_matched_shipment_lines,
        "ambiguous_shipment_line_count": ambiguous_shipment_lines,
        "shipment_photo_count": session.query(ShipmentPhoto).count(),
        "waybill_link_count": session.query(ShipmentReport).filter(ShipmentReport.waybill_id.is_not(None)).count(),
        "waybill_record_count": session.query(WaybillRecord).count(),
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="历史正式订单预览与人工确认迁移")
    parser.add_argument("--database", required=True, help="SQLite 数据库文件")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", help="写入只读预览 JSON")
    mode.add_argument("--apply", help="读取人工确认决定 JSON 并执行")
    parser.add_argument("--audit", help="执行后审计 JSON 输出路径")
    args = parser.parse_args()
    database_path = Path(args.database).resolve()
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        if args.preview:
            payload = preview_legacy_orders(session)
            _write_json(Path(args.preview), payload)
            print(json.dumps(payload["summary"], ensure_ascii=False))
            return 0
        raw = json.loads(Path(args.apply).read_text(encoding="utf-8"))
        decisions = raw.get("decisions", []) if isinstance(raw, dict) else raw
        audit = apply_decisions(session, decisions)
        if args.audit:
            _write_json(Path(args.audit), audit)
        print(json.dumps(audit, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
