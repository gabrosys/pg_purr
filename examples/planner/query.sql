-- The 13-table INNER-JOIN query used across scripts 02, 03, 04.
-- Every table in the schema participates. Fully schema-qualified because
-- purr.quantum_query_plan's search_path excludes public.
SELECT
    c.name           AS customer,
    co.name          AS country,
    r.name           AS region,
    ci.name          AS billing_city,
    a.street         AS billing_street,
    o.placed_at      AS order_placed_at,
    p.sku            AS product_sku,
    cat.name         AS category,
    s.name           AS supplier,
    w.name           AS fulfilling_warehouse,
    inv.qty          AS stock_on_hand,
    sh.shipped_at    AS shipment_date,
    oi.qty           AS ordered_qty
FROM public.customers     c
INNER JOIN public.countries   co  ON co.id  = c.country_id
INNER JOIN public.regions     r   ON r.id   = co.region_id
INNER JOIN public.addresses   a   ON a.customer_id = c.id
INNER JOIN public.cities      ci  ON ci.id  = a.city_id
INNER JOIN public.orders      o   ON o.customer_id = c.id
INNER JOIN public.order_items oi  ON oi.order_id   = o.id
INNER JOIN public.products    p   ON p.id   = oi.product_id
INNER JOIN public.categories  cat ON cat.id = p.category_id
INNER JOIN public.suppliers   s   ON s.id   = p.supplier_id
INNER JOIN public.shipments   sh  ON sh.order_id   = o.id
INNER JOIN public.warehouses  w   ON w.id   = sh.warehouse_id
INNER JOIN public.inventory   inv ON inv.product_id = p.id AND inv.warehouse_id = w.id
WHERE o.placed_at > '2026-01-01'
