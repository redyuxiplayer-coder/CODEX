import re
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import Spu


CODE_PATTERN = re.compile(r"^[A-Z0-9]+$")


def normalize_code(value: str) -> str:
    code = str(value or "").strip().upper()
    if not code or not CODE_PATTERN.fullmatch(code):
        raise ValueError("编码只能包含大写英文字母和数字")
    return code


def create_spu(
    session: Session,
    code: str,
    product_name: str,
    style_name: str,
    note: str = "",
) -> Spu:
    product = str(product_name or "").strip()
    style = str(style_name or "").strip()
    if not product or not style:
        raise ValueError("产品和款式不能为空")

    manual_code = str(code or "").strip()
    normalized = normalize_code(manual_code) if manual_code else f"AUTO{uuid4().hex.upper()}"
    if session.query(Spu.id).filter(Spu.code == normalized).first():
        raise ValueError("SPU 编码已存在")

    spu = Spu(
        code=normalized,
        product_name=product,
        style_name=style,
        note=str(note or "").strip(),
        is_active=True,
    )
    session.add(spu)
    session.flush()
    if not manual_code:
        spu.code = f"SPU{spu.id:05d}"
    session.commit()
    session.refresh(spu)
    return spu
