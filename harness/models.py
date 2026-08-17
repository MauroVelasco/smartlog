"""
Scenario JSON schema (postgres-scenario-harness, design Decision 4).

A ScenarioCase expresses, per case: one or more per-source triggers
(Tomcat/Postgres are live-triggerable; CloudWatch is description-only,
mode="manual", never auto-triggered — see harness/triggers.py), a step id
per trigger that `expected.edges`/`expected.incidents` reference (NEVER
event_ids, which are UUIDs minted at normalize time and unknowable at
authoring time), and a hidden `expected` block the harness scores against
— never read back out of generated log text (design Decision 2).

Discriminated on `source` via Pydantic's tagged union so a malformed step
(e.g. an `http` block on a `postgres` source) fails fast at load time
instead of silently no-op'ing.
"""
from __future__ import annotations

from typing import Annotated, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class Emits(BaseModel):
    """Names which collected event a step's trigger is expected to produce.
    The harness resolves this against real extracted+normalized events at
    run time and requires EXACTLY ONE match — 0 or 2+ is UNRESOLVED, never
    a silent pass (design: "Step -> event resolution")."""

    source_system: Literal["tomcat", "postgres", "cloudwatch"]
    message_contains: str


class HttpTrigger(BaseModel):
    """Tomcat trigger descriptor — fired via harness/triggers.py's
    TomcatTrigger (urllib GET)."""

    path: str
    query: Dict[str, str] = Field(default_factory=dict)


class SqlTrigger(BaseModel):
    """Postgres trigger descriptor — fired via harness/triggers.py's
    PostgresTrigger, which invokes harness.emit_log() with these args
    (postgres-log-source/trigger.py's emit_log() contract)."""

    function: Literal["harness.emit_log"]
    args: Dict[str, object]


class TomcatStep(BaseModel):
    id: str
    source: Literal["tomcat"]
    wait_ms_before: int = 0
    http: HttpTrigger
    emits: Emits


class PostgresStep(BaseModel):
    id: str
    source: Literal["postgres"]
    wait_ms_before: int = 0
    sql: SqlTrigger
    emits: Emits


class CloudWatchStep(BaseModel):
    """Description-only — the harness neither triggers nor scores this
    step (spec: "CloudWatch is describable but never triggered"). `emits`
    is always null; `env` documents the generator config this step
    represents for a human reader / a separate verification loop."""

    id: str
    source: Literal["cloudwatch"]
    mode: Literal["manual"] = "manual"
    env: Dict[str, str] = Field(default_factory=dict)
    emits: None = None
    note: Optional[str] = None


Step = Annotated[Union[TomcatStep, PostgresStep, CloudWatchStep], Field(discriminator="source")]


class ExpectedEdge(BaseModel):
    """References step ids (`from_step`/`to_step`), never event_ids —
    event_ids don't exist until normalize() runs at harness time."""

    from_step: str = Field(alias="from")
    to_step: str = Field(alias="to")
    relation_type: Literal["id_match", "semantic_similarity"]
    min_confidence: float = 1.0

    model_config = {"populate_by_name": True}


class ExpectedIncident(BaseModel):
    """A connected_components grouping the harness's scoring must observe.
    `grouped=True` cases assert every member lands in the same component —
    including singleton (unlinked) incidents some cases deliberately mark
    as excluded from precision/recall (see scoring.py)."""

    members: List[str]
    grouped: bool = True


class Expected(BaseModel):
    """The hidden ground truth block — the harness's scoring compares
    ONLY against this, never against log text (design Decision 2)."""

    edges: List[ExpectedEdge] = Field(default_factory=list)
    forbidden_edges: List[ExpectedEdge] = Field(default_factory=list)
    incidents: List[ExpectedIncident] = Field(default_factory=list)


class ScenarioCase(BaseModel):
    case_id: str
    tier: Union[int, Literal["doc"]]
    outcome_class: Literal["positive-control", "value", "documented-limitation"]
    title: str
    identifier_free: bool
    # Explicit rather than inferred from `identifier_free`: most cases are
    # uniformly identifier-free or not, but doc-hybrid-component-merge is a
    # MIXED case (2 default-mode steps + 1 identifier-free step) where the
    # case-wide `identifier_free` toggle doesn't capture gating status.
    # Per tasks.md Phase 3: True for all t2-* and 3 of the 4 doc-* cases;
    # False for t1-* and doc-error-code-false-link (deterministic-only, no
    # identifier-free dependency).
    gated_by_phase3: bool
    expected_stage: Literal["deterministic", "semantic", "none", "mixed"]
    use_llm: bool
    steps: List[Step]
    expected: Expected
