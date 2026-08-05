from pathlib import Path

from openpyxl import load_workbook

from app.models import ShipmentLine, ShipmentReport, User, WaybillRecord
from app.services.exports import export_customer_company_workbook
from app.services.logistics import create_waybill_record, link_reports_to_waybill
from app.services.orders import create_order_line


def _setup(db_session):
    admin = User(username="export_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    db_session.add(admin)
    db_session.commit()
    order = create_order_line(db_session, "广东茉莉", "裁判", "圆领裁判", "M", 100)
    report = ShipmentReport(
        user_id=admin.id,
        ship_date="2026-07-17",
        company_name="广东茉莉",
        product_name="裁判",
        style_name="圆领裁判",
        status="auto_approved",
    )
    db_session.add(report)
    db_session.flush()
    db_session.add(ShipmentLine(report_id=report.id, order_line_id=order.id, size="M", quantity=50))
    db_session.commit()
    waybill = create_waybill_record(db_session, admin.id, "广东茉莉", "2026-07-17", "800209579798", weight_kg=262.3, package_count=9)
    link_reports_to_waybill(db_session, waybill.id, [report.id])
    return order


def test_customer_export_uses_waybill_number_and_detail_sheet(db_session, tmp_path: Path):
    _setup(db_session)
    output = tmp_path / "茉莉客户版.xlsx"

    export_customer_company_workbook(db_session, "广东茉莉", output)

    wb = load_workbook(output)
    assert wb.sheetnames == ["客户发货明细", "发货明细"]
    main = wb["客户发货明细"]
    headers = [cell.value for cell in main[1]]
    assert headers == ["公司", "产品", "款式", "订单", "尺码", "SKU", "下单数量", "已发数量", "未发数量", "快递单号"]
    values = [cell.value for cell in main[2]]
    assert values[9] == "800209579798"
    detail = wb["发货明细"]
    detail_headers = [cell.value for cell in detail[1]]
    assert detail_headers == ["发货日期", "公司", "产品", "款式", "尺码", "数量", "快递单号", "上报人"]
    detail_row = [cell.value for cell in detail[2]]
    assert detail_row[0] == "2026-07-17"
    assert detail_row[5] == 50
    assert detail_row[6] == "800209579798"
