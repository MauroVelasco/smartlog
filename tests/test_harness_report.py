"""
tests/test_harness_report.py

Fix 2 (postgres-scenario-harness follow-up): `on_raw_result` already fires
for EVERY chunk, including ones where the LLM proposed zero links, but
`report.py` previously only surfaced sub-threshold links — a genuinely
empty response left no visible trace, indistinguishable from "we have no
data". These tests assert the empty case is surfaced distinctly from both
a non-empty result and a call failure, in both the terminal report and the
`--json-out` dict.
"""
from datetime import datetime, timezone

from correlation.langchain_agents import CorrelationResult, ProposedLink
from harness.observer import RecordingObserver
from harness.report import CaseRunResult, format_case_detail
from models.schema import LogEvent, SourceSystem


def _event(source_system, message="something happened", minute=0):
    return LogEvent(
        source_system=source_system,
        origin="test",
        timestamp=datetime(2026, 8, 3, 12, minute, 0, tzinfo=timezone.utc),
        message=message,
    )


def _case_result(observer):
    return CaseRunResult(case_id="t2-example", tier="2", outcome_class="value", status="FAIL", observer=observer)


def test_format_case_detail_surfaces_empty_raw_result_distinctly():
    chunk = [_event(SourceSystem.POSTGRES), _event(SourceSystem.TOMCAT, minute=1)]
    recorder = RecordingObserver()
    recorder.on_raw_result(chunk, CorrelationResult(links=[]))

    detail = format_case_detail(_case_result(recorder))

    assert "LLM proposed 0 links (empty result)" in detail
    assert "chunk of 2 events" in detail


def test_format_case_detail_does_not_report_empty_for_a_non_empty_result():
    a = _event(SourceSystem.POSTGRES)
    b = _event(SourceSystem.TOMCAT, minute=1)
    link = ProposedLink(source_event_id=a.event_id, target_event_id=b.event_id, confidence=0.9, rationale="matches")
    recorder = RecordingObserver()
    recorder.on_raw_result([a, b], CorrelationResult(links=[link]))

    detail = format_case_detail(_case_result(recorder))

    assert "empty result" not in detail


def test_format_case_detail_distinguishes_empty_result_from_call_failure():
    chunk = [_event(SourceSystem.POSTGRES), _event(SourceSystem.TOMCAT, minute=1)]
    recorder = RecordingObserver()
    recorder.on_raw_result(chunk, CorrelationResult(links=[]))
    recorder.on_error(chunk, RuntimeError("LLM provider unavailable"))

    detail = format_case_detail(_case_result(recorder))

    assert "LLM proposed 0 links (empty result)" in detail
    assert "llm_call_failed" in detail
    # Distinct lines, not conflated into one message.
    empty_lines = [line for line in detail.splitlines() if "LLM proposed 0 links" in line]
    failure_lines = [line for line in detail.splitlines() if "llm_call_failed" in line]
    assert len(empty_lines) == 1
    assert len(failure_lines) == 1
    assert empty_lines[0] != failure_lines[0]
