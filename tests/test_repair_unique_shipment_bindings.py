import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, engine_kwargs_for_url
from app.models import ShipmentLine, ShipmentReport
from app.services.aliases import create_product_alias
from app.services.ledger import order_line_totals, recompute_order_ledger
from app.services.orders import create_order_line
from app.services.sales_orders import create_sales_order


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "repair_unique_shipment_order_bindings.py"


def _load_repair_module():
    spec = importlib.util.spec_from_file_location("repair_unique_shipment_order_bindings", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_binding_fixture(session):
    from app.models import Company, Spu, User

    company = Company(name="源兴发", code="YXF", next_order_sequence=1)
    spu = Spu(code="JS", product_name="啦啦队", style_name="僵尸啦啦队")
    admin = User(username="repair_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    session.add_all([company, spu, admin])
    session.commit()

    create_product_alias(session, "源兴发", "啦啦队旧名", "僵尸啦啦队旧版", "啦啦队", "僵尸啦啦队", "历史别名")

    unique_order = create_sales_order(
        session,
        company.id,
        spu.id,
        "红色",
        "RED",
        "2026-08-01",
        [{"size": "S", "quantity": 100}, {"size": "XS", "quantity": 80}],
    )
    ambiguous_order_a = create_sales_order(
        session,
        company.id,
        spu.id,
        "蓝色",
        "BLUE",
        "2026-08-02",
        [{"size": "M", "quantity": 60}],
    )
    ambiguous_order_b = create_sales_order(
        session,
        company.id,
        spu.id,
        "绿色",
        "GREEN",
        "2026-08-03",
        [{"size": "M", "quantity": 70}],
    )
    create_order_line(session, "源兴发", "啦啦队", "僵尸啦啦队", "XL", 55, order_date="2026-08-04")

    unique_report = ShipmentReport(
        user_id=admin.id,
        ship_date="2026-08-10",
        company_name="源兴发",
        product_name="啦啦队旧名",
        style_name="僵尸啦啦队旧版",
        status="auto_approved",
    )
    ambiguous_report = ShipmentReport(
        user_id=admin.id,
        ship_date="2026-08-11",
        company_name="源兴发",
        product_name="啦啦队旧名",
        style_name="僵尸啦啦队旧版",
        status="approved_after_edit",
    )
    unmatched_report = ShipmentReport(
        user_id=admin.id,
        ship_date="2026-08-12",
        company_name="源兴发",
        product_name="啦啦队旧名",
        style_name="僵尸啦啦队旧版",
        status="auto_approved",
    )
    session.add_all([unique_report, ambiguous_report, unmatched_report])
    session.flush()
    session.add_all(
        [
            ShipmentLine(report_id=unique_report.id, order_line_id=None, size="S", quantity=12),
            ShipmentLine(report_id=unique_report.id, order_line_id=None, size="XS", quantity=8),
            ShipmentLine(report_id=ambiguous_report.id, order_line_id=None, size="M", quantity=6),
            ShipmentLine(report_id=unmatched_report.id, order_line_id=None, size="XL", quantity=4),
        ]
    )
    session.commit()
    return {
        "unique_order": unique_order,
        "ambiguous_order_a": ambiguous_order_a,
        "ambiguous_order_b": ambiguous_order_b,
        "unique_report_id": unique_report.id,
        "ambiguous_report_id": ambiguous_report.id,
        "unmatched_report_id": unmatched_report.id,
    }


def _create_file_session(database_path: Path):
    database_url = f"sqlite:///{database_path}"
    engine = create_engine(database_url, **engine_kwargs_for_url(database_url))
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _seed_recompute_fixture(session):
    from app.models import Company, Spu, User

    company = Company(name="源兴发", code="YXF", next_order_sequence=1)
    spu = Spu(code="JS", product_name="啦啦队", style_name="僵尸啦啦队")
    admin = User(username="recompute_admin", display_name="老板", password_hash="x", role="admin", is_active=True)
    session.add_all([company, spu, admin])
    session.commit()

    create_product_alias(session, "源兴发", "啦啦队旧名", "僵尸啦啦队旧版", "啦啦队", "僵尸啦啦队", "历史别名")

    legacy_line = create_order_line(session, "源兴发", "啦啦队", "僵尸啦啦队", "S", 10, order_date="2026-08-01")
    formal_order = create_sales_order(
        session,
        company.id,
        spu.id,
        "红色",
        "RED",
        "2026-08-02",
        [{"size": "S", "quantity": 100}],
    )
    history_report = ShipmentReport(
        user_id=admin.id,
        ship_date="2026-08-10",
        company_name="源兴发",
        product_name="啦啦队旧名",
        style_name="僵尸啦啦队旧版",
        status="auto_approved",
    )
    session.add(history_report)
    session.flush()
    session.add(ShipmentLine(report_id=history_report.id, order_line_id=None, size="S", quantity=12))
    session.commit()

    recompute_order_ledger(session, legacy_line.id)
    recompute_order_ledger(session, formal_order.lines[0].id)
    return {
        "legacy_line_id": legacy_line.id,
        "formal_order_id": formal_order.id,
        "formal_order_line_id": formal_order.lines[0].id,
        "formal_system_order_no": formal_order.system_order_no,
        "report_id": history_report.id,
    }


def test_preview_classifies_unique_ambiguous_and_unmatched_lines(db_session):
    fixture = _seed_binding_fixture(db_session)
    repair = _load_repair_module()

    result = repair.classify_unbound_lines(db_session)

    assert result["summary"] == {"scanned": 4, "unique": 2, "ambiguous": 1, "unmatched": 1}
    assert [item["system_order_no"] for item in result["unique"]] == [
        fixture["unique_order"].system_order_no,
        fixture["unique_order"].system_order_no,
    ]
    assert result["ambiguous"][0]["candidate_system_order_nos"] == sorted(
        [
            fixture["ambiguous_order_a"].system_order_no,
            fixture["ambiguous_order_b"].system_order_no,
        ]
    )
    assert result["unmatched"][0]["size"] == "XL"


def test_apply_binds_only_unique_lines_updates_report_and_stays_idempotent(db_session):
    fixture = _seed_binding_fixture(db_session)
    repair = _load_repair_module()

    before_s = order_line_totals(db_session, fixture["unique_order"].lines[0].id)
    before_xs = order_line_totals(db_session, fixture["unique_order"].lines[1].id)
    assert before_s["shipped"] == 12
    assert before_xs["shipped"] == 8

    first = repair.apply_unique_bindings(db_session)
    second = repair.apply_unique_bindings(db_session)

    unique_report = db_session.get(ShipmentReport, fixture["unique_report_id"])
    ambiguous_report = db_session.get(ShipmentReport, fixture["ambiguous_report_id"])
    unmatched_report = db_session.get(ShipmentReport, fixture["unmatched_report_id"])
    unique_lines = db_session.query(ShipmentLine).filter(ShipmentLine.report_id == unique_report.id).order_by(ShipmentLine.size).all()
    ambiguous_line = db_session.query(ShipmentLine).filter(ShipmentLine.report_id == ambiguous_report.id).one()
    unmatched_line = db_session.query(ShipmentLine).filter(ShipmentLine.report_id == unmatched_report.id).one()

    assert first["bound_line_count"] == 2
    assert first["bound_report_count"] == 1
    assert second["bound_line_count"] == 0
    assert second["bound_report_count"] == 0
    assert unique_report.order_id == fixture["unique_order"].id
    assert [line.order_line_id for line in unique_lines] == [fixture["unique_order"].lines[0].id, fixture["unique_order"].lines[1].id]
    assert ambiguous_line.order_line_id is None
    assert unmatched_line.order_line_id is None

    after_s = order_line_totals(db_session, fixture["unique_order"].lines[0].id)
    after_xs = order_line_totals(db_session, fixture["unique_order"].lines[1].id)
    assert after_s["shipped"] == 12
    assert after_xs["shipped"] == 8
    assert after_s["remaining"] == 88
    assert after_xs["remaining"] == 72
    assert first["bindings"][0]["canonical_key"] == {
        "company_name": "源兴发",
        "canonical_product": "啦啦队",
        "canonical_style": "僵尸啦啦队",
        "size": "S",
    }
    assert [row["order_line_id"] for row in first["recomputed_order_lines"]] == [
        fixture["unique_order"].lines[0].id,
        fixture["unique_order"].lines[1].id,
    ]
    assert first["recomputed_order_lines"][0]["before_totals"]["shipped"] == 12
    assert first["recomputed_order_lines"][0]["after_totals"]["shipped"] == 12


def test_apply_recomputes_all_lines_sharing_the_same_unbound_pool(db_session):
    fixture = _seed_recompute_fixture(db_session)
    repair = _load_repair_module()

    legacy_before = order_line_totals(db_session, fixture["legacy_line_id"])
    formal_before = order_line_totals(db_session, fixture["formal_order_line_id"])

    assert legacy_before["shipped"] == 10
    assert formal_before["shipped"] == 2

    result = repair.apply_unique_bindings(db_session)

    legacy_after = order_line_totals(db_session, fixture["legacy_line_id"])
    formal_after = order_line_totals(db_session, fixture["formal_order_line_id"])

    assert legacy_after["shipped"] == 0
    assert legacy_after["remaining"] == 10
    assert formal_after["shipped"] == 12
    assert formal_after["remaining"] == 88
    assert result["bindings"] == [
        {
            "report_id": fixture["report_id"],
            "shipment_line_id": 1,
            "order_id": fixture["formal_order_id"],
            "order_line_id": fixture["formal_order_line_id"],
            "system_order_no": fixture["formal_system_order_no"],
            "quantity": 12,
            "size": "S",
            "canonical_key": {
                "company_name": "源兴发",
                "canonical_product": "啦啦队",
                "canonical_style": "僵尸啦啦队",
                "size": "S",
            },
        }
    ]
    assert result["recomputed_order_lines"] == [
        {
            "order_line_id": fixture["legacy_line_id"],
            "order_id": None,
            "system_order_no": "",
            "canonical_key": {
                "company_name": "源兴发",
                "canonical_product": "啦啦队",
                "canonical_style": "僵尸啦啦队",
                "size": "S",
            },
            "before_totals": {
                "ordered": 10,
                "shipped": 10,
                "returned": 0,
                "adjusted": 0,
                "closed": 0,
                "remaining": 0,
                "over_shipped": 0,
            },
            "after_totals": {
                "ordered": 10,
                "shipped": 0,
                "returned": 0,
                "adjusted": 0,
                "closed": 0,
                "remaining": 10,
                "over_shipped": 0,
            },
        },
        {
            "order_line_id": fixture["formal_order_line_id"],
            "order_id": fixture["formal_order_id"],
            "system_order_no": fixture["formal_system_order_no"],
            "canonical_key": {
                "company_name": "源兴发",
                "canonical_product": "啦啦队",
                "canonical_style": "僵尸啦啦队",
                "size": "S",
            },
            "before_totals": {
                "ordered": 100,
                "shipped": 2,
                "returned": 0,
                "adjusted": 0,
                "closed": 0,
                "remaining": 98,
                "over_shipped": 0,
            },
            "after_totals": {
                "ordered": 100,
                "shipped": 12,
                "returned": 0,
                "adjusted": 0,
                "closed": 0,
                "remaining": 88,
                "over_shipped": 0,
            },
        },
    ]


def test_cli_preview_and_apply_are_explicit_and_repeatable(tmp_path: Path):
    repair = _load_repair_module()
    database_path = tmp_path / "repair-binding.sqlite"
    preview_path = tmp_path / "repair-preview.json"
    audit_path = tmp_path / "repair-audit.json"
    second_audit_path = tmp_path / "repair-audit-second.json"

    with pytest.raises(SystemExit):
        repair.main([])

    session = _create_file_session(database_path)
    try:
        _seed_binding_fixture(session)
    finally:
        session.close()

    assert repair.main(["--database", str(database_path), "--preview", str(preview_path)]) == 0
    assert repair.main(["--database", str(database_path), "--apply", "--audit", str(audit_path)]) == 0
    assert repair.main(["--database", str(database_path), "--apply", "--audit", str(second_audit_path)]) == 0

    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    first_audit = json.loads(audit_path.read_text(encoding="utf-8"))
    second_audit = json.loads(second_audit_path.read_text(encoding="utf-8"))

    assert preview["summary"] == {"scanned": 4, "unique": 2, "ambiguous": 1, "unmatched": 1}
    assert first_audit["bound_line_count"] == 2
    assert first_audit["bound_report_count"] == 1
    assert second_audit["bound_line_count"] == 0
    assert second_audit["bound_report_count"] == 0


def test_cli_rejects_preview_and_apply_together(db_session, tmp_path: Path):
    repair = _load_repair_module()
    database_path = tmp_path / "repair-binding.sqlite"
    session = _create_file_session(database_path)
    try:
        _seed_binding_fixture(session)
    finally:
        session.close()

    with pytest.raises(SystemExit):
        repair.main(
            [
                "--database",
                str(database_path),
                "--preview",
                str(tmp_path / "preview.json"),
                "--apply",
                "--audit",
                str(tmp_path / "audit.json"),
            ]
        )


def test_non_sqlite_apply_requires_explicit_backup_confirmation_before_opening_session(monkeypatch, tmp_path: Path):
    repair = _load_repair_module()
    preview_path = tmp_path / "preview.json"
    audit_path = tmp_path / "audit.json"
    opened = {"count": 0}

    def fake_open_session(_database_url):
        opened["count"] += 1
        return SimpleNamespace(close=lambda: None)

    monkeypatch.setattr(repair, "open_session", fake_open_session)

    with pytest.raises(ValueError, match="confirm-production-backup"):
        repair.main(
            [
                "--database",
                "postgresql://user:pass@example.com/app",
                "--apply",
                "--audit",
                str(audit_path),
            ]
        )

    assert opened["count"] == 0

    monkeypatch.setattr(repair, "classify_unbound_lines", lambda _session: {"summary": {"scanned": 0, "unique": 0, "ambiguous": 0, "unmatched": 0}, "unique": [], "ambiguous": [], "unmatched": []})
    assert repair.main(
        [
            "--database",
            "postgresql://user:pass@example.com/app",
            "--preview",
            str(preview_path),
        ]
    ) == 0
    assert opened["count"] == 1
