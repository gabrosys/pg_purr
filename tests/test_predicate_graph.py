"""Unit tests for the join-predicate graph extractor."""

from pg_purr.planner.predicate_graph import extract_join_edges, is_connected_order


def _e(*pairs: tuple[str, str]) -> set[frozenset[str]]:
    return {frozenset(p) for p in pairs}


def test_simple_two_table_join():
    edges = extract_join_edges("SELECT * FROM a JOIN b ON a.id = b.aid")
    assert edges == _e(("a", "b"))


def test_three_table_chain():
    edges = extract_join_edges("SELECT * FROM a JOIN b ON a.id = b.aid JOIN c ON b.id = c.bid")
    assert edges == _e(("a", "b"), ("b", "c"))


def test_multi_condition_on():
    # ON clause that ANDs two equalities across 3 tables.
    edges = extract_join_edges(
        "SELECT * FROM sh "
        "JOIN o ON o.id = sh.order_id "
        "JOIN si ON si.shipment_id = sh.id AND si.order_item_id = o.id"
    )
    assert edges == _e(("o", "sh"), ("sh", "si"), ("o", "si"))


def test_where_predicates_count():
    edges = extract_join_edges("SELECT * FROM a, b, c WHERE a.id = b.aid AND b.id = c.bid")
    assert edges == _e(("a", "b"), ("b", "c"))


def test_constant_filter_does_not_create_edge():
    edges = extract_join_edges("SELECT * FROM a JOIN b ON a.id = b.aid WHERE a.flag = true")
    assert edges == _e(("a", "b"))


def test_unparseable_returns_empty():
    assert extract_join_edges("not a sql query at all !!!") == set()


def test_non_select_returns_empty():
    assert extract_join_edges("UPDATE a SET x = 1") == set()


def test_three_way_predicate():
    # A predicate referencing columns from 3 tables contributes all
    # 3 pairwise edges. Rare but legal SQL.
    edges = extract_join_edges("SELECT * FROM a, b, c WHERE a.x + b.y = c.z")
    assert edges == _e(("a", "b"), ("a", "c"), ("b", "c"))


def test_retail_shape_full_graph():
    # 17-table retail-schema join shape. Verifies every documented
    # edge is recovered. Order-insensitive set comparison.
    query = """
    SELECT s.name FROM public.suppliers s
    JOIN public.products         p     ON p.supplier_id  = s.id
    JOIN public.categories       c     ON c.id           = p.category_id
    JOIN public.categories       pc    ON pc.id          = c.parent_id
    JOIN public.inventory        inv   ON inv.product_id = p.id
    JOIN public.warehouses       w     ON w.id           = inv.warehouse_id
    JOIN public.order_items      oi    ON oi.product_id  = p.id
    JOIN public.orders           o     ON o.id           = oi.order_id
    JOIN public.customers        cu    ON cu.id          = o.customer_id
    JOIN public.addresses        a     ON a.id           = o.address_id
    JOIN public.payments         pay   ON pay.order_id   = o.id
    JOIN public.payment_methods  pm    ON pm.id          = pay.payment_method_id
    JOIN public.shipments        sh    ON sh.order_id    = o.id
    JOIN public.shipment_items   si    ON si.shipment_id = sh.id
                                       AND si.order_item_id = oi.id
    JOIN public.reviews          r     ON r.product_id   = p.id
                                       AND r.customer_id = cu.id
    JOIN public.promotion_rules  pr    ON pr.category_id = c.id
    JOIN public.promotions       promo ON promo.id       = pr.promotion_id
    WHERE o.order_date BETWEEN promo.start_date AND promo.end_date
      AND o.total >= pr.min_order_total
    """
    edges = extract_join_edges(query)
    expected = _e(
        ("p", "s"),
        ("c", "p"),
        ("c", "pc"),
        ("inv", "p"),
        ("inv", "w"),
        ("oi", "p"),
        ("o", "oi"),
        ("cu", "o"),
        ("a", "o"),
        ("o", "pay"),
        ("pay", "pm"),
        ("o", "sh"),
        ("sh", "si"),
        ("oi", "si"),
        ("p", "r"),
        ("cu", "r"),
        ("c", "pr"),
        ("pr", "promo"),
        ("o", "promo"),
        ("o", "pr"),
    )
    assert edges == expected


# ---------- is_connected_order --------------------------------------


def test_connected_order_path_graph():
    edges = _e(("a", "b"), ("b", "c"), ("c", "d"))
    assert is_connected_order(["a", "b", "c", "d"], edges) is True
    assert is_connected_order(["d", "c", "b", "a"], edges) is True


def test_disconnected_order_breaks_at_first_isolated_step():
    # b connects to a, but c does NOT connect to {a, b}.
    edges = _e(("a", "b"), ("c", "d"))
    assert is_connected_order(["a", "b", "c", "d"], edges) is False


def test_singleton_and_empty_orders_are_trivially_connected():
    assert is_connected_order([], set()) is True
    assert is_connected_order(["only"], set()) is True


def test_star_schema_any_order_starting_at_centre_connected():
    # Star: f connects to d1, d2, d3.
    edges = _e(("f", "d1"), ("f", "d2"), ("f", "d3"))
    assert is_connected_order(["f", "d1", "d2", "d3"], edges) is True
    # But starting at a leaf and visiting another leaf next is broken.
    assert is_connected_order(["d1", "d2", "f", "d3"], edges) is False
