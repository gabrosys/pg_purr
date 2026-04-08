"""Parse PostgreSQL EXPLAIN (FORMAT JSON) output into a JoinGraph."""

from dataclasses import dataclass, field


@dataclass
class JoinGraph:
    """Represents tables, row estimates, and pairwise join costs."""

    tables: list[str] = field(default_factory=list)
    row_counts: dict[str, float] = field(default_factory=dict)
    costs: dict[tuple[str, str], float] = field(default_factory=dict)


def parse_explain_json(explain_json: list[dict]) -> JoinGraph:
    """Convert EXPLAIN (FORMAT JSON) output into a JoinGraph.

    Walks the plan tree to find Seq Scan / Index Scan nodes, extracts
    table aliases and row estimates, then builds pairwise join costs
    using a simple nested-loop cost model (rows_a * rows_b).
    """
    tables = []
    row_counts = {}

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

    root_plan = explain_json[0]["Plan"]
    _walk(root_plan)

    # Build pairwise costs (simple nested-loop estimate)
    costs = {}
    for i, t1 in enumerate(tables):
        for j, t2 in enumerate(tables):
            if i != j:
                costs[(t1, t2)] = row_counts[t1] * row_counts[t2]

    return JoinGraph(tables=tables, row_counts=row_counts, costs=costs)
