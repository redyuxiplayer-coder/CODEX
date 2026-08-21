# Task 4 Report

## RED

- Added `tests/test_repair_unique_shipment_bindings.py`.
- Ran `python -m pytest tests/test_repair_unique_shipment_bindings.py -q`.
- Confirmed RED because `scripts/repair_unique_shipment_order_bindings.py` did not exist yet, so all three tests failed with `FileNotFoundError`.
- Review round 2 added failing tests for:
  - non-SQLite `--apply` safety before any connection attempt
  - `--preview` / `--apply` argparse mutual exclusion
  - recomputing every active order line that shares the same historical unbound pool
  - richer audit payload for bindings and rebuilt order lines
- Verified second RED with `python -m pytest tests/test_repair_unique_shipment_bindings.py -q` showing 4 failures at the exact missing behaviors above.

## GREEN

- Added `scripts/repair_unique_shipment_order_bindings.py`.
- Implemented read-only preview classification for approved reports with `shipment_lines.order_line_id IS NULL`.
- Apply mode only binds rows whose canonical `(company, product, style, size)` resolves to exactly one active formal order line.
- Apply mode leaves ambiguous and unmatched rows untouched.
- Apply mode updates `shipment_reports.order_id` only when every report line is bound and all lines point to the same `sales_orders.id`.
- Apply mode now collects every canonical key touched by unique bindings, finds all active matching `order_lines` using the same allocation key as `allocated_unbound_for_line(...)`, records before totals, rebuilds each line ledger in one transaction, then records after totals.
- Non-SQLite `--apply` now requires `--confirm-production-backup`, and that guard runs before `open_session()` / `create_engine()`.
- `--preview` and `--apply` now use an argparse mutually exclusive group, so both flags cannot be supplied together.
- Audit payload now includes per-binding `report_id` / `shipment_line_id` / `order_line_id` / `system_order_no` / canonical key / quantity, plus `recomputed_order_lines` with before/after totals for every rebuilt line.
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
  - Result: `scanned=2`, `bound_line_count=0`, `bound_report_count=0`
- Note: one earlier attempt accidentally ran the three drill commands in parallel against the same SQLite file; I discarded that output and re-ran the drill serially. Only the serial rerun above is valid evidence.

## Verification

- `python -m pytest tests/test_repair_unique_shipment_bindings.py -q`
- `python -m pytest tests/test_repair_unique_shipment_bindings.py tests/test_shipment_order_binding.py tests/test_shipment_order_display.py tests/test_ledger.py -q`
- Latest result: `25 passed`

## Commit

- Implementation: `6a08f2a` `fix: bind uniquely matched historical shipments`
- Report evidence: `5609134` `docs: record task 4 repair evidence`
- Review fix round: `d727b1f` `fix: harden shipment binding repair apply`

## Focus

- Script currently supports explicit `--database` or `--database-url-env` only; it does not auto-read `.env`, by design.
- Manual SQL audit and JSON audit now show the same three buckets: unique-safe, ambiguous, unmatched.
- Production-capable apply remains available, but non-SQLite runs now require an explicit backup confirmation flag before any connection is opened.
