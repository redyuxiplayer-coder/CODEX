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
from app.services.order_archives import archive_sales_order, archive_state  # noqa: E402


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
        candidates = collect_archive_candidates(session)
        mode = "执行" if args.apply else "预览"
        print(f"{mode}：符合归档条件的订单 {len(candidates)} 单")
        for order in candidates:
            print(f"{order.system_order_no}\t{order.order_date}")
        if not args.apply:
            print("当前为只读预览，未修改数据库。")
            return 0

        applied = apply_archive_candidates(session, candidates, admin.id)
        remaining_ids = {order.id for order in collect_archive_candidates(session)}
        failed = [record.order_id for record in applied if record.order_id in remaining_ids]
        print(f"已归档 {len(applied)} 单。")
        if failed:
            print(f"归档后复核失败：{failed}", file=sys.stderr)
            return 1
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
