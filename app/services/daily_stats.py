from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import ShipmentLine, ShipmentReport

APPROVED_STATUSES = {"auto_approved", "approved_after_edit"}


def daily_shipment_stats(session: Session, ship_date: str) -> list[dict]:
    rows = (
        session.query(
            ShipmentReport.company_name,
            ShipmentReport.product_name,
            ShipmentReport.style_name,
            ShipmentLine.size,
            func.sum(ShipmentLine.quantity),
        )
        .join(ShipmentLine, ShipmentLine.report_id == ShipmentReport.id)
        .filter(
            ShipmentReport.ship_date == ship_date,
            ShipmentReport.status.in_(APPROVED_STATUSES),
        )
        .group_by(
            ShipmentReport.company_name,
            ShipmentReport.product_name,
            ShipmentReport.style_name,
            ShipmentLine.size,
        )
        .order_by(
            ShipmentReport.company_name,
            ShipmentReport.product_name,
            ShipmentReport.style_name,
            ShipmentLine.size,
        )
        .all()
    )
    return [
        {
            "company": company,
            "product": product,
            "style": style,
            "size": size,
            "quantity": int(quantity or 0),
        }
        for company, product, style, size, quantity in rows
    ]
