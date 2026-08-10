"""Preview or manually archive every currently completed formal sales order."""

import argparse
import sys
from pathlib import Path

from sqlalchemy.orm import Session

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.db import SessionLocal  # noqa: E402
from app.models import SalesOrder, User  # noqa: E402
from app.services.order_archives import (  # noqa: E402
    archive_sales_order,
    archive_state,
    archived_order_ids,
    archived_order_line_ids,
    order_balance_rows,
    worker_visible_balances,
)


def collect_archive_candidates(session: Session) -> list[SalesOrder]:
    candidates = []
    orders = (
        session.query(SalesOrder)
        .order_by(SalesOrder.company_id, SalesOrder.company_sequence, SalesOrder.id)
        .all()
    )
    for order in orders:
        state = archive_state(session, order)
        if state["can_archive"] and not state["is_archived"]:
            candidates.append(order)
    return candidates


def apply_archive_candidates(session: Session, candidates: list[SalesOrder], admin_id: int):
    return [archive_sales_order(session, order.id, admin_id) for order in candidates]


def build_archive_preview(
    session: Session,
    orders: list[SalesOrder],
    candidate_ids: set[int],
) -> list[dict]:
    return [
        {
            "order_id": order.id,
            "system_order_no": order.system_order_no,
            "order_date": order.order_date,
            "candidate": order.id in candidate_ids,
            "sizes": [
                {
                    "size": row["size"],
                    "ordered": int(row["ordered"]),
                    "shipped": int(row["shipped"]),
                    "returned": int(row.get("returned") or 0),
                    "adjusted": int(row.get("adjusted") or 0),
                    "closed": int(row.get("closed") or 0),
                    "remaining": int(row["remaining"]),
                    "over_shipped": int(row["over_shipped"]),
                }
                for row in order_balance_rows(session, order)
            ],
        }
        for order in orders
    ]


def verify_archive_rollout(
    session: Session,
    candidate_ids: set[int],
    protected_order_ids: set[int],
) -> dict:
    open_order_ids = archived_order_ids(session)
    hidden_line_ids = archived_order_line_ids(session)
    visible_archived_line_ids = sorted(
        hidden_line_ids.intersection(
            int(line_id)
            for row in worker_visible_balances(session)
            for line_id in row.get("order_ids", [])
        )
    )
    result = {
        "missing_archives": sorted(candidate_ids - open_order_ids),
        "unexpected_archives": sorted(protected_order_ids.intersection(open_order_ids)),
        "worker_visible_archived_lines": visible_archived_line_ids,
    }
    return {"ok": not any(result.values()), **result}


def _active_admin(session: Session, username: str) -> User:
    admin = (
        session.query(User)
        .filter(User.username == username, User.role == "admin", User.is_active.is_(True))
        .one_or_none()
    )
    if admin is None:
        raise ValueError("未找到有效的管理员账号")
    return admin


def main() -> int:
    parser = argparse.ArgumentParser(description="预览或归档所有已发完的正式订单")
    parser.add_argument("--admin-username", required=True, help="操作日志使用的有效管理员账号")
    parser.add_argument("--apply", action="store_true", help="执行归档；不加时只预览")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        admin = _active_admin(session, args.admin_username)
        all_orders = (
            session.query(SalesOrder)
            .order_by(SalesOrder.company_id, SalesOrder.company_sequence, SalesOrder.id)
            .all()
        )
        candidates = collect_archive_candidates(session)
        candidate_ids = {order.id for order in candidates}
        existing_archived_ids = archived_order_ids(session)
        all_order_ids = {int(order_id) for (order_id,) in session.query(SalesOrder.id).all()}
        protected_order_ids = all_order_ids - candidate_ids - existing_archived_ids
        preview = build_archive_preview(session, all_orders, candidate_ids)
        mode = "执行" if args.apply else "预览"
        print(f"{mode}：符合归档条件的订单 {len(candidates)} 单")
        for order in preview:
            label = "归档候选" if order["candidate"] else "保留"
            print(f'[{label}] {order["system_order_no"]}\t{order["order_date"]}')
            for row in order["sizes"]:
                print(
                    f'  {row["size"]}: 下单 {row["ordered"]}，已发 {row["shipped"]}，'
                    f'退回 {row["returned"]}，核销 {row["adjusted"]}，关闭 {row["closed"]}，'
                    f'剩余 {row["remaining"]}，超发 {row["over_shipped"]}'
                )
        if not args.apply:
            print("当前为只读预览，未修改数据库。")
            return 0

        applied = apply_archive_candidates(session, candidates, admin.id)
        verification = verify_archive_rollout(session, candidate_ids, protected_order_ids)
        print(f"已归档 {len(applied)} 单。")
        if not verification["ok"]:
            print(f"归档后复核失败：{verification}", file=sys.stderr)
            return 1
        print("复核通过：原候选均已归档，其他订单未误归档，员工候选已隐藏。")
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
