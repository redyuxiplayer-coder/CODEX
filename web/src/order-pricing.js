export function formatMoney(value) {
  if (value === null || value === undefined || value === "") return "未填写";
  const exact = String(value).match(/^(\d+)(?:\.(\d{1,2}))?$/);
  if (exact) return `¥${exact[1]}.${(exact[2] || "").padEnd(2, "0")}`;
  return `¥${Number(value).toFixed(2)}`;
}

export function priceStatusText(summary) {
  if (!summary) return "";
  if (summary.is_complete) return `订单总金额 ${formatMoney(summary.total_amount)}`;
  return `总金额待补全；已填写小计 ${formatMoney(summary.known_subtotal)}；${summary.missing_price_count} 个尺码未填写`;
}

export function priceSaveSnapshot(draft, line) {
  return {
    unitPrice: draft === "" || draft == null ? null : draft,
    expectedUnitPrice: line.unit_price,
    expectedPriceRevision: line.price_revision,
  };
}

export function capturePriceEditBaseline(orderId, line) {
  return Object.freeze({
    orderId,
    lineId: line.id,
    unit_price: line.unit_price,
    price_revision: line.price_revision,
  });
}

export function createPriceSaveSession() {
  let generation = 0;
  return {
    capture() { return generation; },
    invalidate() { generation += 1; },
    async run(token, { update, reload, onSuccess, onConflict, onConflictReloadError, onError, onSettled, isCurrent = () => true }) {
      const current = () => token === generation && isCurrent();
      try {
        await update();
        if (!current()) return;
        await reload();
        if (!current()) return;
        onSuccess();
      } catch (error) {
        if (!current()) return;
        if (error.status === 409 && onConflict) {
          try {
            const refreshedOrder = await reload();
            if (current()) onConflict(error, refreshedOrder);
          } catch (reloadError) {
            if (current()) (onConflictReloadError || onError)(reloadError);
          }
        } else {
          onError(error);
        }
      } finally {
        if (current()) onSettled();
      }
    },
  };
}
