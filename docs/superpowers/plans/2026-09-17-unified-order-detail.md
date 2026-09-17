# Unified Formal Order Detail Implementation Plan

> For agentic workers: implement these tasks in order. This session uses inline execution with review after each test cycle.

**Goal:** Show the same complete formal order page from both order-number links, with customer order number immediately visible.

**Architecture:** Add current line totals to the formal order detail API and formal order IDs to shipment-line payloads. Route both links to one Vue page. Embed the existing order-line operations in that page for the selected size.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, Vue 3, Vite, Node test runner.

## Global Constraints

- Preserve the server's uncommitted September files and the main checkout's dirty `web/dist`.
- Do not deploy or modify production data during this implementation.
- Keep historical shipment lines without formal orders on `/order-lines/:id`.
- Record development and deployment separately in the Obsidian project notes.

---

### Task 1: API payloads

**Files:** `tests/test_formal_orders_api.py`, `tests/test_shipment_order_display.py`, `app/api_v1.py`.

- [ ] Add tests that request formal order details after an approved shipment and assert size totals from `order_line_totals`.
- [ ] Add a shipment payload test asserting each bound line includes its actual `sales_order_id`, including cross-order reports.
- [ ] Run the new tests and confirm the missing fields fail.
- [ ] Add only the required response fields to the existing serializers.
- [ ] Run the focused tests again and verify they pass.

### Task 2: Shared navigation and complete page

**Files:** `web/src/views/Shipments.vue`, `web/src/views/SalesOrderDetail.vue`, `web/src/views/OrderLine.vue`, `web/src/order-links.js`, `web/src/order-links.test.js`.

- [ ] Write a Node test that expects formal lines to resolve to `/sales-orders/:id?line=:lineId` and historical lines to remain `/order-lines/:lineId`; confirm the test fails.
- [ ] Implement the path helper and change the shipment button to use it.
- [ ] Show all-size totals and customer order number on the formal page; select a size from the query or first row.
- [ ] Make `OrderLine.vue` embeddable by ID while preserving its standalone route and actions; refresh the summary after an embedded action.
- [ ] Run the Node test and `npm run build`.

### Task 3: Verification and handoff

**Files:** Obsidian `07-更新日志.md`, `11-共享接手状态.md`.

- [ ] Run focused Python tests, Node test, build, and full Python test suite; record exact results and any pre-existing failure.
- [ ] Review Git diff and ensure no production code or data changed.
- [ ] Commit the feature branch and record the commit with development status only. Do not label it deployed.
