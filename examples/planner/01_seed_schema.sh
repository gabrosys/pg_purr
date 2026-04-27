#!/usr/bin/env bash
# Create and seed the 13-table retail schema used by the planner demo.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLANNER_DIR="${REPO_ROOT}/examples/planner"

echo "==> Seeding the 13-table retail schema..."
docker cp "${PLANNER_DIR}/schema.sql" pg-purr-test:/tmp/schema.sql >/dev/null
docker exec pg-purr-test psql -U test -d pg_purr_test -v ON_ERROR_STOP=1 \
    -f /tmp/schema.sql >/dev/null

echo
echo "==> Row counts after seeding:"
docker exec pg-purr-test psql -U test -d pg_purr_test -c "
SELECT 'regions'      AS table_name, count(*) FROM public.regions
UNION ALL SELECT 'countries',   count(*) FROM public.countries
UNION ALL SELECT 'cities',      count(*) FROM public.cities
UNION ALL SELECT 'customers',   count(*) FROM public.customers
UNION ALL SELECT 'addresses',   count(*) FROM public.addresses
UNION ALL SELECT 'suppliers',   count(*) FROM public.suppliers
UNION ALL SELECT 'categories',  count(*) FROM public.categories
UNION ALL SELECT 'products',    count(*) FROM public.products
UNION ALL SELECT 'warehouses',  count(*) FROM public.warehouses
UNION ALL SELECT 'inventory',   count(*) FROM public.inventory
UNION ALL SELECT 'orders',      count(*) FROM public.orders
UNION ALL SELECT 'order_items', count(*) FROM public.order_items
UNION ALL SELECT 'shipments',   count(*) FROM public.shipments
ORDER BY table_name;
"

cat <<'EOF'

13 tables, ~20 000 rows total. A non-trivial JOIN graph: the next two
steps run the same 13-way INNER JOIN through PostgreSQL's own planner
and through pg_purr, so you can compare their chosen orderings.

Next: ./02_baseline_explain.sh
EOF
