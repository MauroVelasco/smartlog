from datetime import datetime, timezone

from models.schema import RawLogRecord, SourceSystem
from normalization.normalizer import normalize


def _pg_record(level: str, message: str = "background writer process") -> RawLogRecord:
    ts = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
    return RawLogRecord(
        source_system=SourceSystem.POSTGRES,
        origin="postgres:app",
        raw_payload={
            "timestamp": ts.isoformat(),
            "level": level,
            "pid": "4210",
            "message": message,
        },
    )


def test_normalize_postgres_warning_maps_to_warn():
    events = normalize([_pg_record("WARNING")])
    assert len(events) == 1
    assert events[0].level == "WARN"


def test_normalize_postgres_info_and_error_pass_through_unchanged():
    info_events = normalize([_pg_record("INFO")])
    error_events = normalize([_pg_record("ERROR")])
    assert info_events[0].level == "INFO"
    assert error_events[0].level == "ERROR"


def test_normalize_postgres_notice_maps_to_info_like_mysql_system():
    events = normalize([_pg_record("NOTICE")])
    assert events[0].level == "INFO"


def test_normalize_postgres_unrecognized_level_falls_back_to_extract_level():
    events = normalize([_pg_record("CONTEXT", message="PL/pgSQL function harness.emit_log(...) SEVERE failure")])
    assert events[0].level == "SEVERE"
