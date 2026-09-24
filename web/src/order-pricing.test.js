import test from "node:test";
import assert from "node:assert/strict";
import { formatMoney, priceStatusText } from "./order-pricing.js";

test("an unknown price displays as unfilled rather than zero", () => {
  assert.equal(formatMoney(null), "未填写");
  assert.equal(formatMoney(undefined), "未填写");
  assert.equal(formatMoney(""), "未填写");
});

test("a confirmed zero price displays two decimal places", () => {
  assert.equal(formatMoney(0), "¥0.00");
  assert.equal(formatMoney("0.00"), "¥0.00");
});

test("a complete order displays its total", () => {
  assert.equal(priceStatusText({ is_complete: true, total_amount: "1230.00" }), "订单总金额 ¥1230.00");
});

test("an incomplete order shows its known subtotal and missing size count", () => {
  assert.equal(
    priceStatusText({ is_complete: false, known_subtotal: "1230.00", missing_price_count: 2 }),
    "总金额待补全；已填写小计 ¥1230.00；2 个尺码未填写",
  );
});

test("large exact decimal amounts retain their cents", () => {
  assert.equal(formatMoney("999999999998999990000000000.03"), "¥999999999998999990000000000.03");
});
