"""
harness/scoring.py

Anchor resolution + precision/recall/contamination/incident-grouping
scoring (postgres-scenario-harness harness architecture).

All ground-truth comparison happens over the ANCHOR SET only — the set of
events successfully resolved from scenario steps via `emits` matching.
Singleton-incident noise never enters precision/recall: only anchor-anchor
pairs are ground-truthed. Anchor<->noise edges are reported as
`contamination` (ground truth doesn't cover noise); noise<->noise edges are
ignored entirely.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import networkx as nx

from harness.models import Expected, Step
from models.schema import CorrelationEdge, LogEvent


def resolve_anchors(events: List[LogEvent], steps: List[Step]) -> Tuple[Dict[str, LogEvent], List[str]]:
    """Resolve each step's `emits` selector against collected events.
    Requires EXACTLY ONE match; 0 or 2+ is UNRESOLVED, never a silent pass
    (design: "Step -> event resolution"). CloudWatch manual steps
    (emits=None) are skipped — they're never triggered or scored."""
    anchors: Dict[str, LogEvent] = {}
    unresolved: List[str] = []
    for step in steps:
        emits = getattr(step, "emits", None)
        if emits is None:
            continue
        matches = [e for e in events if e.source_system == emits.source_system and emits.message_contains in e.message]
        if len(matches) == 1:
            anchors[step.id] = matches[0]
        else:
            unresolved.append(step.id)
    return anchors, unresolved


@dataclass
class IncidentResult:
    members: List[str]  # step ids
    expected_grouped: bool
    actual_grouped: bool
    component_size: Optional[int]


@dataclass
class ScoreResult:
    precision: float
    precision_undefined: bool
    recall: float
    recall_undefined: bool
    true_positives: List[Tuple[str, str]] = field(default_factory=list)
    false_positives: List[Tuple[str, str]] = field(default_factory=list)
    false_negatives: List[Tuple[str, str]] = field(default_factory=list)
    stage_mismatches: List[Tuple[str, str]] = field(default_factory=list)
    contamination: List[Tuple[str, str]] = field(default_factory=list)
    incidents: List[IncidentResult] = field(default_factory=list)
    forbidden_edges_observed: List[Tuple[str, str]] = field(default_factory=list)


def _pair_key(a: str, b: str) -> Tuple[str, str]:
    return tuple(sorted((a, b)))  # type: ignore[return-value]


def score(
    events: List[LogEvent],
    edges: List[CorrelationEdge],
    anchors: Dict[str, LogEvent],
    expected: Expected,
) -> ScoreResult:
    event_id_to_step_id = {event.event_id: step_id for step_id, event in anchors.items()}
    anchor_event_ids = set(event_id_to_step_id)

    # Expected pairs (P), keyed by sorted step-id pair -> expected relation_type.
    expected_relation_by_pair: Dict[Tuple[str, str], str] = {
        _pair_key(e.from_step, e.to_step): e.relation_type for e in expected.edges
    }
    expected_pairs = set(expected_relation_by_pair)

    # Observed pairs (O): edges with BOTH endpoints anchors -> step-id pairs.
    # Edges with exactly one anchor endpoint are contamination, not scored.
    observed_relation_by_pair: Dict[Tuple[str, str], str] = {}
    contamination: List[Tuple[str, str]] = []
    for edge in edges:
        src_in = edge.source_event_id in anchor_event_ids
        tgt_in = edge.target_event_id in anchor_event_ids
        if src_in and tgt_in:
            step_pair = _pair_key(event_id_to_step_id[edge.source_event_id], event_id_to_step_id[edge.target_event_id])
            observed_relation_by_pair[step_pair] = edge.relation_type
        elif src_in or tgt_in:
            anchor_id = edge.source_event_id if src_in else edge.target_event_id
            other_id = edge.target_event_id if src_in else edge.source_event_id
            contamination.append((anchor_id, other_id))
        # else: noise<->noise, ignored entirely

    observed_pairs = set(observed_relation_by_pair)

    true_positive_pairs = expected_pairs & observed_pairs
    false_positive_pairs = observed_pairs - expected_pairs
    false_negative_pairs = expected_pairs - observed_pairs

    forbidden_pairs = {_pair_key(e.from_step, e.to_step) for e in expected.forbidden_edges}
    forbidden_edges_observed = sorted(forbidden_pairs & observed_pairs)

    stage_mismatches = [
        pair
        for pair in sorted(true_positive_pairs)
        if observed_relation_by_pair[pair] != expected_relation_by_pair[pair]
    ]

    tp, fp, fn = len(true_positive_pairs), len(false_positive_pairs), len(false_negative_pairs)
    precision_undefined = (tp + fp) == 0
    recall_undefined = (tp + fn) == 0
    precision = 1.0 if precision_undefined else tp / (tp + fp)
    recall = 1.0 if recall_undefined else tp / (tp + fn)

    incidents = _score_incidents(events, edges, anchors, expected)

    return ScoreResult(
        precision=precision,
        precision_undefined=precision_undefined,
        recall=recall,
        recall_undefined=recall_undefined,
        true_positives=sorted(true_positive_pairs),
        false_positives=sorted(false_positive_pairs),
        false_negatives=sorted(false_negative_pairs),
        stage_mismatches=stage_mismatches,
        contamination=contamination,
        incidents=incidents,
        forbidden_edges_observed=forbidden_edges_observed,
    )


def _score_incidents(
    events: List[LogEvent], edges: List[CorrelationEdge], anchors: Dict[str, LogEvent], expected: Expected
) -> List[IncidentResult]:
    graph = nx.Graph()
    for event in events:
        graph.add_node(event.event_id)
    for edge in edges:
        graph.add_edge(edge.source_event_id, edge.target_event_id)

    component_by_event_id: Dict[str, frozenset] = {}
    for component in nx.connected_components(graph):
        frozen = frozenset(component)
        for event_id in component:
            component_by_event_id[event_id] = frozen

    results: List[IncidentResult] = []
    for incident in expected.incidents:
        member_event_ids = [anchors[m].event_id for m in incident.members if m in anchors]
        if len(member_event_ids) != len(incident.members):
            # A member never resolved to an anchor — can't evaluate grouping.
            results.append(
                IncidentResult(
                    members=incident.members, expected_grouped=incident.grouped, actual_grouped=False, component_size=None
                )
            )
            continue
        components = {component_by_event_id.get(eid, frozenset({eid})) for eid in member_event_ids}
        all_in_one_component = len(components) == 1
        component_size = len(next(iter(components))) if all_in_one_component else None

        if len(incident.members) == 1:
            # A single-member incident isn't asking "do these members share
            # a component with EACH OTHER" (trivially true for any set of
            # size 1) — it's asking "is this event actually isolated, or
            # did it end up linked to something else". grouped=False means
            # "must stay isolated"; actual_grouped reflects whether the
            # event's real component has more than just itself.
            actual_grouped = (component_size or 1) > 1
        else:
            actual_grouped = all_in_one_component

        results.append(
            IncidentResult(
                members=incident.members,
                expected_grouped=incident.grouped,
                actual_grouped=actual_grouped,
                component_size=component_size,
            )
        )
    return results
