"""
LangChain Correlation Agents (architecture slide 5, stage 3).

This is the LLM fallback in the hybrid design: it only ever looks at
events that deterministic.py could NOT link via a shared identifier.
Before any LLM call, candidates are bucketed into small time windows
(SEMANTIC_TIME_BUCKET_SECONDS) and capped at SEMANTIC_MAX_BATCH_SIZE —
the pre-filtering step called out as a derisking item in business case
slide 9 ("Needs sampling and pre-filtering before any LLM call").

The agent reasons the way an SRE would (business case slide 4): given a
handful of unlinked log lines from different systems in the same rough
time window, which ones plausibly describe the same incident, and why?
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import List

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

import config
from models.schema import CorrelationEdge, LogEvent, RelationType

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an experienced Site Reliability Engineer triaging a live \
incident. You are given a batch of log lines pulled from different systems \
(CloudWatch, Tomcat, GCP Logging, Oracle/MySQL/Postgres) that occurred close \
together in time but share no common request ID, trace ID, user ID, error \
code, or service name.

Your job: decide which of these log lines plausibly describe the SAME \
underlying incident or causal chain (e.g. a DB connection pool exhaustion \
that shows up as a Tomcat 500, then a downstream timeout in another \
service), based on error propagation patterns, message content, and \
timing proximity — the same judgment call an SRE makes when eyeballing \
logs across a dozen browser tabs.

Only propose a link when there is real textual or causal evidence — do \
not link events just because they happened at a similar time. Be \
conservative: false links are worse than missed ones. For every link you \
propose, give a confidence score between 0 and 1 and a short rationale."""

USER_PROMPT = """Log events (event_id | source_system | timestamp | level | message):
{event_lines}

Return every plausible correlation as a pair of event_ids with a \
confidence score and rationale. If nothing plausibly correlates, return \
an empty list."""


class ProposedLink(BaseModel):
    source_event_id: str = Field(description="event_id of the first event in the pair")
    target_event_id: str = Field(description="event_id of the second event in the pair")
    confidence: float = Field(description="0.0-1.0 confidence this is a real correlation")
    rationale: str = Field(description="short explanation of the causal/textual evidence")


class CorrelationResult(BaseModel):
    links: List[ProposedLink] = Field(default_factory=list)


def _build_llm():
    if config.LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=config.LLM_MODEL, temperature=config.LLM_TEMPERATURE)
    elif config.LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=config.LLM_MODEL, temperature=config.LLM_TEMPERATURE)
    raise ValueError(f"Unsupported LLM_PROVIDER: {config.LLM_PROVIDER}")


def _format_events(events: List[LogEvent]) -> str:
    lines = []
    for e in events:
        msg = e.message.strip().replace("\n", " ")[:300]
        lines.append(f"{e.event_id} | {e.source_system} | {e.timestamp.isoformat()} | {e.level or '-'} | {msg}")
    return "\n".join(lines)


def _bucket_by_time(events: List[LogEvent], bucket_seconds: int) -> List[List[LogEvent]]:
    """Sliding, non-overlapping time buckets so the LLM only ever compares
    events that are already temporally close — this bounds both cost and
    the chance of spurious long-distance links."""
    if not events:
        return []
    events = sorted(events, key=lambda e: e.timestamp)
    buckets: List[List[LogEvent]] = []
    current: List[LogEvent] = [events[0]]
    bucket_start = events[0].timestamp
    for event in events[1:]:
        if (event.timestamp - bucket_start) <= timedelta(seconds=bucket_seconds):
            current.append(event)
        else:
            buckets.append(current)
            current = [event]
            bucket_start = event.timestamp
    buckets.append(current)
    return buckets


class SemanticCorrelationAgent:
    """LangChain-backed agent that fills in correlations deterministic
    joins missed. Only instantiated (and only calls out to an LLM) when
    there are unlinked events left after the deterministic pass."""

    def __init__(self):
        self._llm = _build_llm()
        prompt = ChatPromptTemplate.from_messages(
            [("system", SYSTEM_PROMPT), ("human", USER_PROMPT)]
        )
        self._chain = prompt | self._llm.with_structured_output(CorrelationResult)

    def correlate(self, unlinked_events: List[LogEvent]) -> List[CorrelationEdge]:
        if len(unlinked_events) < 2:
            return []

        edges: List[CorrelationEdge] = []
        buckets = _bucket_by_time(unlinked_events, config.SEMANTIC_TIME_BUCKET_SECONDS)
        logger.info(
            "Semantic correlation: %d unlinked events across %d time buckets", len(unlinked_events), len(buckets)
        )

        for bucket in buckets:
            if len(bucket) < 2:
                continue
            # Only worth an LLM call if the bucket spans more than one
            # source system — same-system-only clusters are usually just
            # chatty logging, not a cross-system incident.
            if len({e.source_system for e in bucket}) < 2:
                continue
            for chunk_start in range(0, len(bucket), config.SEMANTIC_MAX_BATCH_SIZE):
                chunk = bucket[chunk_start : chunk_start + config.SEMANTIC_MAX_BATCH_SIZE]
                edges.extend(self._correlate_chunk(chunk))
        return edges

    def _correlate_chunk(self, chunk: List[LogEvent]) -> List[CorrelationEdge]:
        valid_ids = {e.event_id for e in chunk}
        try:
            result: CorrelationResult = self._chain.invoke({"event_lines": _format_events(chunk)})
        except Exception as exc:
            logger.warning("LLM correlation call failed for a chunk of %d events: %s", len(chunk), exc)
            return []

        edges: List[CorrelationEdge] = []
        for link in result.links:
            if link.source_event_id not in valid_ids or link.target_event_id not in valid_ids:
                continue  # ignore hallucinated event_ids
            if link.source_event_id == link.target_event_id:
                continue
            if link.confidence < config.SEMANTIC_MIN_CONFIDENCE:
                continue
            edges.append(
                CorrelationEdge(
                    source_event_id=link.source_event_id,
                    target_event_id=link.target_event_id,
                    relation_type=RelationType.SEMANTIC_SIMILARITY,
                    confidence=link.confidence,
                    matched_on=link.rationale,
                )
            )
        return edges
