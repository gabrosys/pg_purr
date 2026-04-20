-- Online retail platform — 13-table schema + seed for the pg_purr planner demo.
-- About 20 000 rows total; seeds in under 10 seconds on a laptop.

-- Drop in reverse-dependency order so re-runs are clean.
DROP TABLE IF EXISTS public.shipments, public.order_items, public.orders,
    public.inventory, public.warehouses, public.products, public.categories,
    public.suppliers, public.addresses, public.customers, public.cities,
    public.countries, public.regions CASCADE;

-- 1. regions (7)
CREATE TABLE public.regions (
    id   INT PRIMARY KEY,
    name TEXT NOT NULL
);
INSERT INTO public.regions (id, name) VALUES
    (1, 'EMEA'),
    (2, 'North America'),
    (3, 'LATAM'),
    (4, 'APAC'),
    (5, 'Middle East & Africa'),
    (6, 'Oceania'),
    (7, 'Antarctica');

-- 2. countries (200)
CREATE TABLE public.countries (
    id        INT PRIMARY KEY,
    region_id INT NOT NULL REFERENCES public.regions(id),
    code      TEXT NOT NULL,
    name      TEXT NOT NULL
);
INSERT INTO public.countries (id, region_id, code, name)
SELECT g, ((g - 1) % 7) + 1, 'C' || lpad(g::text, 3, '0'), 'Country ' || g
FROM generate_series(1, 200) g;

-- 3. cities (500)
CREATE TABLE public.cities (
    id         INT PRIMARY KEY,
    country_id INT NOT NULL REFERENCES public.countries(id),
    name       TEXT NOT NULL
);
INSERT INTO public.cities (id, country_id, name)
SELECT g, ((g - 1) % 200) + 1, 'City ' || g
FROM generate_series(1, 500) g;

-- 4. customers (500)
CREATE TABLE public.customers (
    id         INT PRIMARY KEY,
    country_id INT NOT NULL REFERENCES public.countries(id),
    email      TEXT NOT NULL,
    name       TEXT NOT NULL
);
INSERT INTO public.customers (id, country_id, email, name)
SELECT g, ((g - 1) % 200) + 1, 'customer' || g || '@example.com', 'Customer ' || g
FROM generate_series(1, 500) g;

-- 5. addresses (1000; two per customer)
CREATE TABLE public.addresses (
    id          INT PRIMARY KEY,
    customer_id INT NOT NULL REFERENCES public.customers(id),
    city_id     INT NOT NULL REFERENCES public.cities(id),
    street      TEXT NOT NULL
);
INSERT INTO public.addresses (id, customer_id, city_id, street)
SELECT g, ((g - 1) % 500) + 1, ((g - 1) % 500) + 1, 'Street ' || g
FROM generate_series(1, 1000) g;

-- 6. suppliers (100)
CREATE TABLE public.suppliers (
    id         INT PRIMARY KEY,
    country_id INT NOT NULL REFERENCES public.countries(id),
    name       TEXT NOT NULL
);
INSERT INTO public.suppliers (id, country_id, name)
SELECT g, ((g - 1) % 200) + 1, 'Supplier ' || g
FROM generate_series(1, 100) g;

-- 7. categories (50; first ten are top-level, rest chain to one of them)
CREATE TABLE public.categories (
    id        INT PRIMARY KEY,
    parent_id INT REFERENCES public.categories(id),
    name      TEXT NOT NULL
);
INSERT INTO public.categories (id, parent_id, name)
SELECT g,
       CASE WHEN g <= 10 THEN NULL ELSE ((g - 1) % 10) + 1 END,
       'Category ' || g
FROM generate_series(1, 50) g;

