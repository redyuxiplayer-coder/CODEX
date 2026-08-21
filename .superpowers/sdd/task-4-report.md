# Task 4 Report

## RED

- Added `tests/test_repair_unique_shipment_bindings.py`.
- Ran `python -m pytest tests/test_repair_unique_shipment_bindings.py -q`.
- Confirmed RED because `scripts/repair_unique_shipment_order_bindings.py` did not exist yet, so all three tests failed with `FileNotFoundError`.

## GREEN

- Added `scripts/repair_unique_shipment_order_bindings.py`.
- Implemented read-only preview classification for approved reports with `shipment_lines.order_line_id IS NULL`.
- Apply mode only binds rows whose canonical `(company, product, style, size)` resolves to exactly one active formal order line.
- Apply mode leaves ambiguous and unmatched rows untouched.
- Apply mode updates `shipment_reports.order_id` only when every report line is bound and all lines point to the same `sales_orders.id`.
- Apply mode rebuilds affected report ledgers through `recompute_for_report(...)` so bound rows replace prior unbound allocation instead of doubling shipped quantity.
- Extended `scripts/audit_orders.sql` with a read-only `A1` section for exactly-one formal candidate rows.

## Idempotence Drill

- Seeded a local SQLite fixture at `tmp/task4-drill/repair-binding.sqlite`.
- Preview:
  - `python scripts/repair_unique_shipment_order_bindings.py --database tmp/task4-drill/repair-binding.sqlite --preview tmp/task4-drill/repair-preview.json`
  - Result: `scanned=4`, `unique=2`, `ambiguous=1`, `unmatched=1`
- First apply:
  - `python scripts/repair_unique_shipment_order_bindings.py --database tmp/task4-drill/repair-binding.sqlite --apply --audit tmp/task4-drill/repair-audit.json`
  - Result: `bound_line_count=2`, `bound_report_count=1`
- Second apply:
  - `python scripts/repair_unique_shipment_order_bindings.py --database tmp/task4-drill/repair-binding.sqlite --apply --audit tmp/task4-drill/repair-audit-second.json`
  - Result: `bound_line_count=0`, `bound_report_count=0`

## Verification

- `python -m pytest tests/test_repair_unique_shipment_bindings.py -q`
- `python -m pytest tests/test_repair_unique_shipment_bindings.py tests/test_shipment_order_binding.py tests/test_shipment_order_display.py tests/test_ledger.py -q`
- Latest result: `22 passed`

## Commit

- Implementation: `6a08f2a` `fix: bind uniquely matched historical shipments`
- Report update: pending until this file is committed

## Focus

- Script currently supports explicit `--database` or `--database-url-env` only; it does not auto-read `.env`, by design.
- Manual SQL audit and JSON audit now show the same three buckets: unique-safe, ambiguous, unmatched.
