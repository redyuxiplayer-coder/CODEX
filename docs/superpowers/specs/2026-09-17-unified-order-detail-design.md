# Unified Formal Order Detail Design

## Goal

The system order number in Formal Orders and the order number in Shipments open the same complete formal-order detail page. A user arriving from a shipment can immediately see the customer order number and the relevant size's fulfillment history without another search.

## Current cause

Formal Orders links to `/sales-orders/:id`, which shows order metadata and sizes. Shipments links to `/order-lines/:id`, which shows fulfillment for one size. The two routes use different API payloads; the latter omits `customer_order_no`.

## Behavior

- Both links for a formally bound line open `/sales-orders/:id`. The shipment link includes `?line=:lineId` to select that size.
- The formal order page shows system and customer order numbers prominently, the existing order metadata and archive controls, and a table for every size with ordered, shipped, returned, adjusted, closed, remaining, and customer SKU.
- Below the table, the selected size shows the existing detailed fulfillment, ledger, returns, adjustments, closes, and comments, including existing admin actions. Formal Orders defaults to the first size; the shipment link selects its own size.
- Historical lines without a formal order continue to open the existing `/order-lines/:id` page. Cross-order shipment reports use each line's actual formal order ID; the report-level order ID is never used as a substitute.
- Switching sizes changes the selected detail without losing the order header. Changes made in the selected detail refresh the order summary.

## Data and safety

- `GET /api/v1/sales-orders/:id` adds each line's current totals using the existing `order_line_totals` calculation. It retains the existing response fields and authorization.
- Shipment report line payloads add `sales_order_id` from the line's bound formal order. This is read-only metadata.
- No database migration or production data write is needed. The initial implementation and verification stay local until the server's existing uncommitted changes are reconciled.

## Verification

- API tests cover formal order totals and shipment line order IDs, including multiple formal orders in one report.
- A small frontend path test covers formal and historical links. Build the Vue app and run the relevant Python tests.
- Confirm the two entrypoints share the formal route and that the selected size's detail still exposes all existing actions.
