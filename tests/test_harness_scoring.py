from datetime import datetime, timedelta, timezone

from harness.models import Emits, Expected, ExpectedEdge, ExpectedIncident, PostgresStep, SqlTrigger, TomcatStep, HttpTrigger
from harness.scoring import resolve_anchors, score
from models.schema import CorrelationEdge, LogEvent, RelationType, SourceSystem

BASE_TS = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)


def _event(source_system, message, minute=0, event_id=None):
    kwargs = {}
    if event_id:
        kwargs["event_id"] = event_id
    return LogEvent(
        source_system=source_system,
        origin="test",
        timestamp=BASE_TS + timedelta(minutes=minute),
        message=message,
        **kwargs,
    )


def _pg_step(step_id, message_contains):
    return PostgresStep(
        id=step_id,
        source="postgres",
        sql=SqlTrigger(function="harness.emit_log", args={"p_level": "ERROR", "p_message": message_contains}),
        emits=Emits(source_system="postgres", message_contains=message_contains),
    )


def _tomcat_step(step_id, message_contains):
    return TomcatStep(
        id=step_id,
        source="tomcat",
        http=HttpTrigger(path="/api/orders/scenario", query={}),
        emits=Emits(source_system="tomcat", message_contains=message_contains),
    )


def _edge(source_id, target_id, relation_type=RelationType.SEMANTIC_SIMILARITY, confidence=0.9):
    return CorrelationEdge(
        source_event_id=source_id, target_event_id=target_id, relation_type=relation_type, confidence=confidence
    )


# --- resolve_anchors ---


def test_resolve_anchors_maps_step_to_its_exactly_one_matching_event():
    step = _pg_step("pg-a", "deadlock detected")
    event = _event(SourceSystem.POSTGRES, "deadlock detected on relation orders")
    anchors, unresolved = resolve_anchors([event], [step])

    assert unresolved == []
    assert anchors["pg-a"].event_id == event.event_id


def test_resolve_anchors_marks_zero_matches_as_unresolved():
    step = _pg_step("pg-a", "deadlock detected")
    other_event = _event(SourceSystem.POSTGRES, "completely unrelated message")
    anchors, unresolved = resolve_anchors([other_event], [step])

    assert unresolved == ["pg-a"]
    assert "pg-a" not in anchors


def test_resolve_anchors_marks_multiple_matches_as_unresolved():
    step = _pg_step("pg-a", "deadlock detected")
    dup1 = _event(SourceSystem.POSTGRES, "deadlock detected first")
    dup2 = _event(SourceSystem.POSTGRES, "deadlock detected second")
    anchors, unresolved = resolve_anchors([dup1, dup2], [step])

    assert unresolved == ["pg-a"]
    assert "pg-a" not in anchors


# --- score: precision/recall ---


def test_score_perfect_match_gives_precision_and_recall_of_one():
    pg_event = _event(SourceSystem.POSTGRES, "deadlock detected")
    tomcat_event = _event(SourceSystem.TOMCAT, "PessimisticLockException", minute=1)
    anchors = {"pg-a": pg_event, "tomcat-b": tomcat_event}
    edges = [_edge(pg_event.event_id, tomcat_event.event_id)]
    expected = Expected(
        edges=[ExpectedEdge(**{"from": "pg-a", "to": "tomcat-b", "relation_type": "semantic_similarity", "min_confidence": 0.55})],
        incidents=[ExpectedIncident(members=["pg-a", "tomcat-b"], grouped=True)],
    )

    result = score([pg_event, tomcat_event], edges, anchors, expected)

    assert result.precision == 1.0
    assert result.recall == 1.0
    assert not result.precision_undefined
    assert not result.recall_undefined
    assert result.true_positives == [("pg-a", "tomcat-b")]
    assert result.false_positives == []
    assert result.false_negatives == []


