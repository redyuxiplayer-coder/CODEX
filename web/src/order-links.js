export function shipmentOrderTarget(line) {
  if (line.sales_order_id) {
    return `/sales-orders/${line.sales_order_id}?line=${line.order_line_id}`;
  }
  return `/order-lines/${line.order_line_id}`;
}
