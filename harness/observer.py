"""
harness/observer.py

`RecordingObserver(SemanticObserver)` accumulates what the semantic stage
saw during one harness case run (postgres-scenario-harness design
Decision 1 — the production observer seam added in Phase 4). `errors`
non-empty => the case's status is `ERRORED`, never scored as a legitimate
empty result (spec: "LLM call failure is distinguishable from genuine
empty result").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

import config
from correlation.langchain_agents import CorrelationResult, SemanticObserver
from models.schema import LogEvent


@dataclass
class SubThresholdLink:
    """A link the LLM proposed but that fell below SEMANTIC_MIN_CONFIDENCE
    — captured here because run_correlation() silently drops it before
    returning, per the confidence-observability requirement (spec)."""

    source_event_id: str
    target_event_id: str
    confidence: float
    rationale: str


class RecordingObserver(SemanticObserver):
    def __init__(self):
        self.skips: List[Tuple[List[LogEvent], str]] = []
        self.raw_results: List[Tuple[List[LogEvent], CorrelationResult]] = []
        self.errors: List[Tuple[List[LogEvent], Exception]] = []
        self.sub_threshold_links: List[SubThresholdLink] = []

    def on_skip(self, bucket: List[LogEvent], reason: str) -> None:
        self.skips.append((list(bucket), reason))

    def on_raw_result(self, chunk: List[LogEvent], result: CorrelationResult) -> None:
        self.raw_results.append((list(chunk), result))
        for link in result.links:
            if link.confidence < config.SEMANTIC_MIN_CONFIDENCE:
                self.sub_threshold_links.append(
                    SubThresholdLink(
                        source_event_id=link.source_event_id,
                        target_event_id=link.target_event_id,
                        confidence=link.confidence,
                        rationale=link.rationale,
                    )
                )

    def on_error(self, chunk: List[LogEvent], exc: Exception) -> None:
        self.errors.append((list(chunk), exc))
