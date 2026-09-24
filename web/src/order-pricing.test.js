import test from "node:test";
import assert from "node:assert/strict";
import { createPriceSaveSession, formatMoney, priceStatusText } from "./order-pricing.js";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

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

test("an A-to-B-to-A stale save cannot reload, close a new edit, or clear its loading state", async () => {
  const session = createPriceSaveSession();
  const oldUpdate = deferred();
  const newUpdate = deferred();
  const effects = [];
  let editor = "old A line";
  let saving = true;
  const oldSave = session.run(session.capture(), {
    update: () => oldUpdate.promise,
    reload: () => effects.push("old reload"),
    onSuccess: () => { editor = null; effects.push("old success"); },
    onError: () => effects.push("old error"),
    onSettled: () => { saving = false; effects.push("old settled"); },
  });

  session.invalidate(); // A -> B
  session.invalidate(); // B -> A
  session.invalidate(); // Open the same line editor again.
  editor = "new A line";
  const newSave = session.run(session.capture(), {
    update: () => newUpdate.promise,
    reload: () => effects.push("new reload"),
    onSuccess: () => { editor = null; effects.push("new success"); },
    onError: () => effects.push("new error"),
    onSettled: () => { saving = false; effects.push("new settled"); },
  });

  oldUpdate.resolve();
  await oldSave;
  assert.deepEqual(effects, []);
  assert.equal(editor, "new A line");
  assert.equal(saving, true);

  newUpdate.resolve();
  await newSave;
  assert.deepEqual(effects, ["new reload", "new success", "new settled"]);
  assert.equal(saving, false);
});

test("an invalidated save hides a stale server error", async () => {
  const session = createPriceSaveSession();
  const update = deferred();
  const effects = [];
  const save = session.run(session.capture(), {
    update: () => update.promise,
    reload: () => effects.push("reload"),
    onSuccess: () => effects.push("success"),
    onError: () => effects.push("error"),
    onSettled: () => effects.push("settled"),
  });
  session.invalidate();
  update.reject(new Error("old request failed"));
  await save;
  assert.deepEqual(effects, []);
});

test("switching orders during reload suppresses the old success and cleanup", async () => {
  const session = createPriceSaveSession();
  const reload = deferred();
  const effects = [];
  const save = session.run(session.capture(), {
    update: async () => {},
    reload: () => { effects.push("reload"); return reload.promise; },
    onSuccess: () => effects.push("success"),
    onError: () => effects.push("error"),
    onSettled: () => effects.push("settled"),
  });
  await Promise.resolve();
  session.invalidate();
  reload.resolve();
  await save;
  assert.deepEqual(effects, ["reload"]);
});
