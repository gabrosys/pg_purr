"""Parse PostgreSQL EXPLAIN (FORMAT JSON) output into a JoinGraph."""

from dataclasses import dataclass, field


@dataclass
class JoinGraph:
    """Tables, row estimates, and the predicate-edge set.

    `tables` and `row_counts` come from the EXPLAIN walker; `edges`
    is populated by callers after parsing the original SQL via
    `predicate_graph.extract_join_edges`. The cost model reads row
    counts from this dataclass; edge weights come from `cost_model`.
    """

    tables: list[str] = field(default_factory=list)
    row_counts: dict[str, float] = field(default_factory=dict)
    edges: set[frozenset[str]] = field(default_factory=set)


def parse_explain_json(explain_json: list[dict]) -> JoinGraph:
    """Convert EXPLAIN (FORMAT JSON) output into a JoinGraph.

    Walks the plan tree to find Seq Scan / Index Scan nodes and
    extracts table aliases plus row estimates. Returns an empty
    graph for plans that do not start with a `Plan` block.
    """
    tables: list[str] = []
    row_counts: dict[str, float] = {}

    def _walk(node: dict) -> None:
        relation = node.get("Relation Name")
        if relation:
            alias = node.get("Alias", relation)
            if alias not in row_counts:
                tables.append(alias)
                row_counts[alias] = node.get("Plan Rows", 0)
        for child in node.get("Plans", []):
            _walk(child)

    if not explain_json or "Plan" not in explain_json[0]:
        return JoinGraph()

    _walk(explain_json[0]["Plan"])
    return JoinGraph(tables=tables, row_counts=row_counts)
