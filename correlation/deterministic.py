"""
Deterministic half of the hybrid correlation design (architecture slide 5
footnote: "deterministic joins (IDs, timestamps) run first; LLM
correlation only handles ambiguous, unlinked events").

Groups events that share an identifier value (request_id, trace_id,
user_id, error_code, service_name) and fall within
DETERMINISTIC_TIME_WINDOW_SECONDS of each other, and links them with
confidence 1.0. This alone resolves the majority of real incidents,
since most correlation clues are exact matches — the LLM only has to
look at what's left over.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Dict, List, Set, Tuple

import config
from models.schema import CorrelationEdge, LogEvent, RelationType


def deterministic_correlate(events: List[LogEvent]) -> Tuple[List[CorrelationEdge], Set[str]]:
    """Returns (edges, linked_event_ids)."""
    window = config.DETERMINISTIC_TIME_WINDOW_SECONDS
    edges: List[CorrelationEdge] = []
    linked_ids: Set[str] = set()
    seen_pairs: Set[Tuple[str, str]] = set()

    # index: (identifier_key, identifier_value) -> [events]
    groups: Dict[Tuple[str, str], List[LogEvent]] = defaultdict(list)
    for event in events:
        for key, value in event.identifiers.items():
            groups[(key, value)].append(event)

    for (id_key, _id_value), group_events in groups.items():
        if len(group_events) < 2:
            continue
        group_events = sorted(group_events, key=lambda e: e.timestamp)
        for a, b in combinations(group_events, 2):
            delta = abs((b.timestamp - a.timestamp).total_seconds())
            if delta > window:
                continue
            pair_key = tuple(sorted((a.event_id, b.event_id)))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            edges.append(
                CorrelationEdge(
                    source_event_id=a.event_id,
                    target_event_id=b.event_id,
                    relation_type=RelationType.ID_MATCH,
                    confidence=1.0,
                    matched_on=id_key,
                )
            )
            linked_ids.add(a.event_id)
            linked_ids.add(b.event_id)

    return edges, linked_ids
