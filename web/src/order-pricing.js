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