def test_score_false_positive_when_observed_edge_not_in_expected():
    pg_event = _event(SourceSystem.POSTGRES, "unrelated noise a")
    tomcat_event = _event(SourceSystem.TOMCAT, "unrelated noise b", minute=1)
    anchors = {"pg-a": pg_event, "tomcat-b": tomcat_event}
    edges = [_edge(pg_event.event_id, tomcat_event.event_id)]
    expected = Expected(edges=[], incidents=[])  # nothing expected to link

    result = score([pg_event, tomcat_event], edges, anchors, expected)

    assert result.false_positives == [("pg-a", "tomcat-b")]
    assert result.precision == 0.0
    assert result.recall_undefined  # 0/0 — nothing was expected


def test_score_false_negative_when_expected_edge_is_missing():
    pg_event = _event(SourceSystem.POSTGRES, "deadlock detected")
    tomcat_event = _event(SourceSystem.TOMCAT, "PessimisticLockException", minute=1)
    anchors = {"pg-a": pg_event, "tomcat-b": tomcat_event}
    edges = []  # LLM found nothing this run
    expected = Expected(
        edges=[ExpectedEdge(**{"from": "pg-a", "to": "tomcat-b", "relation_type": "semantic_similarity", "min_confidence": 0.55})],
        incidents=[],
    )

    result = score([pg_event, tomcat_event], edges, anchors, expected)

    assert result.false_negatives == [("pg-a", "tomcat-b")]
    assert result.recall == 0.0
    assert result.precision_undefined  # 0/0 — nothing was observed


def test_score_flags_stage_mismatch_when_relation_type_differs_from_expected():
    pg_event = _event(SourceSystem.POSTGRES, "shared error_code event")
    tomcat_event = _event(SourceSystem.TOMCAT, "shared error_code event 2", minute=1)
    anchors = {"pg-a": pg_event, "tomcat-b": tomcat_event}
    # Observed as a deterministic id_match, but expected semantic_similarity.
    edges = [_edge(pg_event.event_id, tomcat_event.event_id, relation_type=RelationType.ID_MATCH, confidence=1.0)]
    expected = Expected(
        edges=[ExpectedEdge(**{"from": "pg-a", "to": "tomcat-b", "relation_type": "semantic_similarity", "min_confidence": 0.55})],
        incidents=[],
    )

    result = score([pg_event, tomcat_event], edges, anchors, expected)

    assert result.true_positives == [("pg-a", "tomcat-b")]  # pair matched...
    assert result.stage_mismatches == [("pg-a", "tomcat-b")]  # ...but relation_type didn't


def test_score_reports_contamination_for_edges_with_exactly_one_anchor_endpoint():
    pg_event = _event(SourceSystem.POSTGRES, "anchor event")
    noise_event = _event(SourceSystem.TOMCAT, "background noise", minute=1)
    anchors = {"pg-a": pg_event}  # noise_event is NOT an anchor
    edges = [_edge(pg_event.event_id, noise_event.event_id)]
    expected = Expected(edges=[], incidents=[])

    result = score([pg_event, noise_event], edges, anchors, expected)

    assert len(result.contamination) == 1
    assert result.contamination[0][0] == pg_event.event_id
    # A contaminated edge must NOT also count as a scored false positive
    # (ground truth only covers the anchor set).
    assert result.false_positives == []


def test_score_incident_grouped_true_when_all_members_share_one_component():
    a = _event(SourceSystem.POSTGRES, "a")
    b = _event(SourceSystem.TOMCAT, "b", minute=1)
    c = _event(SourceSystem.POSTGRES, "c", minute=2)
    anchors = {"a": a, "b": b, "c": c}
    edges = [_edge(a.event_id, b.event_id), _edge(b.event_id, c.event_id)]
    expected = Expected(edges=[], incidents=[ExpectedIncident(members=["a", "b", "c"], grouped=True)])

    result = score([a, b, c], edges, anchors, expected)

    assert len(result.incidents) == 1
    assert result.incidents[0].actual_grouped is True
    assert result.incidents[0].component_size == 3


