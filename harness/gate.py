"""
harness/gate.py

Reusable core of the Phase 3 zero-deterministic-edges gate check
(postgres-scenario-harness). Both `tests/test_zero_deterministic_edges_gate.py`
(the pytest-driven check used during development/CI-adjacent runs) and
`harness/cli.py` (which re-runs it automatically before any gated case, per
spec: "it is an empirical precondition... the harness re-runs it as part of
the case set") delegate to this single implementation.
"""
from __future__ import annotations

import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from correlation.pipeline import run_correlation
from extraction.db_log_extractor import PostgresLogFileExtractor
from extraction.tomcat_extractor import TomcatExtractor
from models.schema import LogEvent, SourceSystem
from normalization.normalizer import normalize

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "postgres-log-source"))
import trigger as pg_trigger  # noqa: E402  (path-injected sibling module, not a package)

DEFAULT_TOMCAT_BASE_URL = "http://localhost:8080"
DEFAULT_POSTGRES_DSN = "postgresql://postgres:postgres@localhost:5432/log_intelligence"

_TOMCAT_SCENARIOS = [
    "pessimistic-lock", "pool-checkout-timeout", "order-persist-failure",
    "gateway-read-timeout", "validation-rejected", "connection-reset",
    "cache-warmed", "inventory-checked",
]

_POSTGRES_NOISE = [
    ("INFO", "cache warmed for key set"),
    ("WARNING", "connection pool nearing capacity"),
    ("ERROR", "database transaction rolled back"),
    ("ERROR", "circuit breaker opened for dependency"),
]

_CLOUDWATCH_NOISE_MESSAGES = [
    ("INFO", "Health check passed"),
    ("WARN", "Response time exceeded threshold"),
    ("ERROR", "Payment gateway timeout"),
    ("ERROR", "Message queue publish failed"),
]


@dataclass
class GateResult:
    passed: bool
    deterministic_edges: int
    event_count: int
    stats: dict
    reason: Optional[str] = None  # set when passed=False, or "unreachable" when deps are down


def live_deps_unreachable(tomcat_base_url: str, postgres_dsn: str) -> Optional[str]:
    try:
        urllib.request.urlopen(f"{tomcat_base_url}/health", timeout=3)
    except Exception as exc:
        return f"Tomcat not reachable at {tomcat_base_url}: {exc}"
    try:
        conn = pg_trigger.connect(postgres_dsn)
        conn.close()
    except Exception as exc:
        return f"Postgres not reachable at {postgres_dsn}: {exc}"
    return None


def _trigger_tomcat_noise(tomcat_base_url: str) -> None:
    for name in _TOMCAT_SCENARIOS:
        url = f"{tomcat_base_url}/api/orders/scenario?name={name}&identifierFree=true"
        urllib.request.urlopen(url, timeout=5).read()


def _trigger_postgres_noise(postgres_dsn: str) -> None:
    conn = pg_trigger.connect(postgres_dsn)
    try:
        for level, message in _POSTGRES_NOISE:
            pg_trigger.emit_log(conn, {"p_level": level, "p_message": message, "p_identifier_free": True})
    finally:
        conn.close()


def _cloudwatch_noise_events(run_start: datetime) -> List[LogEvent]:
    return [
        LogEvent(
            source_system=SourceSystem.CLOUDWATCH,
            origin="cloudwatch-log-generator:identifier-free-fixture",
            timestamp=run_start + timedelta(seconds=i),
            level=level,
            message=message,
            identifiers={},
        )
        for i, (level, message) in enumerate(_CLOUDWATCH_NOISE_MESSAGES)
    ]


def run_gate_check(
    tomcat_base_url: str = DEFAULT_TOMCAT_BASE_URL,
    postgres_dsn: str = DEFAULT_POSTGRES_DSN,
    postgres_connection_name: str = "app",
) -> GateResult:
    """Runs all three generators in identifier-free mode on a noise-only
    batch (no scenario narrative), normalizes, calls run_correlation(), and
    checks deterministic_edges == 0. Raises nothing on an unreachable
    dependency — callers should check `live_deps_unreachable()` first if
    they want to distinguish "gate failed" from "couldn't run the gate"."""
    run_start = datetime.now(timezone.utc) - timedelta(seconds=2)

    _trigger_tomcat_noise(tomcat_base_url)
    _trigger_postgres_noise(postgres_dsn)
    time.sleep(2)  # settle — neither extractor tails, both re-read from scratch

    tomcat_records = TomcatExtractor().extract(start_time=run_start, end_time=None)
    pg_records = PostgresLogFileExtractor(postgres_connection_name).extract(start_time=run_start, end_time=None)

    tomcat_events = normalize(tomcat_records, start_time=run_start)
    pg_events = normalize(pg_records, start_time=run_start)
    cloudwatch_events = _cloudwatch_noise_events(run_start)

    all_events = tomcat_events + pg_events + cloudwatch_events
    expected_min = len(_TOMCAT_SCENARIOS) + len(_POSTGRES_NOISE) + len(_CLOUDWATCH_NOISE_MESSAGES)

    if len(all_events) < expected_min:
        return GateResult(
            passed=False,
            deterministic_edges=-1,
            event_count=len(all_events),
            stats={},
            reason=(
                f"expected at least {expected_min} noise events, got {len(all_events)} "
                f"({len(tomcat_events)} tomcat, {len(pg_events)} postgres, {len(cloudwatch_events)} cloudwatch) "
                "— trigger or extraction failed silently, gate result is not trustworthy"
            ),
        )

    _, stats = run_correlation(all_events, use_llm=False)
    deterministic_edges = stats["deterministic_edges"]
    passed = deterministic_edges == 0
    return GateResult(
        passed=passed,
        deterministic_edges=deterministic_edges,
        event_count=len(all_events),
        stats=stats,
        reason=None if passed else f"identifier-free mode produced {deterministic_edges} deterministic edge(s) on background noise",
    )
