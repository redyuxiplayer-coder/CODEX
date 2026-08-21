from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import ProductAlias


def clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def create_product_alias(
    session: Session,
    company_name: str,
    alias_product: str,
    alias_style: str,
    canonical_product: str,
    canonical_style: str,
    note: str = "",
) -> ProductAlias:
    alias = ProductAlias(
        company_name=clean_text(company_name),
        alias_product=clean_text(alias_product),
        alias_style=clean_text(alias_style),
        canonical_product=clean_text(canonical_product),
        canonical_style=clean_text(canonical_style),
        note=clean_text(note),
        is_active=True,
    )
    session.add(alias)
    session.commit()
    return alias


def update_product_alias(
    session: Session,
    alias_id: int,
    *,
    company_name: str,
    alias_product: str,
    alias_style: str,
    canonical_product: str,
    canonical_style: str,
    note: str = "",
    is_active: bool = True,
) -> ProductAlias:
    alias = session.get(ProductAlias, alias_id)
    if alias is None:
        raise ValueError("别名规则不存在")
    alias.company_name = clean_text(company_name)
    alias.alias_product = clean_text(alias_product)
    alias.alias_style = clean_text(alias_style)
    alias.canonical_product = clean_text(canonical_product)
    alias.canonical_style = clean_text(canonical_style)
    alias.note = clean_text(note)
    alias.is_active = is_active
    alias.updated_at = datetime.now()
    session.commit()
    return alias


def list_product_aliases(session: Session) -> list[ProductAlias]:
    return (
        session.query(ProductAlias)
        .order_by(ProductAlias.company_name, ProductAlias.canonical_product, ProductAlias.canonical_style, ProductAlias.alias_product)
        .all()
    )


def alias_lookup(session: Session, company_name: str | None = None) -> dict[tuple[str, str, str], tuple[str, str]]:
    query = session.query(ProductAlias).filter(ProductAlias.is_active.is_(True))
    if company_name:
        query = query.filter(func.trim(ProductAlias.company_name) == clean_text(company_name))
    rows = query.order_by(ProductAlias.id).all()
    lookup: dict[tuple[str, str, str], tuple[str, str]] = {}
    for row in rows:
        company = clean_text(row.company_name)
        alias_product = clean_text(row.alias_product)
        alias_style = clean_text(row.alias_style)
        canonical_product = clean_text(row.canonical_product)
        canonical_style = clean_text(row.canonical_style)
        lookup[(company, alias_product, alias_style)] = (canonical_product, canonical_style)
        lookup[(company, canonical_product, canonical_style)] = (canonical_product, canonical_style)
    return lookup


def canonical_item(session: Session, company_name: str, product_name: str, style_name: str) -> tuple[str, str]:
    company = clean_text(company_name)
    product = clean_text(product_name)
    style = clean_text(style_name)
    lookup = alias_lookup(session, company)
    return lookup.get((company, product, style), (product, style))
