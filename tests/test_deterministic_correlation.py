from datetime import datetime, timedelta, timezone

from correlation.deterministic import deterministic_correlate
from models.schema import LogEvent, SourceSystem

BASE = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)


def make_event(source, offset_seconds, identifiers, message="err"):
    return LogEvent(
        source_system=source,
        origin="test",
        timestamp=BASE + timedelta(seconds=offset_seconds),
        message=message,
        identifiers=identifiers,
    )


def test_links_events_sharing_request_id_within_window():
    events = [
        make_event(SourceSystem.TOMCAT, 0, {"request_id": "req-1"}),
        make_event(SourceSystem.CLOUDWATCH, 30, {"request_id": "req-1"}),
    ]
    edges, linked = deterministic_correlate(events)
    assert len(edges) == 1
    assert edges[0].relation_type == "id_match"
    assert edges[0].matched_on == "request_id"
    assert linked == {events[0].event_id, events[1].event_id}


def test_does_not_link_events_outside_time_window():
    events = [
        make_event(SourceSystem.TOMCAT, 0, {"request_id": "req-1"}),
        make_event(SourceSystem.CLOUDWATCH, 10_000, {"request_id": "req-1"}),
    ]
    edges, linked = deterministic_correlate(events)
    assert edges == []
    assert linked == set()


def test_does_not_link_events_with_no_shared_identifiers():
    events = [
        make_event(SourceSystem.TOMCAT, 0, {"request_id": "req-1"}),
        make_event(SourceSystem.CLOUDWATCH, 5, {"request_id": "req-2"}),
    ]
    edges, linked = deterministic_correlate(events)
    assert edges == []
    assert linked == set()


def test_three_way_link_on_shared_trace_id():
    events = [
        make_event(SourceSystem.TOMCAT, 0, {"trace_id": "t-1"}),
        make_event(SourceSystem.CLOUDWATCH, 5, {"trace_id": "t-1"}),
        make_event(SourceSystem.POSTGRES, 10, {"trace_id": "t-1"}),
    ]
    edges, linked = deterministic_correlate(events)
    assert len(edges) == 3  # fully connected triangle
    assert len(linked) == 3
