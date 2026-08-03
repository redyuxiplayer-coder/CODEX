from app.main import item_choices_from_balances, sort_balances_for_display


def test_item_choices_only_use_product_names():
    balances = [
        {"company": "福建", "product": "小偷", "style": "小偷女款", "size": "M", "remaining": 0, "over_shipped": 0},
        {"company": "张鹏", "product": "聪明的红帽子", "style": "小红帽男款", "size": "XL", "remaining": 20, "over_shipped": 0},
    ]

    assert item_choices_from_balances(balances) == ["小偷", "聪明的红帽子"]


def test_unfinished_balances_sort_before_finished_balances():
    balances = [
        {"company": "A", "product": "已发产品", "style": "款", "size": "M", "remaining": 0, "over_shipped": 0},
        {"company": "A", "product": "未发产品", "style": "款", "size": "M", "remaining": 10, "over_shipped": 0},
        {"company": "A", "product": "超发产品", "style": "款", "size": "M", "remaining": -2, "over_shipped": 2},
    ]

    sorted_rows = sort_balances_for_display(balances)

    assert [row["product"] for row in sorted_rows] == ["未发产品", "超发产品", "已发产品"]


def test_order_query_sorts_sizes_inside_same_order():
    balances = [
        {"company": "A", "product": "裁判", "style": "圆领裁判", "order_ref": "2026-07-20", "size": "XL", "remaining": 10, "over_shipped": 0},
        {"company": "A", "product": "裁判", "style": "圆领裁判", "order_ref": "2026-07-20", "size": "S", "remaining": 10, "over_shipped": 0},
        {"company": "A", "product": "裁判", "style": "圆领裁判", "order_ref": "2026-07-20", "size": "XXL", "remaining": 10, "over_shipped": 0},
        {"company": "A", "product": "裁判", "style": "圆领裁判", "order_ref": "2026-07-20", "size": "L", "remaining": 10, "over_shipped": 0},
        {"company": "A", "product": "裁判", "style": "圆领裁判", "order_ref": "2026-07-20", "size": "M", "remaining": 10, "over_shipped": 0},
        {"company": "A", "product": "裁判", "style": "圆领裁判", "order_ref": "2026-07-19", "size": "S", "remaining": 0, "over_shipped": 0},
    ]

    sorted_rows = sort_balances_for_display(balances)

    assert [row["size"] for row in sorted_rows[:5]] == ["S", "M", "L", "XL", "XXL"]
    assert sorted_rows[-1]["remaining"] == 0
