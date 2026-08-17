"""
Ingestion & Normalization (architecture slide 5, stage 2):
  "Parse, timestamp-align, and standardize each source's log format"

Takes the raw, source-specific RawLogRecord objects from extraction/ and
turns them into the common LogEvent shape everything downstream depends
on: UTC timestamps, a plain-text message, a level, and a dict of
correlation identifiers (request_id, trace_id, user_id, error_code,
service_name) pulled out via regex — "the same clues an engineer would
chase manually" (business case slide 4).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from dateutil import parser as dateutil_parser

import config
from models.schema import LogEvent, RawLogRecord, SourceSystem

logger = logging.getLogger(__name__)

_COMPILED_KEY_PATTERNS = {
    key: re.compile(pattern, re.IGNORECASE) for key, pattern in config.CORRELATION_KEY_PATTERNS.items()
}

_LEVEL_PATTERN = re.compile(r"\b(TRACE|DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|SEVERE)\b", re.IGNORECASE)

# Matches Tomcat's default `dd-MMM-yyyy HH:mm:ss.SSS` and the JUL fallback
# `yyyy-MM-dd HH:mm:ss` formats seen in catalina.out.
_TOMCAT_TS_PATTERN = re.compile(
    r"(?P<ts>\d{2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2}:\d{2}\.\d{3}|\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
)


def extract_identifiers(text: str) -> Dict[str, str]:
    """Pull correlation keys out of free text. This is the deterministic
    half of the hybrid design — cheap regex first, LLM only as fallback."""
    found: Dict[str, str] = {}
    for key, pattern in _COMPILED_KEY_PATTERNS.items():
        match = pattern.search(text)
        if match:
            found[key] = match.group(1)
    return found


def extract_level(text: str) -> Optional[str]:
    match = _LEVEL_PATTERN.search(text)
    return match.group(1).upper() if match else None


def _normalize_cloudwatch(record: RawLogRecord) -> LogEvent:
    payload = record.raw_payload
    ts_ms = payload.get("timestamp_ms")
    timestamp = (
        datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc) if ts_ms is not None else datetime.now(timezone.utc)
    )
    message = payload.get("message", "")
    return LogEvent(
        source_system=SourceSystem.CLOUDWATCH,
        origin=record.origin,
        timestamp=timestamp,
        level=extract_level(message),
        message=message,
        identifiers=extract_identifiers(message),
        host=payload.get("log_stream_name"),
    )


def _normalize_tomcat(record: RawLogRecord) -> Optional[LogEvent]:
    line = record.raw_payload.get("line", "")
    ts_match = _TOMCAT_TS_PATTERN.search(line)
    if not ts_match:
        return None  # continuation line of a multi-line stack trace; caller may stitch these
    try:
        timestamp = dateutil_parser.parse(ts_match.group("ts"))
    except (ValueError, OverflowError):
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return LogEvent(
        source_system=SourceSystem.TOMCAT,
        origin=record.origin,
        timestamp=timestamp.astimezone(timezone.utc),
        level=extract_level(line),
        message=line,
        identifiers=extract_identifiers(line),
    )


def _normalize_gcp(record: RawLogRecord) -> LogEvent:
    payload = record.raw_payload
    ts_raw = payload.get("timestamp")
    timestamp = dateutil_parser.parse(ts_raw) if ts_raw else datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    message = payload.get("message", "")
    return LogEvent(
        source_system=SourceSystem.GCP_LOGGING,
        origin=record.origin,
        timestamp=timestamp.astimezone(timezone.utc),
        level=payload.get("severity") or extract_level(message),
        message=message,
        identifiers=extract_identifiers(message),
        host=payload.get("resource_type"),
    )


def _parse_ts_or_now(ts_raw) -> datetime:
    if not ts_raw:
        return datetime.now(timezone.utc)
    timestamp = dateutil_parser.parse(str(ts_raw))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _normalize_oracle(record: RawLogRecord) -> LogEvent:
    payload = record.raw_payload
    message = payload.get("message", "")
    return LogEvent(
        source_system=SourceSystem.ORACLE,
        origin=record.origin,
        timestamp=_parse_ts_or_now(payload.get("timestamp")),
        level=extract_level(message),
        message=message,
        identifiers=extract_identifiers(message),
        host=payload.get("host") or payload.get("module"),
    )


def _normalize_mysql(record: RawLogRecord) -> LogEvent:
    payload = record.raw_payload
    message = payload.get("message", "")
    # performance_schema.error_log PRIO values are System/Warning/Error/etc.,
    # not the TRACE..FATAL vocabulary the other sources use — fold onto the
    # same scale so severity is comparable across systems in the UI.
    prio_map = {"SYSTEM": "INFO", "NOTE": "DEBUG", "WARNING": "WARN", "ERROR": "ERROR"}
    prio = (payload.get("level") or "").upper()
    level = prio_map.get(prio, extract_level(message))
    return LogEvent(
        source_system=SourceSystem.MYSQL,
        origin=record.origin,
        timestamp=_parse_ts_or_now(payload.get("timestamp")),
        level=level,
        message=message,
        identifiers=extract_identifiers(message),
    )


def _normalize_postgres(record: RawLogRecord) -> LogEvent:
    payload = record.raw_payload
    message = payload.get("message", "")
    # Postgres server-log severities (DEBUG1-5/LOG/INFO/NOTICE/WARNING/ERROR/
    # FATAL/PANIC) are a different vocabulary from the TRACE..FATAL scale the
    # other sources use — fold onto the same scale, exactly as MySQL's PRIO
    # values are folded above, so WARNING doesn't diverge from CloudWatch WARN.
    prio_map = {
        "DEBUG5": "DEBUG", "DEBUG4": "DEBUG", "DEBUG3": "DEBUG",
        "DEBUG2": "DEBUG", "DEBUG1": "DEBUG",
        "LOG": "INFO", "INFO": "INFO", "NOTICE": "INFO",
        "WARNING": "WARN", "ERROR": "ERROR",
        "FATAL": "FATAL", "PANIC": "FATAL",
    }
    prio = (payload.get("level") or "").upper()
    level = prio_map.get(prio, extract_level(message))
    return LogEvent(
        source_system=SourceSystem.POSTGRES,
        origin=record.origin,
        timestamp=_parse_ts_or_now(payload.get("timestamp")),
        level=level,
        message=message,
        identifiers=extract_identifiers(message),
        host=f"pid:{payload['pid']}" if payload.get("pid") else None,
    )


_NORMALIZERS = {
    SourceSystem.CLOUDWATCH: _normalize_cloudwatch,
    SourceSystem.TOMCAT: _normalize_tomcat,
    SourceSystem.GCP_LOGGING: _normalize_gcp,
    SourceSystem.ORACLE: _normalize_oracle,
    SourceSystem.MYSQL: _normalize_mysql,
    SourceSystem.POSTGRES: _normalize_postgres,
}


def normalize(records: List[RawLogRecord], start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> List[LogEvent]:
    """Normalize raw records into LogEvents, dropping unparsable lines and
    anything outside [start_time, end_time) for sources (like Tomcat) that
    couldn't be time-filtered at extraction time."""
    events: List[LogEvent] = []
    for record in records:
        normalizer_fn = _NORMALIZERS.get(record.source_system)
        if normalizer_fn is None:
            logger.warning("No normalizer registered for source %s", record.source_system)
            continue
        try:
            event = normalizer_fn(record)
        except Exception as exc:
            logger.warning("Failed to normalize record from %s: %s", record.origin, exc)
            continue
        if event is None:
            continue
        if start_time and event.timestamp < start_time:
            continue
        if end_time and event.timestamp >= end_time:
            continue
        events.append(event)

    events.sort(key=lambda e: e.timestamp)
    logger.info("Normalized %d/%d raw records into LogEvents", len(events), len(records))
    return events
