"""
harness/report.py

Plain-text terminal report (postgres-scenario-harness harness
architecture). The harness is a local reporting tool, not a CI gate: a
failing or low-scoring case status is informational, never build-breaking.
Exit code 0 always, unless the caller explicitly opts in via
`--fail-on-error` (and even then, only ERRORED/TIMEOUT cases — infra
failures, not low precision/recall — trip it).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from harness.observer import RecordingObserver
from harness.scoring import ScoreResult

# Case statuses (design): PASS | FAIL | REPRODUCED | NOT_REPRODUCED |
# ERRORED | UNRESOLVED | TIMEOUT
STATUS_ERRORED = "ERRORED"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_UNRESOLVED = "UNRESOLVED"
STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_REPRODUCED = "REPRODUCED"
STATUS_NOT_REPRODUCED = "NOT_REPRODUCED"

_INFRA_FAILURE_STATUSES = {STATUS_ERRORED, STATUS_TIMEOUT}


@dataclass
class CaseRunResult:
    case_id: str
    tier: str
    outcome_class: str
    status: str
    score: Optional[ScoreResult] = None
    unresolved_steps: List[str] = field(default_factory=list)
    timeout_missing: List[str] = field(default_factory=list)
    observer: Optional[RecordingObserver] = None
    error: Optional[str] = None
    gate_untrustworthy: bool = False  # True if this run's Tier 2 result predates a passing Phase 3 gate


def _score_summary(score: Optional[ScoreResult]) -> str:
    if score is None:
        return "precision=- recall=- stage_mismatch=0 contamination=0"
    precision = "undef" if score.precision_undefined else f"{score.precision:.2f}"
    recall = "undef" if score.recall_undefined else f"{score.recall:.2f}"
    incident_sizes = ",".join(str(i.component_size) for i in score.incidents if i.component_size is not None) or "-"
    return (
        f"precision={precision} recall={recall} "
        f"stage_mismatch={len(score.stage_mismatches)} contamination={len(score.contamination)} "
        f"incident_size=[{incident_sizes}]"
    )


def format_case_line(result: CaseRunResult) -> str:
    line = f"[{result.status:14s}] {result.case_id:45s} tier={result.tier:4s} {_score_summary(result.score)}"
    if result.gate_untrustworthy:
        line += "  ** UNTRUSTWORTHY: Phase 3 zero-deterministic-edges gate has not passed this run **"
    return line


def format_case_detail(result: CaseRunResult) -> str:
    lines: List[str] = []
    if result.unresolved_steps:
        lines.append(f"    unresolved anchors: {result.unresolved_steps}")
    if result.timeout_missing:
        lines.append(f"    timed out waiting for: {result.timeout_missing}")
    if result.error:
        lines.append(f"    error: {result.error}")
    if result.observer is not None:
        for skip_bucket, reason in result.observer.skips:
            lines.append(f"    bucket_skipped ({reason}): {len(skip_bucket)} events")
        for link in result.observer.sub_threshold_links:
            lines.append(
                f"    sub_threshold_link: {link.source_event_id[:8]}..->{link.target_event_id[:8]}.. "
                f"confidence={link.confidence:.2f} (filtered by threshold, not 'no link') rationale={link.rationale!r}"
            )
        for _chunk, exc in result.observer.errors:
            lines.append(f"    llm_call_failed: {exc!r} (distinct from a genuine empty result)")
    if result.score is not None:
        for pair in result.score.stage_mismatches:
            lines.append(f"    stage_mismatch: {pair}")
        for pair in result.score.contamination:
            lines.append(f"    contamination: {pair}")
        for pair in result.score.forbidden_edges_observed:
            lines.append(f"    FORBIDDEN EDGE OBSERVED: {pair} (expected.forbidden_edges asserted this must not link)")
    return "\n".join(lines)


def format_suite_footer(results: List[CaseRunResult]) -> str:
    by_tier: dict = {}
    for r in results:
        by_tier.setdefault(str(r.tier), []).append(r)

    lines = ["", "=== Suite Summary ==="]
    for tier in sorted(by_tier, key=lambda t: (t == "doc", t)):
        group = by_tier[tier]
        status_counts: dict = {}
        for r in group:
            status_counts[r.status] = status_counts.get(r.status, 0) + 1
        counts_str = ", ".join(f"{status}={count}" for status, count in sorted(status_counts.items()))
        lines.append(f"Tier {tier}: {len(group)} cases — {counts_str}")
    return "\n".join(lines)


def render_report(results: List[CaseRunResult]) -> str:
    lines: List[str] = []
    for result in results:
        lines.append(format_case_line(result))
        detail = format_case_detail(result)
        if detail:
            lines.append(detail)
    lines.append(format_suite_footer(results))
    return "\n".join(lines)


def exit_code(results: List[CaseRunResult], fail_on_error: bool) -> int:
    """Exit code 0 ALWAYS, unless the caller opts in via --fail-on-error —
    and even then, only infra failures (ERRORED/TIMEOUT) trip it, never a
    low-scoring PASS/FAIL/REPRODUCED/NOT_REPRODUCED/UNRESOLVED case (the
    harness reports scores, it does not gate on them)."""
    if not fail_on_error:
        return 0
    return 1 if any(r.status in _INFRA_FAILURE_STATUSES for r in results) else 0
