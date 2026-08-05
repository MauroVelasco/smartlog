import networkx as nx

from visualization.graph_builder import build_graph_json


def _sample_graph():
    g = nx.Graph()
    g.add_node(
        "e1",
        source_system="cloudwatch",
        origin="/ecs/app",
        timestamp="2026-08-03T12:00:00+00:00",
        level="ERROR",
        message="NullPointerException",
        identifiers={"request_id": "req-1"},
        host="host-a",
    )
    g.add_node(
        "e2",
        source_system="tomcat",
        origin="catalina.out",
        timestamp="2026-08-03T12:00:05+00:00",
        level="INFO",
        message="request handled",
        identifiers={"request_id": "req-1"},
        host="host-b",
    )
    g.add_edge("e1", "e2", relation_type="id_match", confidence=1.0, matched_on="request_id")
    return g


def test_build_graph_json_full():
    result = build_graph_json(_sample_graph())
    assert len(result["nodes"]) == 2
    assert len(result["edges"]) == 1
    node = next(n for n in result["nodes"] if n["id"] == "e1")
    assert node["group"] == "cloudwatch"
    assert node["borderWidth"] == 3  # ERROR level gets a highlighted border
    edge = result["edges"][0]
    assert edge["dashes"] is False  # id_match is deterministic, drawn solid


def test_build_graph_json_filters_by_incident():
    result = build_graph_json(_sample_graph(), event_ids={"e1"})
    assert len(result["nodes"]) == 1
    assert len(result["edges"]) == 0