def test_score_incident_grouped_false_when_members_land_in_different_components():
    a = _event(SourceSystem.POSTGRES, "a")
    b = _event(SourceSystem.TOMCAT, "b", minute=1)
    anchors = {"a": a, "b": b}
    edges = []  # no edge at all — a and b end up isolated
    expected = Expected(edges=[], incidents=[ExpectedIncident(members=["a", "b"], grouped=True)])

    result = score([a, b], edges, anchors, expected)

    assert result.incidents[0].actual_grouped is False


def test_score_singleton_incident_is_actually_grouped_false_when_truly_isolated():
    """Regression: a 1-member expected incident (grouped=False, asserting
    'this event must stay isolated') must reflect whether the event's REAL
    connected component has size 1 — not trivially report grouped=True just
    because a single-element set always 'shares one component with itself'."""
    isolated = _event(SourceSystem.TOMCAT, "isolated noise")
    anchors = {"solo": isolated}
    edges = []  # no edges at all — isolated has no partner
    expected = Expected(edges=[], incidents=[ExpectedIncident(members=["solo"], grouped=False)])

    result = score([isolated], edges, anchors, expected)

    assert result.incidents[0].actual_grouped is False
    assert result.incidents[0].component_size == 1


def test_score_singleton_incident_is_grouped_true_when_contaminated_by_noise():
    """The same singleton check must flip to grouped=True when the 'lone'
    event actually DID end up linked to something else (contamination) —
    proving the check inspects real component size, not just set identity."""
    solo = _event(SourceSystem.TOMCAT, "solo")
    noise = _event(SourceSystem.POSTGRES, "some noise event", minute=1)
    anchors = {"solo": solo}  # noise is NOT an anchor, just contamination
    edges = [_edge(solo.event_id, noise.event_id)]
    expected = Expected(edges=[], incidents=[ExpectedIncident(members=["solo"], grouped=False)])

    result = score([solo, noise], edges, anchors, expected)

    assert result.incidents[0].actual_grouped is True
    assert result.incidents[0].component_size == 2


def test_score_reports_forbidden_edge_observed_when_it_appears():
    """expected.forbidden_edges asserts a pair must NOT link — score() must
    surface it when the pipeline links it anyway, not silently ignore it."""
    pg_event = _event(SourceSystem.POSTGRES, "would-be-semantic-partner source")
    tomcat_event = _event(SourceSystem.TOMCAT, "would-be-semantic-partner target", minute=1)
    anchors = {"pg-a": pg_event, "tomcat-b": tomcat_event}
    edges = [_edge(pg_event.event_id, tomcat_event.event_id)]  # forbidden pair DID link
    expected = Expected(
        edges=[],
        forbidden_edges=[ExpectedEdge(**{"from": "pg-a", "to": "tomcat-b", "relation_type": "semantic_similarity", "min_confidence": 0.0})],
        incidents=[],
    )

    result = score([pg_event, tomcat_event], edges, anchors, expected)

    assert result.forbidden_edges_observed == [("pg-a", "tomcat-b")]


def test_score_forbidden_edges_empty_when_forbidden_pair_never_links():
    pg_event = _event(SourceSystem.POSTGRES, "a")
    tomcat_event = _event(SourceSystem.TOMCAT, "b", minute=1)
    anchors = {"pg-a": pg_event, "tomcat-b": tomcat_event}
    edges = []  # forbidden pair correctly never linked
    expected = Expected(
        edges=[],
        forbidden_edges=[ExpectedEdge(**{"from": "pg-a", "to": "tomcat-b", "relation_type": "semantic_similarity", "min_confidence": 0.0})],
        incidents=[],
    )

    result = score([pg_event, tomcat_event], edges, anchors, expected)

    assert result.forbidden_edges_observed == []
