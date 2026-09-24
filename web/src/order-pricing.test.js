import test from "node:test";
import assert from "node:assert/strict";
import { updateSalesOrderLineUnitPrice } from "./api.js";
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

test("price update payload keeps unknown and confirmed zero previous prices distinct", async () => {
  const originalFetch = globalThis.fetch;
  const bodies = [];
  globalThis.fetch = async (_path, options) => {
    bodies.push(JSON.parse(options.body));
    return new Response("{}", { status: 200 });
  };
  try {
    await updateSalesOrderLineUnitPrice(7, 42, 0, null);
    await updateSalesOrderLineUnitPrice(7, 42, null, "0.00");
    assert.deepEqual(bodies, [
      { unit_price: 0, expected_unit_price: null },
      { unit_price: null, expected_unit_price: "0.00" },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("price update exposes a 409 response status to the editor", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "单价已变更" }), { status: 409 });
  try {
    await assert.rejects(
      updateSalesOrderLineUnitPrice(7, 42, "9.99", null),
      (error) => error.status === 409 && error.message === "单价已变更",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("an active price conflict reloads current data and keeps the editor open", async () => {
  const session = createPriceSaveSession();
  const conflict = Object.assign(new Error("单价已变更"), { status: 409 });
  const effects = [];
  let editorOpen = true;
  let saving = true;
  await session.run(session.capture(), {
    update: () => Promise.reject(conflict),
    reload: () => { effects.push("reload"); },
    onConflict: () => effects.push("conflict message"),
    onSuccess: () => { editorOpen = false; },
    onError: () => effects.push("generic error"),
    onSettled: () => { saving = false; effects.push("settled"); },
  });
  assert.deepEqual(effects, ["reload", "conflict message", "settled"]);
  assert.equal(editorOpen, true);
  assert.equal(saving, false);
});

test("a stale conflict cannot refresh or message a reopened editor", async () => {
  const session = createPriceSaveSession();
  const update = deferred();
  const effects = [];
  const save = session.run(session.capture(), {
    update: () => update.promise,
    reload: () => effects.push("reload"),
    onConflict: () => effects.push("conflict message"),
    onSuccess: () => effects.push("success"),
    onError: () => effects.push("generic error"),
    onSettled: () => effects.push("settled"),
  });
  session.invalidate();
  update.reject(Object.assign(new Error("单价已变更"), { status: 409 }));
  await save;
  assert.deepEqual(effects, []);
});

test("navigation during conflict refresh suppresses the old message and loading cleanup", async () => {
  const session = createPriceSaveSession();
  const refresh = deferred();
  const refreshStarted = deferred();
  const effects = [];
  const save = session.run(session.capture(), {
    update: () => Promise.reject(Object.assign(new Error("单价已变更"), { status: 409 })),
    reload: () => { refreshStarted.resolve(); return refresh.promise; },
    onConflict: () => effects.push("conflict message"),
    onSuccess: () => effects.push("success"),
    onError: () => effects.push("generic error"),
    onSettled: () => effects.push("settled"),
  });
  let timeout;
  try {
    await Promise.race([
      refreshStarted.promise,
      new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error("conflict reload not started")), 250); }),
    ]);
  } finally {
    clearTimeout(timeout);
  }
  session.invalidate();
  refresh.resolve();
  await save;
  assert.deepEqual(effects, []);
});
