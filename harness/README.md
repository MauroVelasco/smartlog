# harness/

The `postgres-scenario-harness` correlation harness — a local reporting
tool that drives Tomcat + Postgres through a scenario catalog
(`scenarios/*.json`), runs the real `correlation.pipeline.run_correlation()`
pipeline, and scores the result against hidden ground truth. It is **not**
a CI gate: every run exits `0` by default regardless of case scores.

## Architecture

```
harness/
  models.py     Pydantic ScenarioCase / Step / Emits / Expected schema
  loader.py     load + validate scenario JSON, identifier lint
  gate.py       Phase 3 zero-deterministic-edges gate (shared by cli.py and its pytest check)
  triggers.py   TomcatTrigger (urllib), PostgresTrigger (psycopg2, autocommit), CloudWatchTrigger (no-op)
  collector.py  poll-until-anchors-resolve + settle pass, case-isolated by start_time
  observer.py   RecordingObserver(SemanticObserver) — records skips/raw results/errors
  scoring.py    anchor resolution, precision/recall, contamination, incident grouping
  report.py     plain-text report + exit-code policy
  cli.py        python -m harness.cli — wires it all together
```

See `scenarios/README.md` for the JSON schema and the full 13-case catalog.

## Running the harness

Prerequisites: `docker compose up -d` (postgres + tomcat) from the repo
root, with `harness.emit_log()` installed (`postgres-log-source/README.md`)
and `.env` pointing `TOMCAT_LOG_PATHS`/`DATABASE_URL_APP` at the local
containers.

```bash
# Full catalog
python -m harness.cli --cases scenarios/

# One case
python -m harness.cli --cases scenarios/ --case t1-shared-trx-tomcat-postgres

# Skip all LLM calls (forces use_llm=False everywhere — useful for a fast
# structural/plumbing check without touching the semantic stage at all)
python -m harness.cli --cases scenarios/ --no-llm

# Write a JSON summary alongside the text report
python -m harness.cli --cases scenarios/ --json-out /tmp/harness-report.json

# Opt into a non-zero exit code for infra failures (ERRORED/TIMEOUT only —
# never for a low-scoring PASS/FAIL/REPRODUCED/NOT_REPRODUCED/UNRESOLVED case)
python -m harness.cli --cases scenarios/ --fail-on-error
```

Requires a working `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY` +
`LLM_PROVIDER=openai`) in the environment for any case with `use_llm: true`
(all `t2-*` cases and most `doc-*` cases) to actually reach a scored
semantic result — see "Known environmental gap" below if neither is set.

### The Phase 3 gate auto-reruns

Before running any case whose `gated_by_phase3` field is `true`, the CLI
automatically re-runs the same zero-deterministic-edges gate check used to
originally unblock Tier 2 authoring (`tests/test_zero_deterministic_edges_gate.py`,
sharing its implementation with `harness/gate.py`). If it fails or the
dependencies are unreachable, gated cases still run and score (the harness
reports, it does not gate) but are flagged in the report:

```
** UNTRUSTWORTHY: Phase 3 zero-deterministic-edges gate has not passed this run **
```

Use `--skip-gate-check` to bypass the auto-rerun (e.g. if you already know
the gate is green and want a faster iteration loop).

### Case statuses

`PASS | FAIL | REPRODUCED | NOT_REPRODUCED | ERRORED | UNRESOLVED | TIMEOUT`

- `PASS`/`FAIL` — `outcome_class: "value"` or `"positive-control"` cases,
  scored against `expected`.
- `REPRODUCED`/`NOT_REPRODUCED` — `outcome_class: "documented-limitation"`
  cases (the `doc-*` catalog) — these assert a known pipeline behavior
  reproduces, not a pass/fail judgment.
- `ERRORED` — the semantic stage's LLM call itself failed (see
  `correlation/langchain_agents.py`'s `SemanticObserver.on_error`) —
  distinct from a case that legitimately scored zero links.
- `UNRESOLVED` — an `emits` selector matched 0 or 2+ events; the harness
  refuses to guess which one is "the" anchor.
- `TIMEOUT` — one or more anchors never landed within the poll timeout.

## Known limitation: shared `error_code` deterministic false-link

Full writeup in `scenarios/README.md`. Short version: `correlation/deterministic.py`
links any two events sharing an identifier value — including `error_code`/`status`
— within `DETERMINISTIC_TIME_WINDOW_SECONDS`, at confidence 1.0, regardless of
whether the events are actually related. `doc-error-code-false-link` reproduces
this deliberately and asserts it as the *expected*, intended outcome — this
harness does not test against a "must not link" version of this behavior,
because that would contradict how the deterministic stage is designed to work.

One practical live-run consequence worth knowing: `/api/orders/db-error`
(used by both `t1-shared-trx-tomcat-postgres` and `doc-error-code-false-link`)
unconditionally stamps `error_code=DB_TIMEOUT` server-side. If those two
cases — or repeated runs of the same case — execute within 300 seconds of
each other, their `error_code`-bearing events will cross-link and show up
as `contamination` in each other's report. This never corrupts
precision/recall (which are scored over the anchor set only), and is a
faithful demonstration of the `contamination` metric doing its job, not a
harness defect.

## Known environmental gap (as of this apply batch)

`t2-*` cases and most `doc-*` cases require a live, successful LLM call to
be meaningfully scored (`expected_stage: "semantic"` or `"mixed"`). In the
environment this harness was built and verified in, neither
`ANTHROPIC_API_KEY` nor `OPENAI_API_KEY` was configured, so every such case
correctly reported `ERRORED` (a genuine "Could not resolve authentication
method" failure, caught by the `SemanticObserver.on_error` hook exactly as
designed — a real demonstration of the LLM-failure-distinguishability
requirement, just not the "successfully reaches the LLM and scores a real
semantic link" one). `t1-shared-trx-tomcat-postgres` (deterministic-only)
and `doc-error-code-false-link`/`doc-single-source-bucket-skipped`/
`doc-hybrid-component-merge` (which either need no LLM call or correctly
never trigger one) were fully verified end-to-end, including a fix for a
genuine incident-grouping scoring bug found during that verification (see
apply-progress for detail). To complete verification of the semantic path,
run with a real key configured:

```bash
ANTHROPIC_API_KEY=sk-... python -m harness.cli --cases scenarios/
```
