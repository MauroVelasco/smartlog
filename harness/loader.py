"""
Load + validate scenario JSON cases (postgres-scenario-harness, design
Decision 4's "Loader lint").

Two checks beyond Pydantic schema validation:
  1. Step-id uniqueness within a case — `expected.edges`/`expected.incidents`
     reference step ids, so a duplicate id makes ground truth ambiguous.
  2. Identifier lint — for every `identifier_free: true` case, runs the
     PRODUCTION `normalization.normalizer.extract_identifiers()` over each
     step's rendered narrative text. Any hit fails the case AT LOAD TIME,
     before it's ever triggered — this is the mechanized form of the
     zero-deterministic-edges gate (Phase 3), catching accidental
     `status:`/`uid`/`svc` substrings inside authored Tier 2 narratives
     before they can corrupt a scored run.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from normalization.normalizer import extract_identifiers

from harness.models import PostgresStep, ScenarioCase, Step, TomcatStep


class ScenarioValidationError(Exception):
    """A scenario JSON file failed load-time validation (schema, duplicate
    step ids, or the identifier-free lint)."""


def _rendered_text(step: Step) -> Optional[str]:
    """The narrative text a lint should inspect for this step, or None if
    the step has no authored text to check (e.g. a CloudWatch manual step,
    which the harness never triggers or scores)."""
    if isinstance(step, PostgresStep):
        message = step.sql.args.get("p_message")
        return str(message) if message is not None else None
    if isinstance(step, TomcatStep):
        return step.emits.message_contains
    return None


def _validate_unique_step_ids(case: ScenarioCase) -> None:
    ids = [step.id for step in case.steps]
    seen = set()
    duplicates = set()
    for step_id in ids:
        if step_id in seen:
            duplicates.add(step_id)
        seen.add(step_id)
    if duplicates:
        raise ScenarioValidationError(
            f"{case.case_id}: duplicate step ids {sorted(duplicates)} — "
            "expected.edges/incidents reference step ids and cannot be unambiguous with duplicates"
        )


def _lint_identifier_free(case: ScenarioCase) -> None:
    if not case.identifier_free:
        return
    for step in case.steps:
        text = _rendered_text(step)
        if not text:
            continue
        found = extract_identifiers(text)
        if found:
            raise ScenarioValidationError(
                f"{case.case_id}: step '{step.id}' is identifier_free but its rendered text "
                f"leaks regex-matchable identifier(s) {sorted(found)}: {text!r}"
            )


def load_case(path: Path) -> ScenarioCase:
    """Load and fully validate a single scenario JSON file. Raises
    ScenarioValidationError (schema, duplicate ids, or identifier leak) —
    never returns a case that shouldn't be trusted."""
    path = Path(path)
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ScenarioValidationError(f"{path}: invalid JSON — {exc}") from exc

    try:
        case = ScenarioCase.model_validate(data)
    except Exception as exc:  # pydantic.ValidationError, kept generic to avoid a hard pydantic-error dependency here
        raise ScenarioValidationError(f"{path}: schema validation failed — {exc}") from exc

    _validate_unique_step_ids(case)
    _lint_identifier_free(case)
    return case


def load_directory(directory: Path) -> List[ScenarioCase]:
    """Load every `*.json` file in a directory (non-recursive), sorted by
    filename for deterministic run order."""
    directory = Path(directory)
    cases = []
    for path in sorted(directory.glob("*.json")):
        cases.append(load_case(path))
    return cases