-- 8. products (1000)
CREATE TABLE public.products (
    id          INT PRIMARY KEY,
    category_id INT NOT NULL REFERENCES public.categories(id),
    supplier_id INT NOT NULL REFERENCES public.suppliers(id),
    sku         TEXT NOT NULL,
    price_cents INT NOT NULL
);
INSERT INTO public.products (id, category_id, supplier_id, sku, price_cents)
SELECT g,
       ((g - 1) % 50) + 1,
       ((g - 1) % 100) + 1,
       'SKU-' || lpad(g::text, 4, '0'),
       (random() * 10000)::int + 100
FROM generate_series(1, 1000) g;

-- 9. warehouses (10)
CREATE TABLE public.warehouses (
    id      INT PRIMARY KEY,
    city_id INT NOT NULL REFERENCES public.cities(id),
    name    TEXT NOT NULL
);
INSERT INTO public.warehouses (id, city_id, name)
SELECT g, ((g - 1) % 500) + 1, 'Warehouse ' || g
FROM generate_series(1, 10) g;

-- 10. inventory (5000 = 500 products each kept in all 10 warehouses)
CREATE TABLE public.inventory (
    product_id   INT NOT NULL REFERENCES public.products(id),
    warehouse_id INT NOT NULL REFERENCES public.warehouses(id),
    qty          INT NOT NULL,
    PRIMARY KEY (product_id, warehouse_id)
);
INSERT INTO public.inventory (product_id, warehouse_id, qty)
SELECT p, w, (random() * 100)::int
FROM generate_series(1, 500) p
CROSS JOIN generate_series(1, 10) w;

-- 11. orders (2000)
CREATE TABLE public.orders (
    id          INT PRIMARY KEY,
    customer_id INT NOT NULL REFERENCES public.customers(id),
    address_id  INT NOT NULL REFERENCES public.addresses(id),
    placed_at   TIMESTAMPTZ NOT NULL,
    status      TEXT NOT NULL
);
INSERT INTO public.orders (id, customer_id, address_id, placed_at, status)
SELECT g,
       ((g - 1) % 500) + 1,
       ((g - 1) % 1000) + 1,
       now() - (g * interval '1 hour'),
       CASE (g % 4)
           WHEN 0 THEN 'PENDING'
           WHEN 1 THEN 'SHIPPED'
           WHEN 2 THEN 'DELIVERED'
           ELSE        'CANCELLED'
       END
FROM generate_series(1, 2000) g;

-- 12. order_items (8000, about 4 per order)
CREATE TABLE public.order_items (
    id               INT PRIMARY KEY,
    order_id         INT NOT NULL REFERENCES public.orders(id),
    product_id       INT NOT NULL REFERENCES public.products(id),
    qty              INT NOT NULL,
    unit_price_cents INT NOT NULL
);
INSERT INTO public.order_items (id, order_id, product_id, qty, unit_price_cents)
SELECT g,
       ((g - 1) % 2000) + 1,
       ((g - 1) % 1000) + 1,
       (random() * 5)::int + 1,
       (random() * 10000)::int + 100
FROM generate_series(1, 8000) g;

-- 13. shipments (2000; one per order)
-- Orders placed fewer than 100 hours ago have shipped_at = NULL
-- ("not shipped yet"). Older orders shipped 100 hours after they were
-- placed, which keeps shipped_at strictly in the past and strictly after
-- the corresponding orders.placed_at.
CREATE TABLE public.shipments (
    id           INT PRIMARY KEY,
    order_id     INT NOT NULL REFERENCES public.orders(id),
    warehouse_id INT NOT NULL REFERENCES public.warehouses(id),
    shipped_at   TIMESTAMPTZ
);
INSERT INTO public.shipments (id, order_id, warehouse_id, shipped_at)
SELECT g,
       g,
       ((g - 1) % 10) + 1,
       CASE WHEN g >= 100
            THEN now() - ((g - 100) * interval '1 hour')
            ELSE NULL
       END
FROM generate_series(1, 2000) g;

ANALYZE public.regions, public.countries, public.cities, public.customers,
    public.addresses, public.suppliers, public.categories, public.products,
    public.warehouses, public.inventory, public.orders, public.order_items,
    public.shipments;
