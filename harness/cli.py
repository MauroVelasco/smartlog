"""
harness/cli.py

    python -m harness.cli --cases scenarios/ [--case ID] [--no-llm] [--json-out FILE]

Wires trigger -> collect -> score -> report for every scenario case in a
directory (postgres-scenario-harness). Local reporting tool: exit code 0
always unless --fail-on-error is passed, and even then only for
ERRORED/TIMEOUT (infra failures), never a low-scoring case.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from correlation.pipeline import run_correlation
from harness.collector import DEFAULT_GAP_SECONDS, CollectionTimeout, collect
from harness.gate import DEFAULT_POSTGRES_DSN, DEFAULT_TOMCAT_BASE_URL, live_deps_unreachable, run_gate_check
from harness.loader import ScenarioValidationError, load_directory
from harness.models import ScenarioCase, Step
from harness.observer import RecordingObserver
from harness.report import (
    STATUS_ERRORED,
    STATUS_FAIL,
    STATUS_NOT_REPRODUCED,
    STATUS_PASS,
    STATUS_REPRODUCED,
    STATUS_TIMEOUT,
    STATUS_UNRESOLVED,
    CaseRunResult,
    exit_code,
    render_report,
)
from harness.scoring import resolve_anchors, score
from harness.triggers import CloudWatchTrigger, PostgresTrigger, TomcatTrigger


def _fire_step(step: Step, tomcat_trigger: TomcatTrigger, postgres_trigger: PostgresTrigger, cloudwatch_trigger: CloudWatchTrigger) -> None:
    if step.wait_ms_before:
        time.sleep(step.wait_ms_before / 1000)
    if step.source == "tomcat":
        tomcat_trigger.fire(step)
    elif step.source == "postgres":
        postgres_trigger.fire(step)
    else:
        cloudwatch_trigger.fire(step)


def run_case(
    case: ScenarioCase,
    use_llm_override: Optional[bool],
    tomcat_trigger: TomcatTrigger,
    postgres_trigger: PostgresTrigger,
    cloudwatch_trigger: CloudWatchTrigger,
    gate_untrustworthy: bool,
) -> CaseRunResult:
    tier = str(case.tier)
    run_start = datetime.now(timezone.utc) - timedelta(seconds=2)

    for step in case.steps:
        _fire_step(step, tomcat_trigger, postgres_trigger, cloudwatch_trigger)

    try:
        events = collect(case.steps, run_start)
    except CollectionTimeout as exc:
        return CaseRunResult(
            case_id=case.case_id, tier=tier, outcome_class=case.outcome_class,
            status=STATUS_TIMEOUT, timeout_missing=exc.missing, gate_untrustworthy=gate_untrustworthy,
        )

    anchors, unresolved = resolve_anchors(events, case.steps)
    if unresolved:
        return CaseRunResult(
            case_id=case.case_id, tier=tier, outcome_class=case.outcome_class,
            status=STATUS_UNRESOLVED, unresolved_steps=unresolved, gate_untrustworthy=gate_untrustworthy,
        )

    use_llm = case.use_llm if use_llm_override is None else (case.use_llm and use_llm_override)
    recorder = RecordingObserver()
    try:
        edges, _stats = run_correlation(events, use_llm=use_llm, semantic_observer=recorder)
    except Exception as exc:
        # SemanticCorrelationAgent's __init__ builds the LLM client
        # (_build_llm()) outside the try/except that RecordingObserver's
        # on_error hooks into — a missing/invalid API key raises here,
        # before any chunk is ever sent. Treat it the same as an in-flight
        # LLM call failure: ERRORED, not an uncaught crash of the whole run.
        recorder.errors.append(([], exc))

    if recorder.errors:
        return CaseRunResult(
            case_id=case.case_id, tier=tier, outcome_class=case.outcome_class,
            status=STATUS_ERRORED, observer=recorder, gate_untrustworthy=gate_untrustworthy,
        )

    result = score(events, edges, anchors, case.expected)
    reproduced_ok = (
        not result.false_positives
        and not result.false_negatives
        and not result.stage_mismatches
        and not result.forbidden_edges_observed
        and all(i.actual_grouped == i.expected_grouped for i in result.incidents)
    )

    if case.outcome_class == "documented-limitation":
        status = STATUS_REPRODUCED if reproduced_ok else STATUS_NOT_REPRODUCED
    else:
        status = STATUS_PASS if reproduced_ok else STATUS_FAIL

    return CaseRunResult(
        case_id=case.case_id, tier=tier, outcome_class=case.outcome_class,
        status=status, score=result, observer=recorder, gate_untrustworthy=gate_untrustworthy,
    )


def _result_to_dict(result: CaseRunResult) -> dict:
    return {
        "case_id": result.case_id,
        "tier": result.tier,
        "outcome_class": result.outcome_class,
        "status": result.status,
        "precision": None if result.score is None or result.score.precision_undefined else result.score.precision,
        "recall": None if result.score is None or result.score.recall_undefined else result.score.recall,
        "unresolved_steps": result.unresolved_steps,
        "timeout_missing": result.timeout_missing,
        "gate_untrustworthy": result.gate_untrustworthy,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="postgres-scenario-harness runner")
    parser.add_argument("--cases", default="scenarios/", help="Directory of scenario JSON files")
    parser.add_argument("--case", default=None, help="Run only this case_id")
    parser.add_argument("--no-llm", action="store_true", help="Force use_llm=False for every case")
    parser.add_argument("--json-out", default=None, help="Also write a JSON summary to this path")
    parser.add_argument("--fail-on-error", action="store_true", help="Exit 1 if any case is ERRORED/TIMEOUT")
    parser.add_argument("--tomcat-base-url", default=DEFAULT_TOMCAT_BASE_URL)
    parser.add_argument("--postgres-dsn", default=DEFAULT_POSTGRES_DSN)
    parser.add_argument("--gap-seconds", type=float, default=DEFAULT_GAP_SECONDS, help="Delay between cases for isolation")
    parser.add_argument("--skip-gate-check", action="store_true", help="Don't auto-run the Phase 3 gate before gated cases")
    args = parser.parse_args(argv)

    try:
        all_cases = load_directory(Path(args.cases))
    except ScenarioValidationError as exc:
        print(f"Scenario load failed: {exc}", file=sys.stderr)
        return 2

    if args.case:
        cases = [c for c in all_cases if c.case_id == args.case]
        if not cases:
            print(f"No case with case_id={args.case!r} found under {args.cases}", file=sys.stderr)
            return 2
    else:
        cases = all_cases

    gate_untrustworthy = False
    if any(c.gated_by_phase3 for c in cases) and not args.skip_gate_check:
        unreachable = live_deps_unreachable(args.tomcat_base_url, args.postgres_dsn)
        if unreachable:
            print(f"WARNING: cannot run Phase 3 gate check ({unreachable}) — gated results marked untrustworthy", file=sys.stderr)
            gate_untrustworthy = True
        else:
            gate_result = run_gate_check(args.tomcat_base_url, args.postgres_dsn)
            if not gate_result.passed:
                print(f"GATE FAILURE: {gate_result.reason}", file=sys.stderr)
                gate_untrustworthy = True
            else:
                print(
                    f"Phase 3 gate PASSED: {gate_result.deterministic_edges} deterministic edges "
                    f"on {gate_result.event_count} noise events — Tier 2/doc-gated results this run are trustworthy",
                    file=sys.stderr,
                )

    postgres_trigger = PostgresTrigger(dsn=args.postgres_dsn)
    tomcat_trigger = TomcatTrigger(base_url=args.tomcat_base_url)
    cloudwatch_trigger = CloudWatchTrigger()
    use_llm_override = False if args.no_llm else None

    results = []
    try:
        for i, case in enumerate(cases):
            if i > 0:
                time.sleep(args.gap_seconds)
            case_gate_untrustworthy = gate_untrustworthy and case.gated_by_phase3
            results.append(
                run_case(case, use_llm_override, tomcat_trigger, postgres_trigger, cloudwatch_trigger, case_gate_untrustworthy)
            )
    finally:
        postgres_trigger.close()

    print(render_report(results))

    if args.json_out:
        Path(args.json_out).write_text(json.dumps([_result_to_dict(r) for r in results], indent=2, default=str))

    return exit_code(results, args.fail_on_error)


if __name__ == "__main__":
    sys.exit(main())
