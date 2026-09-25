from decimal import Decimal, InvalidOperation

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Company, OrderLine, SalesOrder, Spu
from app.services.quantities import parse_quantity
from app.services.spus import normalize_code


PRICE_QUANTUM = Decimal("0.01")
MAX_UNIT_PRICE = Decimal("9999999999.99")


class OrderPriceTargetNotFoundError(ValueError):
    pass


class StaleUnitPriceError(ValueError):
    pass


def parse_unit_price(value: object) -> Decimal | None:
    if value is None or isinstance(value, str) and not value.strip():
        return None
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("单价格式无效") from exc
    if (
        not price.is_finite()
        or price < 0
        or price > MAX_UNIT_PRICE
        or price.as_tuple().exponent < -2
    ):
        raise ValueError("单价必须为 0 到 9999999999.99 之间且最多两位小数")
    return price.quantize(PRICE_QUANTUM)


def order_line_amount_cents(quantity: int, unit_price: Decimal) -> int:
    return int(unit_price * 100) * quantity


def money_from_cents(cents: int) -> Decimal:
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return Decimal(f"{sign}{whole}.{fraction:02d}")


def order_price_summary(order: SalesOrder) -> dict:
    active = [line for line in order.lines if line.is_active]
    known_cents = sum(
        order_line_amount_cents(line.quantity, line.unit_price)
        for line in active
        if line.unit_price is not None
    )
    known = money_from_cents(known_cents)
    missing = sum(1 for line in active if line.unit_price is None)
    return {
        "known_subtotal": known,
        "missing_price_count": missing,
        "is_complete": missing == 0,
        "total_amount": known if missing == 0 else None,
    }


def update_order_line_unit_price(
    session: Session,
    order_id: int,
    line_id: int,
    value: object,
    expected_value: object,
    expected_revision: int,
) -> tuple[OrderLine, Decimal | None]:
    price = parse_unit_price(value)
    expected_price = parse_unit_price(expected_value)
    order = session.get(SalesOrder, int(order_id))
    if order is None:
        raise OrderPriceTargetNotFoundError("订单不存在")
    line = session.get(OrderLine, int(line_id))
    if line is None:
        raise OrderPriceTargetNotFoundError("订单行不存在")
    if line.order_id != order.id:
        raise ValueError("订单行不存在或不属于该订单")
    price_matches = (
        OrderLine.unit_price.is_(None)
        if expected_price is None
        else OrderLine.unit_price == expected_price
    )
    result = session.execute(
        update(OrderLine)
        .where(
            OrderLine.id == int(line_id),
            OrderLine.order_id == order.id,
            price_matches,
            OrderLine.price_revision == expected_revision,
        )
        .values(unit_price=price, price_revision=OrderLine.price_revision + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        current_order_id = session.execute(
            select(OrderLine.order_id).where(OrderLine.id == int(line_id))
        ).scalar_one_or_none()
        if current_order_id is None:
            raise OrderPriceTargetNotFoundError("订单行不存在")
        if current_order_id != order.id:
            raise ValueError("订单行不存在或不属于该订单")
        raise StaleUnitPriceError("单价已变更，请刷新订单后重试")
    session.refresh(line)
    return line, expected_price


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
                "unit_price": parse_unit_price(raw.get("unit_price")),
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
                unit_price=row["unit_price"],
                is_active=True,
            )
        )
    session.commit()
    session.refresh(order)
    return order


def update_sales_order_customer_no(
    session: Session,
    order_id: int,
    customer_order_no: str,
) -> SalesOrder:
    clean = str(customer_order_no or "").strip()
    if len(clean) > 160:
        raise ValueError("客户订单号不能超过 160 个字符")
    order = session.get(SalesOrder, int(order_id))
    if order is None:
        raise ValueError("订单不存在")
    order.customer_order_no = clean
    session.commit()
    session.refresh(order)
    return order
