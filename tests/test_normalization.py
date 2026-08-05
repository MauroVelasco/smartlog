from datetime import datetime, timezone

from models.schema import RawLogRecord, SourceSystem
from normalization.normalizer import extract_identifiers, extract_level, normalize


def test_extract_identifiers_finds_request_and_trace_id():
    text = "ERROR request_id=abc12345 trace_id=xyz98765 failed to process order"
    ids = extract_identifiers(text)
    assert ids["request_id"] == "abc12345"
    assert ids["trace_id"] == "xyz98765"


def test_extract_level_picks_up_error():
    assert extract_level("2026-08-03 ERROR NullPointerException") == "ERROR"
    assert extract_level("just a plain message") is None


def test_normalize_cloudwatch_record():
    ts = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
    record = RawLogRecord(
        source_system=SourceSystem.CLOUDWATCH,
        origin="/ecs/app-service:stream-1",
        raw_payload={
            "message": "ERROR request_id=req-000111222 NullPointerException in OrderService",
            "timestamp_ms": int(ts.timestamp() * 1000),
            "log_stream_name": "stream-1",
        },
    )
    events = normalize([record])
    assert len(events) == 1
    event = events[0]
    assert event.source_system == SourceSystem.CLOUDWATCH.value
    assert event.level == "ERROR"
    assert event.identifiers["request_id"] == "req-000111222"
    assert event.timestamp == ts


def test_normalize_filters_outside_time_window():
    ts = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
    record = RawLogRecord(
        source_system=SourceSystem.CLOUDWATCH,
        origin="/ecs/app-service:stream-1",
        raw_payload={"message": "INFO hello", "timestamp_ms": int(ts.timestamp() * 1000)},
    )
    events = normalize(
        [record],
        start_time=datetime(2026, 8, 3, 13, 0, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 8, 3, 14, 0, 0, tzinfo=timezone.utc),
    )
    assert events == []
