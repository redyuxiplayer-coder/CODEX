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

\echo '=== A1. / B. / C. 按修复 CLI 同一口径分类：唯一候选 / 歧义 / 无匹配 ==='
WITH normalized_aliases AS (
  SELECT a.id AS alias_id,
         BTRIM(a.company_name) AS company_name,
         BTRIM(a.alias_product) AS alias_product,
         BTRIM(a.alias_style) AS alias_style,
         BTRIM(a.canonical_product) AS canonical_product,
         BTRIM(a.canonical_style) AS canonical_style
  FROM product_aliases a
  WHERE a.is_active = TRUE
),
alias_assignments AS (
  SELECT alias_id, 1 AS assignment_order, company_name,
         alias_product AS key_product, alias_style AS key_style,
         canonical_product, canonical_style
  FROM normalized_aliases
  UNION ALL
  SELECT alias_id, 2 AS assignment_order, company_name,
         canonical_product AS key_product, canonical_style AS key_style,
         canonical_product, canonical_style
  FROM normalized_aliases
),
canonical_aliases AS (
  SELECT DISTINCT ON (company_name, key_product, key_style)
         company_name, key_product, key_style, canonical_product, canonical_style
  FROM alias_assignments
  ORDER BY company_name, key_product, key_style, alias_id DESC, assignment_order DESC
),
unbound AS (
  SELECT r.id AS report_id, BTRIM(r.ship_date) AS ship_date,
         BTRIM(r.company_name) AS company_name,
         BTRIM(r.product_name) AS product_name,
         BTRIM(r.style_name) AS style_name,
         l.id AS shipment_line_id, BTRIM(l.size) AS size, l.quantity,
         COALESCE(a.canonical_product, BTRIM(r.product_name)) AS c_product,
         COALESCE(a.canonical_style, BTRIM(r.style_name)) AS c_style
  FROM shipment_reports r
  JOIN shipment_lines l ON l.report_id = r.id
  LEFT JOIN canonical_aliases a
    ON a.company_name = BTRIM(r.company_name)
   AND a.key_product = BTRIM(r.product_name)
   AND a.key_style = BTRIM(r.style_name)
  WHERE l.order_line_id IS NULL
    AND r.status IN ('auto_approved','approved_after_edit')
),
formal_lines AS (
  SELECT o.id AS order_line_id, o.order_id, so.system_order_no, so.order_date,
         BTRIM(c.name) AS company_name, BTRIM(o.size) AS size,
         COALESCE(a.canonical_product, BTRIM(o.product_name)) AS c_product,
         COALESCE(a.canonical_style, BTRIM(o.style_name)) AS c_style
  FROM order_lines o
  JOIN sales_orders so ON so.id = o.order_id
  JOIN companies c ON c.id = o.company_id
  LEFT JOIN canonical_aliases a
    ON a.company_name = BTRIM(c.name)
   AND a.key_product = BTRIM(o.product_name)
   AND a.key_style = BTRIM(o.style_name)
  WHERE o.is_active = TRUE
    AND o.order_id IS NOT NULL
    AND so.status = 'active'
),
repair_buckets AS (
  SELECT u.report_id, u.ship_date, u.shipment_line_id, u.company_name,
         u.product_name, u.style_name, u.c_product, u.c_style, u.size, u.quantity,
         COUNT(f.order_line_id) AS candidate_count,
         ARRAY_AGG(f.order_line_id ORDER BY f.order_line_id)
           FILTER (WHERE f.order_line_id IS NOT NULL) AS candidate_order_line_ids,
         ARRAY_AGG(f.order_id ORDER BY f.order_line_id)
           FILTER (WHERE f.order_id IS NOT NULL) AS candidate_order_ids,
         ARRAY_AGG(f.system_order_no ORDER BY f.order_line_id)
           FILTER (WHERE f.system_order_no IS NOT NULL) AS candidate_system_order_nos,
         ARRAY_AGG(f.order_date ORDER BY f.order_line_id)
           FILTER (WHERE f.order_date IS NOT NULL) AS candidate_order_dates
  FROM unbound u
  LEFT JOIN formal_lines f
    ON f.company_name = u.company_name
   AND f.c_product = u.c_product
   AND f.c_style = u.c_style
   AND f.size = u.size
  GROUP BY u.shipment_line_id, u.report_id, u.ship_date, u.company_name,
           u.product_name, u.style_name, u.c_product, u.c_style, u.size, u.quantity
)
SELECT CASE
         WHEN candidate_count = 1 THEN 'unique'
         WHEN candidate_count > 1 THEN 'ambiguous'
         ELSE 'unmatched'
       END AS repair_bucket,
       report_id, ship_date, shipment_line_id, company_name, product_name, style_name,
       c_product, c_style, size, quantity, candidate_count,
       candidate_order_line_ids, candidate_order_ids, candidate_system_order_nos, candidate_order_dates
FROM repair_buckets
ORDER BY CASE
           WHEN candidate_count = 1 THEN 1
           WHEN candidate_count > 1 THEN 2
           ELSE 3
         END,
         company_name, c_product, c_style, size, ship_date, report_id, shipment_line_id;

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
       SUM(CASE WHEN r.status IN ('auto_approved','approved_after_edit') THEN l.quantity ELSE 0 END) AS bound_shipped
FROM order_lines o
JOIN companies c ON c.id = o.company_id
LEFT JOIN shipment_lines l ON l.order_line_id = o.id
LEFT JOIN shipment_reports r ON r.id = l.report_id
WHERE o.is_active = TRUE
GROUP BY o.id, c.name, o.style_name, o.size, o.quantity
HAVING SUM(CASE WHEN r.status IN ('auto_approved','approved_after_edit') THEN l.quantity ELSE 0 END) > o.quantity
ORDER BY c.name, o.style_name, o.size;
