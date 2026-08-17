"""
Phase 3 HARD BLOCKING GATE (postgres-scenario-harness tasks.md 3.1/3.2).

Before any Tier 2 scenario case is authored or trusted, this test proves,
empirically, that identifier-free mode across all three generators (Tomcat,
Postgres, CloudWatch) produces genuinely ZERO deterministic edges on
background noise. If this test fails, every downstream Tier 2 result in
that run is untrustworthy until this gate passes again — per the spec's
"blocking gate" requirement.

BLOCKS: scenarios/t2-*.json (6.4) and 3 of the 4 scenarios/doc-*.json cases
(all except doc-error-code-false-link, per each case's `gated_by_phase3`
field — 6.5).

The actual check lives in harness/gate.py (`run_gate_check`), shared with
`harness/cli.py`, which re-runs this same check automatically before any
gated case (spec: "it is an empirical precondition... the harness re-runs
it as part of the case set").

Requires live containers: `docker compose up -d` (postgres + tomcat) from
the repo root. Skipped (not failed) if either dependency is unreachable —
this keeps the file safe to include in a routine `pytest` run without a
live stack, while still being the authoritative gate when one is up.
"""
from __future__ import annotations

import pytest

from harness.gate import DEFAULT_POSTGRES_DSN, DEFAULT_TOMCAT_BASE_URL, live_deps_unreachable, run_gate_check


def test_identifier_free_noise_produces_zero_deterministic_edges():
    """Phase 3 gate. Empirical precondition, re-run as part of the case set
    — not a one-time check (spec: "identifier-free mode produces zero
    deterministic edges on background noise")."""
    unreachable_reason = live_deps_unreachable(DEFAULT_TOMCAT_BASE_URL, DEFAULT_POSTGRES_DSN)
    if unreachable_reason:
        pytest.skip(f"live deps unreachable (docker compose up -d?): {unreachable_reason}")

    result = run_gate_check(DEFAULT_TOMCAT_BASE_URL, DEFAULT_POSTGRES_DSN)

    assert result.passed, (
        f"GATE FAILURE: {result.reason} (stats={result.stats}). Per the postgres-scenario-harness "
        "spec, every downstream Tier 2 result is untrustworthy until this gate passes again."
    )
    assert result.deterministic_edges == 0
