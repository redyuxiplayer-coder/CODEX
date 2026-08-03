import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import WorkInfoLine, WorkInfoProposal
from app.services.orders import clean_text

FIXED_SECTIONS = [
    ("accessories", "产品配件信息"),
    ("bag", "包装袋信息"),
    ("wash_label", "水洗标信息"),
    ("sticker", "贴标信息"),
]


def normalize_work_rows(rows: list[dict]) -> list[dict]:
    normalized = []
    for index, row in enumerate(rows):
        section_key = clean_text(row.get("section_key"))
        title = clean_text(row.get("section_title"))
        content = clean_text(row.get("content"))
        photo_path = clean_text(row.get("photo_path"))
        original_name = clean_text(row.get("original_name"))
        if not section_key and not title and not content:
            continue
        is_custom = section_key == "custom" or section_key.startswith("custom:")
        if is_custom:
            section_key = f"custom:{index}"
        normalized.append(
            {
                "section_key": section_key,
                "section_title": title or "自定义信息",
                "content": content,
                "photo_path": photo_path,
                "original_name": original_name,
                "sort_order": index,
                "is_custom": is_custom,
            }
        )
    return normalized


def get_work_info(session: Session, company_name: str, product_name: str, style_name: str) -> list[dict]:
    company_name = clean_text(company_name)
    product_name = clean_text(product_name)
    style_name = clean_text(style_name)
    existing = {
        line.section_key: line
        for line in session.query(WorkInfoLine)
        .filter_by(company_name=company_name, product_name=product_name, style_name=style_name)
        .order_by(WorkInfoLine.sort_order, WorkInfoLine.id)
        .all()
    }
    rows = []
    for index, (key, title) in enumerate(FIXED_SECTIONS):
        line = existing.pop(key, None)
        rows.append(
            {
                "id": line.id if line else "",
                "section_key": key,
                "section_title": title,
                "content": line.content if line else "",
                "photo_path": line.photo_path if line else "",
                "original_name": line.original_name if line else "",
                "sort_order": index,
                "is_custom": False,
            }
        )
    custom_lines = sorted(existing.values(), key=lambda line: (line.sort_order, line.id))
    for line in custom_lines:
        rows.append(
            {
                "id": line.id,
                "section_key": line.section_key,
                "section_title": line.section_title,
                "content": line.content,
                "photo_path": line.photo_path,
                "original_name": line.original_name,
                "sort_order": line.sort_order,
                "is_custom": True,
            }
        )
    return rows


def save_work_info(
    session: Session,
    company_name: str,
    product_name: str,
    style_name: str,
    rows: list[dict],
    updated_by: int | None = None,
) -> None:
    company_name = clean_text(company_name)
    product_name = clean_text(product_name)
    style_name = clean_text(style_name)
    session.query(WorkInfoLine).filter_by(company_name=company_name, product_name=product_name, style_name=style_name).delete()
    for row in normalize_work_rows(rows):
        session.add(
            WorkInfoLine(
                company_name=company_name,
                product_name=product_name,
                style_name=style_name,
                section_key=row["section_key"],
                section_title=row["section_title"],
                content=row["content"],
                photo_path=row.get("photo_path", ""),
                original_name=row.get("original_name", ""),
                sort_order=row["sort_order"],
                is_custom=row["is_custom"],
                updated_by=updated_by,
                updated_at=datetime.now(),
            )
        )
    session.commit()


def create_work_info_proposal(
    session: Session,
    user_id: int,
    company_name: str,
    product_name: str,
    style_name: str,
    rows: list[dict],
) -> WorkInfoProposal:
    proposal = WorkInfoProposal(
        user_id=user_id,
        company_name=clean_text(company_name),
        product_name=clean_text(product_name),
        style_name=clean_text(style_name),
        payload=json.dumps(normalize_work_rows(rows), ensure_ascii=False),
        status="pending_review",
        review_reason="员工提交作业信息，等待老板审核",
    )
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal


def pending_work_info_proposals(session: Session) -> list[WorkInfoProposal]:
    return (
        session.query(WorkInfoProposal)
        .filter_by(status="pending_review")
        .order_by(WorkInfoProposal.created_at.desc())
        .all()
    )


def proposal_rows(proposal: WorkInfoProposal) -> list[dict]:
    try:
        return json.loads(proposal.payload)
    except json.JSONDecodeError:
        return []


def approve_work_info_proposal(session: Session, proposal_id: int, admin_id: int, note: str = "") -> WorkInfoProposal:
    proposal = session.get(WorkInfoProposal, proposal_id)
    if proposal is None:
        raise ValueError("作业信息建议不存在")
    save_work_info(
        session,
        proposal.company_name,
        proposal.product_name,
        proposal.style_name,
        proposal_rows(proposal),
        updated_by=admin_id,
    )
    proposal.status = "approved_after_edit"
    proposal.review_reason = note or "已通过"
    proposal.reviewed_by = admin_id
    proposal.reviewed_at = datetime.now()
    session.commit()
    session.refresh(proposal)
    return proposal


def reject_work_info_proposal(session: Session, proposal_id: int, admin_id: int, note: str = "") -> WorkInfoProposal:
    proposal = session.get(WorkInfoProposal, proposal_id)
    if proposal is None:
        raise ValueError("作业信息建议不存在")
    proposal.status = "rejected"
    proposal.review_reason = note or "已驳回"
    proposal.reviewed_by = admin_id
    proposal.reviewed_at = datetime.now()
    session.commit()
    session.refresh(proposal)
    return proposal
