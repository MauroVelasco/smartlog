import json

import pytest

from harness.loader import ScenarioValidationError, load_case


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


def test_load_case_rejects_duplicate_step_ids(tmp_path):
    dup = _base_case()
    dup["steps"][1]["id"] = "pg-step"  # collides with steps[0]
    path = _write_case(tmp_path, dup)

    with pytest.raises(ScenarioValidationError, match="duplicate"):
        load_case(path)
