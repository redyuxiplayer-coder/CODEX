-- 订单/发货数据一致性排查
-- 服务器用法：sudo -u postgres psql -d zy_shipping -f /home/ubuntu/zy-shipping/scripts/audit_orders.sql

\echo '=== A. 已通过但未绑定订单行的发货（历史导入/漏绑定） ==='
SELECT r.id AS report_id, r.ship_date, r.status, r.company_name, r.product_name, r.style_name,
       l.size, l.quantity,
       COALESCE((SELECT canonical_product FROM product_aliases a
                 WHERE a.company_name=r.company_name AND a.alias_product=r.product_name
                   AND a.alias_style=r.style_name AND a.is_active = TRUE LIMIT 1), r.product_name) AS c_product,
       COALESCE((SELECT canonical_style FROM product_aliases a
                 WHERE a.company_name=r.company_name AND a.alias_product=r.product_name
                   AND a.alias_style=r.style_name AND a.is_active = TRUE LIMIT 1), r.style_name) AS c_style
FROM shipment_reports r
JOIN shipment_lines l ON l.report_id = r.id
WHERE l.order_line_id IS NULL
  AND r.status IN ('auto_approved','approved_after_edit')
ORDER BY r.company_name, c_product, c_style, l.size, r.ship_date;

\echo '=== B. 未绑定发货找不到任何匹配订单（孤儿发货，谁都没归入） ==='
SELECT u.report_id, u.ship_date, u.company_name, u.style_name, u.size, u.quantity, u.c_style
FROM (
  SELECT r.id AS report_id, r.ship_date, r.company_name, r.style_name, l.size, l.quantity,
         COALESCE((SELECT canonical_product FROM product_aliases a
                   WHERE a.company_name=r.company_name AND a.alias_product=r.product_name
                     AND a.alias_style=r.style_name AND a.is_active = TRUE LIMIT 1), r.product_name) AS c_product,
         COALESCE((SELECT canonical_style FROM product_aliases a
                   WHERE a.company_name=r.company_name AND a.alias_product=r.product_name
                     AND a.alias_style=r.style_name AND a.is_active = TRUE LIMIT 1), r.style_name) AS c_style
  FROM shipment_reports r
  JOIN shipment_lines l ON l.report_id = r.id
  WHERE l.order_line_id IS NULL AND r.status IN ('auto_approved','approved_after_edit')
) u
LEFT JOIN (
  SELECT o.company_id, c.name AS company, o.product_name, o.style_name, o.size,
         COALESCE((SELECT canonical_product FROM product_aliases a
                   WHERE a.company_name=c.name AND a.alias_product=o.product_name
                     AND a.alias_style=o.style_name AND a.is_active = TRUE LIMIT 1), o.product_name) AS c_product,
         COALESCE((SELECT canonical_style FROM product_aliases a
                   WHERE a.company_name=c.name AND a.alias_product=o.product_name
                     AND a.alias_style=o.style_name AND a.is_active = TRUE LIMIT 1), o.style_name) AS c_style
  FROM order_lines o
  JOIN companies c ON c.id = o.company_id
  WHERE o.is_active = TRUE
) o
  ON o.company = u.company_name AND o.c_product = u.c_product AND o.c_style = u.c_style AND o.size = u.size
WHERE o.company IS NULL
ORDER BY u.company_name, u.c_style, u.size;

\echo '=== C. 同公司+款式+尺码有多个活跃订单行（未绑定发货分配有歧义） ==='
SELECT c.name AS company,
       COALESCE((SELECT canonical_product FROM product_aliases a
                 WHERE a.company_name=c.name AND a.alias_product=o.product_name
                   AND a.alias_style=o.style_name AND a.is_active = TRUE LIMIT 1), o.product_name) AS c_product,
       COALESCE((SELECT canonical_style FROM product_aliases a
                 WHERE a.company_name=c.name AND a.alias_product=o.product_name
                   AND a.alias_style=o.style_name AND a.is_active = TRUE LIMIT 1), o.style_name) AS c_style,
       o.size, COUNT(*) AS order_count, SUM(o.quantity) AS total_ordered
FROM order_lines o
JOIN companies c ON c.id = o.company_id
WHERE o.is_active = TRUE
GROUP BY c.name, c_product, c_style, o.size
HAVING COUNT(*) > 1
ORDER BY c.name, c_product, c_style, o.size;

\echo '=== D. 已绑定订单行但款式/尺码/公司对不上（疑似绑定错误） ==='
SELECT r.id AS report_id, r.ship_date, r.company_name AS report_company, r.style_name AS report_style,
       l.size AS report_size, l.quantity,
       o.id AS order_line_id, c.name AS order_company, o.style_name AS order_style, o.size AS order_size
FROM shipment_lines l
JOIN shipment_reports r ON r.id = l.report_id
JOIN order_lines o ON o.id = l.order_line_id
JOIN companies c ON c.id = o.company_id
WHERE r.status IN ('auto_approved','approved_after_edit')
  AND (
    r.company_name != c.name
    OR l.size != o.size
    OR COALESCE((SELECT canonical_product FROM product_aliases a
                 WHERE a.company_name=r.company_name AND a.alias_product=r.product_name
                   AND a.alias_style=r.style_name AND a.is_active = TRUE LIMIT 1), r.product_name)
       != COALESCE((SELECT canonical_product FROM product_aliases a
                    WHERE a.company_name=c.name AND a.alias_product=o.product_name
                      AND a.alias_style=o.style_name AND a.is_active = TRUE LIMIT 1), o.product_name)
    OR COALESCE((SELECT canonical_style FROM product_aliases a
                 WHERE a.company_name=r.company_name AND a.alias_product=r.product_name
                   AND a.alias_style=r.style_name AND a.is_active = TRUE LIMIT 1), r.style_name)
       != COALESCE((SELECT canonical_style FROM product_aliases a
                    WHERE a.company_name=c.name AND a.alias_product=o.product_name
                      AND a.alias_style=o.style_name AND a.is_active = TRUE LIMIT 1), o.style_name)
  )
ORDER BY r.id;

\echo '=== E. 绑定发货超过下单数量（超发/重复绑定） ==='
SELECT o.id AS order_line_id, c.name AS company, o.style_name, o.size, o.quantity AS ordered,
       SUM(l.quantity) AS bound_shipped
FROM order_lines o
JOIN companies c ON c.id = o.company_id
LEFT JOIN shipment_lines l ON l.order_line_id = o.id
LEFT JOIN shipment_reports r ON r.id = l.report_id AND r.status IN ('auto_approved','approved_after_edit')
WHERE o.is_active = TRUE
GROUP BY o.id, c.name, o.style_name, o.size, o.quantity
HAVING SUM(l.quantity) > o.quantity
ORDER BY c.name, o.style_name, o.size;
