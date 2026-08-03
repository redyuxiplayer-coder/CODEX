from app.main import shipment_status_label


def test_shipment_status_label_is_chinese():
    assert shipment_status_label("pending_review") == "待审核"
    assert shipment_status_label("auto_approved") == "已通过"
    assert shipment_status_label("approved_after_edit") == "已修改通过"
    assert shipment_status_label("rejected") == "已驳回"
    assert shipment_status_label("unknown") == "unknown"
