"""
Shapes the Relationship Store's networkx graph into the node/edge JSON
the vis-network frontend (templates/index.html) consumes — the last
step before "Visualization UI" (architecture slide 5, stage 5).

Design choices, tied back to the business case:
  - Nodes are colored by source_system so a human can instantly see
    which systems an incident crossed, and sized/bordered by level so
    ERROR/FATAL events pop out of a busy incident (slide 4's "one
    incident, every system it touched").
  - Edges are styled by relation_type: solid for deterministic id_match
    (high trust), dashed for LLM-inferred semantic_similarity (slide 9:
    "false links are worse than missed ones" — dashing keeps inferred
    links visually distinct from certain ones) — and edge width scales
    with confidence.
  - The graph is NOT forced into a tree: slide 9 flags real log
    relationships as many-to-many, so this renders the true graph/DAG
    and lets the layout algorithm (or the user) reveal structure,
    rather than pre-collapsing it into a hierarchy.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set

import networkx as nx

_SOURCE_COLORS = {
    "cloudwatch": "#FF9900",   # AWS orange
    "tomcat": "#F8DC75",       # tomcat yellow/cream
    "gcp_logging": "#4285F4",  # GCP blue
    "oracle": "#F80000",       # Oracle red
    "mysql": "#00758F",        # MySQL teal
    "postgres": "#336791",     # Postgres blue-grey
}

_LEVEL_BORDER = {
    "FATAL": "#B00020",
    "ERROR": "#D32F2F",
    "WARN": "#F9A825",
    "WARNING": "#F9A825",
    "INFO": "#616161",
    "DEBUG": "#9E9E9E",
    "TRACE": "#BDBDBD",
}

_LEVEL_SIZE = {
    "FATAL": 34,
    "ERROR": 28,
    "WARN": 22,
    "WARNING": 22,
    "INFO": 16,
    "DEBUG": 14,
    "TRACE": 12,
}


def _node_to_vis(event_id: str, data: Dict) -> Dict:
    level = (data.get("level") or "INFO").upper()
    message = (data.get("message") or "")[:160]
    identifiers = data.get("identifiers") or {}
    id_summary = ", ".join(f"{k}={v}" for k, v in identifiers.items()) or "none"
    return {
        "id": event_id,
        "label": f"{data.get('source_system', '?')}\n{message[:40]}",
        "title": (
            f"<b>{data.get('source_system')}</b> ({data.get('origin')})<br>"
            f"{data.get('timestamp')}<br>"
            f"<b>level:</b> {level}<br>"
            f"<b>identifiers:</b> {id_summary}<br>"
            f"<b>message:</b> {message}"
        ),
        "group": data.get("source_system", "unknown"),
        "color": {
            "background": _SOURCE_COLORS.get(data.get("source_system"), "#9E9E9E"),
            "border": _LEVEL_BORDER.get(level, "#616161"),
        },
        "borderWidth": 3 if level in ("ERROR", "FATAL") else 1,
        "size": _LEVEL_SIZE.get(level, 16),
        "raw": {
            "source_system": data.get("source_system"),
            "origin": data.get("origin"),
            "timestamp": data.get("timestamp"),
            "level": level,
            "message": data.get("message"),
            "identifiers": identifiers,
            "host": data.get("host"),
        },
    }


def _edge_to_vis(u: str, v: str, data: Dict) -> Dict:
    relation_type = data.get("relation_type", "time_window")
    confidence = float(data.get("confidence", 1.0))
    is_inferred = relation_type == "semantic_similarity"
    return {
        "from": u,
        "to": v,
        "dashes": is_inferred,
        "width": max(1, round(confidence * 4)),
        "color": {"color": "#B0BEC5" if is_inferred else "#37474F", "opacity": max(0.3, confidence)},
        "title": f"{relation_type} (confidence {confidence:.2f})<br>{data.get('matched_on', '')}",
        "label": relation_type.replace("_", " "),
    }


def build_graph_json(graph: nx.Graph, event_ids: Optional[Set[str]] = None) -> Dict[str, List[Dict]]:
    """Convert a networkx graph (optionally restricted to a subset of
    event_ids, i.e. one incident) into vis-network's nodes/edges format."""
    nodes = []
    for node_id, data in graph.nodes(data=True):
        if event_ids is not None and node_id not in event_ids:
            continue
        nodes.append(_node_to_vis(node_id, data))

    edges = []
    for u, v, data in graph.edges(data=True):
        if event_ids is not None and (u not in event_ids or v not in event_ids):
            continue
        edges.append(_edge_to_vis(u, v, data))

    return {"nodes": nodes, "edges": edges}
