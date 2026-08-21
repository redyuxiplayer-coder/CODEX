from pathlib import Path


AUDIT_SQL = Path("scripts/audit_orders.sql")


def test_repair_buckets_share_one_cte_and_match_repair_cli_predicates():
    sql = AUDIT_SQL.read_text(encoding="utf-8")
    section = sql.split("=== A1.", 1)[1].split("=== D.", 1)[0]
    normalized = " ".join(section.lower().split())

    assert normalized.count("unbound as") == 1
    assert "l.order_line_id is null" in normalized
    assert "r.status in ('auto_approved','approved_after_edit')" in normalized
    assert "a.is_active = true" in normalized
    assert "coalesce" in normalized
    assert "o.is_active = true" in normalized
    assert "o.order_id is not null" in normalized
    assert "join sales_orders so on so.id = o.order_id" in normalized
    assert "so.status = 'active'" in normalized
    assert "from unbound u left join formal_lines f" in normalized


def test_repair_bucket_classification_is_per_current_unbound_shipment_line():
    sql = AUDIT_SQL.read_text(encoding="utf-8")
    section = sql.split("=== A1.", 1)[1].split("=== D.", 1)[0]
    normalized = " ".join(section.lower().split())

    assert "group by u.shipment_line_id" in normalized
    assert "when candidate_count = 1 then 'unique'" in normalized
    assert "when candidate_count > 1 then 'ambiguous'" in normalized
    assert "else 'unmatched'" in normalized
    assert "from repair_buckets" in normalized


def test_repair_bucket_alias_keys_are_trimmed_paired_and_deterministic():
    sql = AUDIT_SQL.read_text(encoding="utf-8")
    section = sql.split("=== A1.", 1)[1].split("=== D.", 1)[0]
    normalized = " ".join(section.lower().split())

    assert "normalized_aliases as" in normalized
    assert "alias_assignments as" in normalized
    assert "canonical_aliases as" in normalized
    assert "btrim(r.company_name)" in normalized
    assert "btrim(r.product_name)" in normalized
    assert "btrim(r.style_name)" in normalized
    assert "btrim(l.size)" in normalized
    assert "btrim(c.name)" in normalized
    assert "btrim(o.product_name)" in normalized
    assert "btrim(o.style_name)" in normalized
    assert "btrim(o.size)" in normalized
    assert "alias_id desc, assignment_order desc" in normalized
    assert "(select canonical_product" not in normalized
    assert "(select canonical_style" not in normalized
