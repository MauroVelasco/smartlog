"""
tests/test_harness_cli.py

Fix 2 (postgres-scenario-harness follow-up): the `--json-out` summary must
also carry the empty-semantic-result signal, not just the terminal report
(harness/report.py's `empty_semantic_result_chunks`).
"""
from datetime import datetime, timezone

from correlation.langchain_agents import CorrelationResult
from harness.cli import _result_to_dict
from harness.observer import RecordingObserver
from harness.report import CaseRunResult
from models.schema import LogEvent, SourceSystem


def _event(source_system, message="something happened", minute=0):
    return LogEvent(
        source_system=source_system,
        origin="test",
        timestamp=datetime(2026, 8, 3, 12, minute, 0, tzinfo=timezone.utc),
        message=message,
    )


def test_result_to_dict_reports_empty_semantic_result_count():
    chunk = [_event(SourceSystem.POSTGRES), _event(SourceSystem.TOMCAT, minute=1)]
    recorder = RecordingObserver()
    recorder.on_raw_result(chunk, CorrelationResult(links=[]))
    result = CaseRunResult(case_id="t2-example", tier="2", outcome_class="value", status="FAIL", observer=recorder)

    payload = _result_to_dict(result)

    assert payload["empty_semantic_results"] == 1


def test_result_to_dict_empty_semantic_result_count_zero_without_observer():
    result = CaseRunResult(case_id="t2-example", tier="2", outcome_class="value", status="PASS", observer=None)

    payload = _result_to_dict(result)

    assert payload["empty_semantic_results"] == 0
