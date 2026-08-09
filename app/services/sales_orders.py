from sqlalchemy.orm import Session

from app.models import Company, OrderLine, SalesOrder, Spu
from app.services.quantities import parse_quantity
from app.services.spus import normalize_code


def build_system_order_no(
    company_code: str,
    sequence: int,
    spu_code: str,
    color_code: str = "",
) -> str:
    parts = [normalize_code(company_code), f"{int(sequence):05d}", normalize_code(spu_code)]
    if str(color_code or "").strip():
        parts.append(normalize_code(color_code))
    return "-".join(parts)


def _clean_order_lines(lines: list[dict]) -> list[dict]:
    cleaned = []
    seen_sizes = set()
    for raw in lines:
        size = str(raw.get("size") or "").strip()
        quantity = parse_quantity(raw.get("quantity"))
        if not size or quantity <= 0:
            raise ValueError("尺码和数量必须填写，数量必须大于 0")
        if size in seen_sizes:
            raise ValueError("同一订单不能有重复尺码")
        seen_sizes.add(size)
        cleaned.append(
            {
                "size": size,
                "quantity": quantity,
                "customer_sku": str(raw.get("customer_sku") or "").strip(),
            }
        )
    if not cleaned:
        raise ValueError("订单至少需要一个尺码")
    return cleaned


def create_sales_order(
    session: Session,
    company_id: int,
    spu_id: int,
    color_name: str,
    color_code: str,
    order_date: str,
    lines: list[dict],
    customer_order_no: str = "",
    delivery_date: str = "",
    note: str = "",
) -> SalesOrder:
    clean_color_name = str(color_name or "").strip()
    raw_color_code = str(color_code or "").strip()
    if bool(clean_color_name) != bool(raw_color_code):
        raise ValueError("颜色名称和颜色编码必须同时填写")
    clean_color_code = normalize_code(raw_color_code) if raw_color_code else ""
    clean_order_date = str(order_date or "").strip()
    if not clean_order_date:
        raise ValueError("下单日期不能为空")
    clean_lines = _clean_order_lines(lines)

    company = (
        session.query(Company)
        .filter(Company.id == int(company_id))
        .with_for_update()
        .one_or_none()
    )
    if company is None or not company.is_active:
        raise ValueError("公司不存在或已停用")
    if not str(company.code or "").strip():
        raise ValueError("公司尚未设置公司代码")
    spu = session.get(Spu, int(spu_id))
    if spu is None or not spu.is_active:
        raise ValueError("SPU 不存在或已停用")

    sequence = max(1, int(company.next_order_sequence or 1))
    system_order_no = build_system_order_no(company.code, sequence, spu.code, clean_color_code)
    company.next_order_sequence = sequence + 1
    order = SalesOrder(
        system_order_no=system_order_no,
        customer_order_no=str(customer_order_no or "").strip(),
        company_id=company.id,
        company_sequence=sequence,
        spu_id=spu.id,
        product_name=spu.product_name,
        style_name=spu.style_name,
        color_name=clean_color_name,
        color_code=clean_color_code,
        order_date=clean_order_date,
        delivery_date=str(delivery_date or "").strip(),
        note=str(note or "").strip(),
        status="active",
    )
    session.add(order)
    session.flush()
    for row in clean_lines:
        session.add(
            OrderLine(
                order_id=order.id,
                company_id=company.id,
                product_name=order.product_name,
                style_name=order.style_name,
                size=row["size"],
                quantity=row["quantity"],
                order_date=order.order_date,
                delivery_date=order.delivery_date,
                note=order.note,
                batch=order.system_order_no,
                sku="",
                customer_sku=row["customer_sku"],
                is_active=True,
            )
        )
    session.commit()
    session.refresh(order)
    return order
