import json
from pathlib import Path

import pytest

from harness.loader import ScenarioValidationError, load_case, load_directory

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"


def _write_case(tmp_path, data):
    path = tmp_path / f"{data['case_id']}.json"
    path.write_text(json.dumps(data))
    return path


def _base_case(**overrides):
    case = {
        "case_id": "t2-example",
        "tier": 2,
        "outcome_class": "value",
        "title": "example",
        "identifier_free": True,
        "gated_by_phase3": True,
        "expected_stage": "semantic",
        "use_llm": True,
        "steps": [
            {
                "id": "pg-step",
                "source": "postgres",
                "wait_ms_before": 0,
                "sql": {
                    "function": "harness.emit_log",
                    "args": {"p_level": "ERROR", "p_message": "deadlock detected", "p_identifier_free": True},
                },
                "emits": {"source_system": "postgres", "message_contains": "deadlock detected"},
            },
            {
                "id": "tomcat-step",
                "source": "tomcat",
                "wait_ms_before": 500,
                "http": {"path": "/api/orders/scenario", "query": {"name": "pessimistic-lock"}},
                "emits": {"source_system": "tomcat", "message_contains": "PessimisticLockException"},
            },
        ],
        "expected": {
            "edges": [{"from": "pg-step", "to": "tomcat-step", "relation_type": "semantic_similarity", "min_confidence": 0.55}],
            "forbidden_edges": [],
            "incidents": [{"members": ["pg-step", "tomcat-step"], "grouped": True}],
        },
    }
    case.update(overrides)
    return case


def test_load_case_accepts_a_clean_identifier_free_case(tmp_path):
    path = _write_case(tmp_path, _base_case())
    case = load_case(path)
    assert case.case_id == "t2-example"
    assert len(case.steps) == 2


def test_load_case_rejects_a_leaking_tier2_case(tmp_path):
    leaking = _base_case()
    # Accidentally leaks a regex-matchable identifier token inside the
    # authored narrative text, exactly the mistake the lint exists to catch.
    leaking["steps"][0]["sql"]["args"]["p_message"] = "deadlock detected status: 500 while updating orders"
    leaking["steps"][0]["emits"]["message_contains"] = "status: 500"
    path = _write_case(tmp_path, leaking)

    with pytest.raises(ScenarioValidationError, match="identifier"):
        load_case(path)


def test_load_case_defaults_edge_scoring_to_exact(tmp_path):
    path = _write_case(tmp_path, _base_case())
    case = load_case(path)
    assert case.edge_scoring == "exact"


def test_load_case_accepts_incident_only_edge_scoring(tmp_path):
    path = _write_case(tmp_path, _base_case(edge_scoring="incident_only"))
    case = load_case(path)
    assert case.edge_scoring == "incident_only"


def test_load_case_rejects_duplicate_step_ids(tmp_path):
    dup = _base_case()
    dup["steps"][1]["id"] = "pg-step"  # collides with steps[0]
    path = _write_case(tmp_path, dup)

    with pytest.raises(ScenarioValidationError, match="duplicate"):
        load_case(path)


# --- real scenarios/ directory: new lexical-trap cases (Fix 1) ---

TRAP_CASE_IDS = [
    "t2-trap-webhook-timeout-vs-vacuum-timeout",
    "t2-trap-cart-lock-vs-stats-lock",
    "t2-trap-email-retry-vs-replication-retry",
]


def test_load_directory_loads_the_new_trap_cases_cleanly():
    cases = load_directory(SCENARIOS_DIR)
    cases_by_id = {c.case_id: c for c in cases}

    for case_id in TRAP_CASE_IDS:
        assert case_id in cases_by_id, f"missing scenario file for {case_id}"


@pytest.mark.parametrize("case_id", TRAP_CASE_IDS)
def test_trap_case_asserts_no_link_via_forbidden_edges_and_singleton_incidents(case_id):
    cases = load_directory(SCENARIOS_DIR)
    case = next(c for c in cases if c.case_id == case_id)

    assert case.expected.edges == []
    assert len(case.expected.forbidden_edges) == 1
    assert len(case.steps) == 2
    step_ids = {step.id for step in case.steps}
    sources = {step.source for step in case.steps}
    assert sources == {"tomcat", "postgres"}, "trap cases must be cross-source"

    forbidden = case.expected.forbidden_edges[0]
    assert {forbidden.from_step, forbidden.to_step} == step_ids

    assert len(case.expected.incidents) == 2
    for incident in case.expected.incidents:
        assert incident.grouped is False
        assert len(incident.members) == 1
