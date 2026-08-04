from pathlib import Path

from app.models import PackingDraft, PackingDraftLine, PackingDraftPhoto
from app.services.quantities import parse_quantity
from app.services.shipments import submit_shipment_report


def _next_package_no(session, pack_date: str) -> str:
    count = session.query(PackingDraft).filter_by(pack_date=pack_date).count()
    compact = str(pack_date or "").replace("-", "")
    return f"PKG-{compact}-{count + 1:03d}"


def _clean_lines(lines: list[dict]) -> list[dict]:
    cleaned = []
    for line in lines:
        size = str(line.get("size", "")).strip()
        quantity = parse_quantity(line.get("quantity"))
        order_line_id = line.get("order_line_id") or None
        if size and quantity > 0:
            cleaned.append({"size": size, "quantity": quantity, "order_line_id": int(order_line_id) if order_line_id else None})
    return cleaned


def create_packing_draft(
    session,
    user_id: int,
    pack_date: str,
    company_name: str,
    product_name: str,
    style_name: str,
    lines: list[dict],
    note: str = "",
    photo_paths: list[str] | None = None,
    waybill_no: str = "",
) -> PackingDraft:
    draft = PackingDraft(
        user_id=user_id,
        pack_date=pack_date,
        company_name=company_name,
        product_name=product_name,
        style_name=style_name,
        package_no=_next_package_no(session, pack_date),
        waybill_no=str(waybill_no or "").strip(),
        note=note,
    )
    session.add(draft)
    session.flush()
    for line in _clean_lines(lines):
        session.add(
            PackingDraftLine(
                draft_id=draft.id,
                order_line_id=line.get("order_line_id"),
                size=line["size"],
                quantity=line["quantity"],
            )
        )
    for path in photo_paths or []:
        session.add(PackingDraftPhoto(draft_id=draft.id, file_path=path, original_name=Path(path).name))
    session.commit()
    session.refresh(draft)
    return draft


def _get_own_draft(session, draft_id: int, user_id: int) -> PackingDraft:
    draft = session.get(PackingDraft, draft_id)
    if draft is None or draft.user_id != user_id:
        raise ValueError("不能修改这条包货记录")
    if draft.submitted_report_id is not None:
        raise ValueError("已提交的包货记录不能修改")
    return draft


def update_packing_draft(
    session,
    draft_id: int,
    user_id: int,
    lines: list[dict],
    note: str = "",
    photo_paths: list[str] | None = None,
    waybill_no: str | None = None,
) -> PackingDraft:
    draft = _get_own_draft(session, draft_id, user_id)
    for line in list(draft.lines):
        session.delete(line)
    session.flush()
    for line in _clean_lines(lines):
        session.add(
            PackingDraftLine(
                draft_id=draft.id,
                order_line_id=line.get("order_line_id"),
                size=line["size"],
                quantity=line["quantity"],
            )
        )
    for path in photo_paths or []:
        session.add(PackingDraftPhoto(draft_id=draft.id, file_path=path, original_name=Path(path).name))
    draft.note = note
    if waybill_no is not None:
        draft.waybill_no = str(waybill_no).strip()
    session.commit()
    session.refresh(draft)
    return draft


def delete_packing_draft(session, draft_id: int, user_id: int) -> None:
    draft = _get_own_draft(session, draft_id, user_id)
    session.delete(draft)
    session.commit()


def submit_packing_draft(session, draft_id: int, user_id: int):
    draft = _get_own_draft(session, draft_id, user_id)
    lines = [{"size": line.size, "quantity": line.quantity, "order_line_id": line.order_line_id} for line in draft.lines]
    report = submit_shipment_report(
        session,
        user_id=user_id,
        ship_date=draft.pack_date,
        company_name=draft.company_name,
        product_name=draft.product_name,
        style_name=draft.style_name,
        lines=lines,
        photo_paths=[photo.file_path for photo in draft.photos],
        note=draft.note,
        waybill_no=draft.waybill_no or "",
    )
    draft.submitted_report_id = report.id
    for photo in report.photos:
        photo.draft_id = draft.id
    session.commit()
    session.refresh(report)
    return report
