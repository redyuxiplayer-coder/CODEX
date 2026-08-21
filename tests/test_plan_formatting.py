from pathlib import Path


PLAN = Path("docs/superpowers/plans/2026-08-21-worker-shipment-report-and-binding.md")


def test_worker_shipment_plan_has_no_trailing_whitespace_or_blank_eof_line():
    text = PLAN.read_text(encoding="utf-8")

    assert all(line == line.rstrip(" \t") for line in text.splitlines())
    assert not text.endswith("\n\n")
