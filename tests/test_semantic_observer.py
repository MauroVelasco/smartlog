from datetime import datetime, timezone

import pytest

from correlation.langchain_agents import CorrelationResult, ProposedLink, SemanticCorrelationAgent, SemanticObserver
from models.schema import LogEvent, SourceSystem


def _event(source_system, minute=0, message="something happened"):
    return LogEvent(
        source_system=source_system,
        origin="test",
        timestamp=datetime(2026, 8, 3, 12, minute, 0, tzinfo=timezone.utc),
        message=message,
    )


class _RecordingObserver(SemanticObserver):
    def __init__(self):
        self.skips = []
        self.raw_results = []
        self.errors = []

    def on_skip(self, bucket, reason):
        self.skips.append((list(bucket), reason))

    def on_raw_result(self, chunk, result):
        self.raw_results.append((list(chunk), result))

    def on_error(self, chunk, exc):
        self.errors.append((list(chunk), exc))


def _agent_with_fake_chain(chain):
    """Build a SemanticCorrelationAgent without touching _build_llm/network,
    matching the class's own construction shape (self._chain is what
    _correlate_chunk() invokes)."""
    agent = SemanticCorrelationAgent.__new__(SemanticCorrelationAgent)
    agent._llm = None
    agent._chain = chain
    agent._observer = None
    return agent


class _FakeChain:
    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc
        self.invocations = 0

    def invoke(self, _payload):
        self.invocations += 1
        if self._exc is not None:
            raise self._exc
        return self._result


def test_semantic_observer_base_class_is_a_no_op():
    observer = SemanticObserver()
    # Must not raise — these are no-op defaults every real call site can rely on.
    observer.on_skip([], "bucket_size_lt_2")
    observer.on_raw_result([], CorrelationResult(links=[]))
    observer.on_error([], RuntimeError("boom"))


def test_default_observer_is_none_and_correlate_behaves_unchanged():
    a = _event(SourceSystem.TOMCAT, minute=0)
    b = _event(SourceSystem.POSTGRES, minute=0)
    chain = _FakeChain(result=CorrelationResult(links=[]))
    agent = _agent_with_fake_chain(chain)
    edges = agent.correlate([a, b])
    assert edges == []
    assert chain.invocations == 1


def test_on_skip_fires_for_bucket_below_two_events():
    recorder = _RecordingObserver()
    agent = _agent_with_fake_chain(_FakeChain(result=CorrelationResult(links=[])))
    agent._observer = recorder
    # Two events far enough apart in time to land in separate
    # SEMANTIC_TIME_BUCKET_SECONDS buckets — each bucket then has exactly
    # one event, which is what actually reaches the per-bucket skip check
    # (a single-event list overall short-circuits earlier, before bucketing).
    far_apart = [
        _event(SourceSystem.TOMCAT, minute=0),
        _event(SourceSystem.POSTGRES, minute=59),
    ]
    agent.correlate(far_apart)
    assert len(recorder.skips) == 2
    assert all(reason == "bucket_size_lt_2" for _bucket, reason in recorder.skips)


def test_on_skip_fires_for_single_source_system_bucket():
    recorder = _RecordingObserver()
    agent = _agent_with_fake_chain(_FakeChain(result=CorrelationResult(links=[])))
    agent._observer = recorder
    same_source = [_event(SourceSystem.POSTGRES, minute=0), _event(SourceSystem.POSTGRES, minute=0)]
    agent.correlate(same_source)
    assert len(recorder.skips) == 1
    assert recorder.skips[0][1] == "single_source_system"


def test_on_raw_result_fires_before_confidence_filter_with_sub_threshold_link():
    a = _event(SourceSystem.TOMCAT, minute=0)
    b = _event(SourceSystem.POSTGRES, minute=0)
    sub_threshold_link = ProposedLink(
        source_event_id=a.event_id,
        target_event_id=b.event_id,
        confidence=0.1,  # below SEMANTIC_MIN_CONFIDENCE (0.55 default)
        rationale="weak textual overlap",
    )
    raw_result = CorrelationResult(links=[sub_threshold_link])
    recorder = _RecordingObserver()
    agent = _agent_with_fake_chain(_FakeChain(result=raw_result))
    agent._observer = recorder

    edges = agent.correlate([a, b])

    # The observer sees the RAW result including the sub-threshold link...
    assert len(recorder.raw_results) == 1
    seen_chunk, seen_result = recorder.raw_results[0]
    assert seen_result.links[0].confidence == 0.1
    # ...but correlate() itself still applies the confidence filter downstream.
    assert edges == []


def test_on_error_fires_when_chain_invoke_raises():
    a = _event(SourceSystem.TOMCAT, minute=0)
    b = _event(SourceSystem.POSTGRES, minute=0)
    boom = RuntimeError("LLM provider unavailable")
    recorder = _RecordingObserver()
    agent = _agent_with_fake_chain(_FakeChain(exc=boom))
    agent._observer = recorder

    edges = agent.correlate([a, b])

    assert edges == []
    assert len(recorder.errors) == 1
    seen_chunk, seen_exc = recorder.errors[0]
    assert seen_exc is boom
