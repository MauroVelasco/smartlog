"""
Orchestrates the full Correlation Agents stage: deterministic joins
first, then the LangChain semantic agent on whatever's left unlinked —
exactly the hybrid design described on architecture slide 5.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional, Tuple

from correlation.deterministic import deterministic_correlate
from models.schema import CorrelationEdge, LogEvent

if TYPE_CHECKING:
    from correlation.langchain_agents import SemanticObserver

logger = logging.getLogger(__name__)


def run_correlation(
    events: List[LogEvent], use_llm: bool = True, semantic_observer: Optional["SemanticObserver"] = None
) -> Tuple[List[CorrelationEdge], dict]:
    """Returns (all_edges, stats)."""
    deterministic_edges, linked_ids = deterministic_correlate(events)
    unlinked = [e for e in events if e.event_id not in linked_ids]

    semantic_edges: List[CorrelationEdge] = []
    if use_llm and unlinked:
        from correlation.langchain_agents import SemanticCorrelationAgent

        agent = SemanticCorrelationAgent(observer=semantic_observer)
        semantic_edges = agent.correlate(unlinked)

    all_edges = deterministic_edges + semantic_edges
    stats = {
        "total_events": len(events),
        "deterministic_edges": len(deterministic_edges),
        "unlinked_after_deterministic": len(unlinked),
        "semantic_edges": len(semantic_edges),
        "total_edges": len(all_edges),
    }
    logger.info("Correlation stats: %s", stats)
    return all_edges, stats
