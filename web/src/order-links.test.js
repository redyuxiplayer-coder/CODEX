import test from "node:test";
import assert from "node:assert/strict";
import { shipmentOrderTarget } from "./order-links.js";

test("a formal shipment line opens its complete order and selects its size", () => {
  assert.equal(
    shipmentOrderTarget({ order_line_id: 42, sales_order_id: 7 }),
    "/sales-orders/7?line=42",
  );
});

test("a historical line without a formal order keeps its existing detail page", () => {
  assert.equal(
    shipmentOrderTarget({ order_line_id: 42, sales_order_id: null }),
    "/order-lines/42",
  );
});
