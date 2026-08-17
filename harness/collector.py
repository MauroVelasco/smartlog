"""
harness/collector.py

Poll-until-anchors-resolve loop (postgres-scenario-harness harness
architecture). Neither `TomcatExtractor` nor `PostgresLogFileExtractor`
tails — both re-read their whole source on every call
(`TomcatExtractor.extract()` ignores its `start_time`/`end_time` args
entirely; `PostgresLogFileExtractor.extract()` only uses
`pg_current_logfile()` + a fresh `pg_read_file()`), so "poll" is simply
calling `extract()` again. No offset bookkeeping, no risk of
double-consuming.

Case isolation: `normalize(..., start_time=run_start)` is load-bearing, not
cosmetic. `DETERMINISTIC_TIME_WINDOW_SECONDS=300` means a PREVIOUS case's
events, still present in the re-read log files, would otherwise link into
the current case's correlation run.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import List

from extraction.db_log_extractor import PostgresLogFileExtractor
from extraction.tomcat_extractor import TomcatExtractor
from harness.models import Step
from models.schema import LogEvent
from normalization.normalizer import normalize

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_POLL_INTERVAL_SECONDS = 1
DEFAULT_GAP_SECONDS = 2  # between consecutive cases, per design


class CollectionTimeout(Exception):
    """Raised when one or more anchor steps never landed within the
    timeout. `missing` names exactly which step ids — never a silent
    partial pass."""

    def __init__(self, missing: List[str]):
        self.missing = missing
        super().__init__(f"anchors never resolved within timeout, missing steps: {missing}")


def _anchor_steps(steps: List[Step]) -> List[Step]:
    """Steps the collector must wait for. Excludes CloudWatch manual steps
    (emits=None) — they're description-only and never triggered."""
    return [s for s in steps if getattr(s, "emits", None) is not None]


def _matches(event: LogEvent, step: Step) -> bool:
    return event.source_system == step.emits.source_system and step.emits.message_contains in event.message


def extract_all(run_start: datetime, postgres_connection_name: str = "app") -> List[LogEvent]:
    tomcat_records = TomcatExtractor().extract(start_time=run_start, end_time=None)
    pg_records = PostgresLogFileExtractor(postgres_connection_name).extract(start_time=run_start, end_time=None)
    return normalize(tomcat_records + pg_records, start_time=run_start)


def collect(
    steps: List[Step],
    run_start: datetime,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    postgres_connection_name: str = "app",
) -> List[LogEvent]:
    """Poll until every anchor step's `emits` selector matches at least one
    event, then take ONE settle pass (absorbs late continuation lines —
    Tomcat multi-line stack traces are stitched only once the NEXT header
    line arrives, so an ERROR case's final entry can land one poll behind).
    Raises CollectionTimeout naming exactly which steps never landed."""
    anchors = _anchor_steps(steps)
    deadline = time.monotonic() + timeout_seconds
    events: List[LogEvent] = []

    while True:
        events = extract_all(run_start, postgres_connection_name)
        missing = [s.id for s in anchors if not any(_matches(e, s) for e in events)]
        if not missing:
            break
        if time.monotonic() >= deadline:
            raise CollectionTimeout(missing=missing)
        time.sleep(interval_seconds)

    time.sleep(interval_seconds)
    return extract_all(run_start, postgres_connection_name)
