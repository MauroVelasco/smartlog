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
import os
from datetime import timedelta
from typing import List, Optional

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
conservative: false links are worse than missed ones.

You are writing for an on-call engineer who is already looking at both log \
lines on screen, mid-incident. Obey these rules for every link:

- Do NOT quote, paraphrase, or restate the log messages. They can see them.
- Do NOT argue for your own confidence score. It is displayed separately.
- Name the causal direction explicitly: which event is the upstream cause \
and which is the downstream symptom. If the two are joint symptoms of an \
unobserved third cause, say so and pick the one closer to the root.
- `summary` is ONE sentence, at most 30 words, in plain language: what is \
actually happening across these systems. Lead with the mechanism, not with \
your reasoning process.
- `next_step` is ONE concrete action the engineer can take right now to \
confirm or fix it — a specific thing to check, query, or change. Not \
"investigate further", not "monitor the situation"."""

USER_PROMPT = """Log events (event_id | source_system | timestamp | level | message):
{event_lines}

Return every plausible correlation as a pair of event_ids. If nothing \
plausibly correlates, return an empty list."""


class ProposedLink(BaseModel):
    source_event_id: str = Field(description="event_id of the first event in the pair")
    target_event_id: str = Field(description="event_id of the second event in the pair")
    confidence: float = Field(description="0.0-1.0 confidence this is a real correlation")
    root_cause_event_id: str = Field(
        description="Whichever of the two event_ids is the upstream cause; the other is the downstream symptom"
    )
    summary: str = Field(
        description="ONE sentence, max 30 words, plain language: the mechanism linking these systems. "
        "Never quote or restate the log messages"
    )
    next_step: str = Field(
        description="ONE concrete action to confirm or fix it right now — a specific thing to check, "
        "query, or change. Never 'investigate further'"
    )


class CorrelationResult(BaseModel):
    links: List[ProposedLink] = Field(default_factory=list)


class SemanticObserver:
    """No-op observation hook for the semantic correlation stage.

    Production callers never pass one (default None), so this class exists
    purely as a seam for the scenario harness — subclass it to record what
    the LLM stage saw, without changing what run_correlation() returns.
    """

    def on_skip(self, bucket: List[LogEvent], reason: str) -> None:
        """A bucket was never sent to the LLM. reason is one of
        'bucket_size_lt_2' or 'single_source_system'."""

    def on_raw_result(self, chunk: List[LogEvent], result: CorrelationResult) -> None:
        """The LLM call succeeded; result is the RAW CorrelationResult,
        before the SEMANTIC_MIN_CONFIDENCE filter is applied."""

    def on_error(self, chunk: List[LogEvent], exc: Exception) -> None:
        """The LLM call itself raised — distinct from a legitimate empty
        result."""


def _build_llm():
    if config.LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=config.LLM_MODEL, temperature=config.LLM_TEMPERATURE)
    elif config.LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=config.LLM_MODEL, temperature=config.LLM_TEMPERATURE)
    elif config.LLM_PROVIDER == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        # config.LLM_MODEL's own default ("claude-sonnet-5") is Anthropic-
        # specific and shared across all providers, so only fall back to it
        # when LLM_MODEL was actually set by the caller/env; otherwise use a
        # Gemini-appropriate default. "gemini-flash-latest" (Google's stable
        # rolling alias for the current recommended flash model) is used
        # instead of a dated id like "gemini-2.5-flash" because dated ids
        # get sunset for new API keys (confirmed live: gemini-2.5-flash and
        # gemini-2.5-flash-lite both 404 "no longer available to new users"
        # against this project's key as of 2026-08-16).
        model = config.LLM_MODEL if os.getenv("LLM_MODEL") else "gemini-flash-latest"
        # ChatGoogleGenerativeAI's google_api_key field already resolves from
        # GOOGLE_API_KEY, falling back to GEMINI_API_KEY, via its own
        # default_factory — no need to read the env var here ourselves.
        return ChatGoogleGenerativeAI(model=model, temperature=config.LLM_TEMPERATURE)
    elif config.LLM_PROVIDER == "openrouter":
        from langchain_openai import ChatOpenAI

        # OpenRouter exposes an OpenAI-compatible Chat Completions API, so —
        # same pattern as the GitHub Models decision in
        # architecture/mvp-scope-and-llm-provider — it reuses ChatOpenAI
        # pointed at a different base_url instead of a new SDK/package.
        #
        # config.LLM_MODEL's own default ("claude-sonnet-5") is Anthropic-
        # specific and shared across all providers, so only fall back to it
        # when LLM_MODEL was actually set by the caller/env; otherwise use an
        # OpenRouter-appropriate default. "openai/gpt-4o-mini" is used
        # because OpenRouter's model listing (checked live via
        # GET /api/v1/models as of 2026-08-19) reports "tools", "tool_choice",
        # and "structured_outputs" in its supported_parameters — this
        # pipeline calls .with_structured_output(CorrelationResult), which
        # needs reliable function/tool calling, and free/open OpenRouter
        # models were already rejected for this exact reason in
        # architecture/mvp-scope-and-llm-provider ("irregular tool-calling on
        # free open models"). OpenRouter's own slash-namespaced id
        # ("openai/gpt-4o-mini") differs from the plain "gpt-4o-mini" used by
        # the "openai" branch above — the namespace prefix is required by
        # OpenRouter's routing.
        model = config.LLM_MODEL if os.getenv("LLM_MODEL") else "openai/gpt-4o-mini"
        # ChatOpenAI's own validate_environment() falls back to OPENAI_API_KEY
        # whenever the resolved api_key is None (langchain_core.utils._gateway.
        # _resolve_gateway_config only special-cases "api_key is not None" —
        # it does not distinguish "never passed" from "explicitly passed as
        # None"), so silently omitting api_key here would authenticate
        # against OpenRouter with an OPENAI_API_KEY-shaped credential from a
        # completely different provider if one happens to be set. Passing
        # os.getenv("OPENROUTER_API_KEY", "") keeps the value a non-None
        # string even when unset, so that fallback lookup never runs; the
        # openai SDK client then raises "Missing credentials" immediately at
        # construction instead, which is the correct fail-loud behavior.
        #
        # OpenRouter reads "provider" from the top level of the request body,
        # which is not an OpenAI Chat Completions field, so it travels via
        # extra_body rather than a ChatOpenAI constructor argument. Without it
        # OpenRouter picks a backend per request and structured output becomes
        # a coin flip — see config.OPENROUTER_PROVIDER_ORDER for the measured
        # per-provider tool-call results behind this pin.
        provider_routing = {
            "order": config.OPENROUTER_PROVIDER_ORDER,
            "allow_fallbacks": config.OPENROUTER_ALLOW_FALLBACKS,
            # Belt-and-braces for the fallbacks-enabled case: a provider that
            # does not declare the request's own parameters is never a valid
            # target for a .with_structured_output() call.
            "require_parameters": True,
        }
        return ChatOpenAI(
            model=model,
            temperature=config.LLM_TEMPERATURE,
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY", ""),
            extra_body={"provider": provider_routing},
        )
    raise ValueError(f"Unsupported LLM_PROVIDER: {config.LLM_PROVIDER}")


def _render_rationale(link: "ProposedLink", source_by_id: dict) -> str:
    """Flattens the structured link fields into the single free-text
    matched_on column the Relationship Store already has, so no schema
    migration is needed. Rendered as fixed lines rather than a paragraph:
    the Visualization UI shows this with white-space:pre-wrap, and an
    on-call reader scans it instead of reading it."""
    lines = [link.summary.strip()]
    root_source = source_by_id.get(link.root_cause_event_id)
    if root_source:
        lines.append(f"\nROOT CAUSE  {root_source}")
    if link.next_step.strip():
        lines.append(f"NEXT STEP   {link.next_step.strip()}")
    return "\n".join(lines)


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

    def __init__(self, observer: Optional[SemanticObserver] = None):
        self._llm = _build_llm()
        prompt = ChatPromptTemplate.from_messages(
            [("system", SYSTEM_PROMPT), ("human", USER_PROMPT)]
        )
        self._chain = prompt | self._llm.with_structured_output(CorrelationResult)
        self._observer = observer

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
                if self._observer:
                    self._observer.on_skip(bucket, "bucket_size_lt_2")
                continue
            # Only worth an LLM call if the bucket spans more than one
            # source system — same-system-only clusters are usually just
            # chatty logging, not a cross-system incident.
            if len({e.source_system for e in bucket}) < 2:
                if self._observer:
                    self._observer.on_skip(bucket, "single_source_system")
                continue
            for chunk_start in range(0, len(bucket), config.SEMANTIC_MAX_BATCH_SIZE):
                chunk = bucket[chunk_start : chunk_start + config.SEMANTIC_MAX_BATCH_SIZE]
                edges.extend(self._correlate_chunk(chunk))
        return edges

    def _correlate_chunk(self, chunk: List[LogEvent]) -> List[CorrelationEdge]:
        valid_ids = {e.event_id for e in chunk}
        source_by_id = {e.event_id: e.source_system for e in chunk}
        try:
            result: CorrelationResult = self._chain.invoke({"event_lines": _format_events(chunk)})
        except Exception as exc:
            logger.warning("LLM correlation call failed for a chunk of %d events: %s", len(chunk), exc)
            if self._observer:
                self._observer.on_error(chunk, exc)
            return []

        if self._observer:
            self._observer.on_raw_result(chunk, result)

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
                    matched_on=_render_rationale(link, source_by_id),
                )
            )
        return edges
