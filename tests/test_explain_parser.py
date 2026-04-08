"""Unit tests for the EXPLAIN JSON parser."""

from pg_purr.planner.explain_parser import JoinGraph, parse_explain_json

SAMPLE_EXPLAIN = [
    {
        "Plan": {
            "Node Type": "Hash Join",
            "Plan Rows": 1000,
            "Total Cost": 500.0,
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "orders",
                    "Alias": "o",
                    "Plan Rows": 10000,
                    "Total Cost": 200.0,
                },
                {
                    "Node Type": "Hash",
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "customers",
                            "Alias": "c",
                            "Plan Rows": 5000,
                            "Total Cost": 100.0,
                        }
                    ],
                },
            ],
        }
    }
]


def test_parse_extracts_tables():
    graph = parse_explain_json(SAMPLE_EXPLAIN)
    assert isinstance(graph, JoinGraph)
    assert set(graph.tables) == {"c", "o"}


def test_parse_extracts_row_counts():
    graph = parse_explain_json(SAMPLE_EXPLAIN)
    assert graph.row_counts["o"] == 10000
    assert graph.row_counts["c"] == 5000


def test_parse_generates_costs():
    graph = parse_explain_json(SAMPLE_EXPLAIN)
    assert ("c", "o") in graph.costs
    assert ("o", "c") in graph.costs
    assert graph.costs[("c", "o")] > 0
