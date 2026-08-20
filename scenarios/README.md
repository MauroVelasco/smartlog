# scenarios/

JSON case catalog for the `postgres-scenario-harness` correlation harness
(`harness/`). Each file is one `ScenarioCase` (`harness/models.py`), loaded
and validated by `harness/loader.py` before it's ever triggered.

## Schema

```jsonc
{
  "case_id": "t2-example",                 // unique, matches the filename stem
  "tier": 1,                                // 1 | 2 | "doc"
  "outcome_class": "positive-control",      // "positive-control" | "value" | "documented-limitation"
  "title": "human-readable one-liner",
  "identifier_free": true,                  // case-wide toggle passed to every step's generator
  "gated_by_phase3": true,                  // true if this case depends on the zero-deterministic-edges gate (Phase 3)
  "expected_stage": "semantic",             // "deterministic" | "semantic" | "none" | "mixed"
  "use_llm": true,                          // whether the harness calls run_correlation(..., use_llm=...)
  "edge_scoring": "exact",                  // optional, default "exact"; see "edge_scoring" below
  "steps": [ /* Step, discriminated on "source" */ ],
  "expected": { /* hidden ground truth — see below */ }
}
```

### `edge_scoring` (optional, default `"exact"`)

Most cases should leave this unset — the default `"exact"` behavior scores
`false_positives` as a strict set difference against `expected.edges`,
which is exactly what should catch a real false link. Transitive-chain
cases (A-B + B-C both expected, all three in one incident) are an
exception: the pipeline correctly grouping all three members can also
produce a valid-but-non-minimal direct A-C edge, which `"exact"` would
wrongly count as a false positive. `"incident_only"` relaxes this: an edge
between two anchors that are BOTH already correctly members of the same
expected `grouped: true` incident is not counted as a false positive.
`forbidden_edges` is unaffected either way — a pair explicitly asserted as
"must not link" still fails the case under `"incident_only"` too. Only
`t2-three-hop-chain` sets this today.

### Steps (discriminated on `source`)

- **`tomcat`**: `{ id, source: "tomcat", wait_ms_before, http: { path, query }, emits }`
  — fired via `harness/triggers.py`'s `TomcatTrigger` (a plain HTTP GET).
- **`postgres`**: `{ id, source: "postgres", wait_ms_before, sql: { function: "harness.emit_log", args }, emits }`
  — fired via `harness/triggers.py`'s `PostgresTrigger`, which calls
  `postgres-log-source/trigger.py`'s `emit_log()` with `args` verbatim.
- **`cloudwatch`**: `{ id, source: "cloudwatch", mode: "manual", env, emits: null, note }`
  — **description-only**. The harness never triggers or scores this step
  (CloudWatch's `@Scheduled` tick model is incompatible with this
  synchronous trigger→wait→run→compare loop). `env` documents the generator
  config the step represents, for a human reader or a separate
  verification loop.

`gated_by_phase3` is explicit rather than inferred from `identifier_free`:
most cases are uniformly identifier-free or not, but
`doc-hybrid-component-merge` is a MIXED case (2 default-mode steps + 1
identifier-free step) where a single case-wide `identifier_free` toggle
can't capture gating status on its own.

`emits: { source_system, message_contains }` names which collected event a
step's trigger is expected to produce. The harness resolves this against
real extracted+normalized events at run time and requires **exactly one**
match — 0 or 2+ matches is `UNRESOLVED`, never a silent pass.

### `expected` (hidden ground truth)

```jsonc
{
  "edges": [ { "from": "step-id", "to": "step-id", "relation_type": "id_match" | "semantic_similarity", "min_confidence": 1.0 } ],
  "forbidden_edges": [ /* same shape — asserts these must NOT appear, or appear only below threshold */ ],
  "incidents": [ { "members": ["step-id", ...], "grouped": true | false } ]
}
```

`edges`/`incidents` reference **step ids**, never `event_id`s — event_ids
are UUIDs minted at normalize time and unknowable when a case is authored.
The harness resolves step ids to real event_ids via `emits` matching, then
scores `run_correlation()`'s output against this block. **Ground truth is
never read back out of generated log text** (no parsing of `correlated=`
or `mdc.correlated`) — see the harness design's Decision 2 for why.

`incidents` with `grouped: false` mark expected **singleton** incidents
(isolated events with no correlation partner) — `nx.connected_components`
naturally produces 1-node components for unlinked events, and these are
explicitly excluded from precision/recall scoring, not counted as misses.

## Case catalog (16 cases)

| case_id | Tier | Gated by Phase 3? | Asserts |
|---|---|---|---|
| `t1-shared-trx-tomcat-postgres` | 1 | No (deterministic-only) | Shared `trxId` links Tomcat+Postgres at confidence 1.0 |
| `t2-pool-exhaustion` | 2 | Yes | Postgres connection-slot exhaustion ↔ Tomcat pool checkout timeout |
| `t2-deadlock-vs-lock-exception` | 2 | Yes | SQL deadlock ↔ Java `PessimisticLockException` |
| `t2-disk-full-vs-write-failure` | 2 | Yes | Postgres disk-full ↔ Tomcat order-persist failure |
| `t2-slow-query-vs-gateway-timeout` | 2 | Yes | Postgres long-running statement ↔ Tomcat upstream read timeout |
| `t2-constraint-violation-vs-validation` | 2 | Yes | Postgres unique-constraint violation ↔ Tomcat validation rejection |
| `t2-restart-vs-connection-reset` | 2 | Yes | Postgres crash-recovery narrative ↔ Tomcat connection reset |
| `t2-negative-unrelated` | 2 | Yes | **Precision guard**: two unrelated, low-overlap events must NOT link |
| `t2-trap-webhook-timeout-vs-vacuum-timeout` | 2 | Yes | **Lexical trap**: "timeout"/"retry" overlap, webhook delivery vs autovacuum — must NOT link |
| `t2-trap-cart-lock-vs-stats-lock` | 2 | Yes | **Lexical trap**: "lock" overlap, cart concurrency vs stats-refresh scheduling — must NOT link |
| `t2-trap-email-retry-vs-replication-retry` | 2 | Yes | **Lexical trap**: "failed"/"retry" overlap, email delivery vs DB replication — must NOT link |
| `t2-three-hop-chain` | 2 | Yes | A(pg)-B(tomcat)-C(pg): A-B + B-C merge into one 3-member incident (`edge_scoring: "incident_only"`) |
| `doc-single-source-bucket-skipped` | doc | Yes | A single-source-system bucket is never sent to the LLM (`langchain_agents.py:135`) |
| `doc-batch-split-unlinkable` | doc | Yes | A real pair straddling the 25-event chunk boundary can never link |
| `doc-error-code-false-link` | doc | **No** (deterministic-only) | Shared `error_code=DB_TIMEOUT` links two unrelated events at 1.0 — **intended**, see below |
| `doc-hybrid-component-merge` | doc | Yes | Deterministic edge removes one member of a would-be semantic pair — see below |

### Lexical traps vs `t2-negative-unrelated`

`t2-negative-unrelated` is both low-vocabulary-overlap AND unrelated —
it can't test whether the LLM resists surface pattern-matching, because
there's no tempting overlap to resist. The `t2-trap-*` cases are the
opposite construction: deliberately HIGH surface vocabulary overlap
between a Tomcat and a Postgres event that are genuinely unrelated
subsystems (outbound webhook delivery vs internal vacuum maintenance;
user-facing cart concurrency vs internal stats-refresh scheduling;
outbound email delivery vs DB replication topology). These test
*restraint under temptation* — whether the model is doing causal
reasoning or just fancy string matching — which the passing
`t2-*-vs-*` cases mostly can't distinguish on their own.

`outcome_class: "documented-limitation"` cases are reported as
*reproduced / not reproduced*, never pass/fail.

## Known limitation: shared `error_code` deterministic false-link

`correlation/deterministic.py` groups events sharing ANY identifier value
(including `error_code=`/`status=`, matched case-insensitively via
`config.CORRELATION_KEY_PATTERNS`) within `DETERMINISTIC_TIME_WINDOW_SECONDS`
and links them at confidence 1.0 — by design, with no semantic check. Two
narratively unrelated events that happen to carry the same `error_code`
(e.g. two different failures both tagged `DB_TIMEOUT`) will link.

This is an **accepted precision tradeoff of the deterministic stage, not a
bug**. `doc-error-code-false-link` reproduces it deliberately and asserts
the false link as the *expected* outcome — no case in this catalog asserts
"must not link" for shared `error_code`.

## Deviation from design: `doc-hybrid-component-merge`

The design doc's case-catalog table describes this case in one line as:
"the `doc-error-code-false-link` pair plus a true semantic pair sharing an
endpoint collapse into **one incident**; report flags `merged_by:
[id_match, semantic_similarity]`."

That literal outcome is **not producible by the pipeline as implemented**:
`correlation/pipeline.py`'s `run_correlation()` removes every event that
participated in ANY deterministic edge from the pool passed to the semantic
stage (`unlinked = [e for e in events if e.event_id not in linked_ids]`).
An event cannot be both deterministically AND semantically linked in the
same run — so a single connected component containing both an `id_match`
edge and a `semantic_similarity` edge is structurally impossible here.

This case instead implements the spec's own KF-3 text precisely (`spec.md`,
"Requirement: sub-threshold LLM confidence is observable per case" section
neighbor, KF-3 — "Hybrid deterministic+semantic interaction"), which is
more accurate than the design table's one-liner: **a deterministic edge
removes one member of a would-be semantic pair from the unlinked pool,
changing which events end up in the same connected component — not a
naive sum of "deterministic result + semantic result run independently."**

Concretely: `pg-db-timeout` and `tomcat-db-error` share `error_code=DB_TIMEOUT`
and link deterministically (removing both from the semantic pool).
`tomcat-would-be-semantic-partner` carries a narrative that would plausibly
link to `pg-db-timeout` semantically — if `pg-db-timeout` were still
available. It isn't, so `tomcat-would-be-semantic-partner` ends up an
isolated singleton instead of merging into one 3-member incident. The
`expected` block asserts exactly this (2-member deterministic incident +
1 singleton), with the would-be semantic edge listed under
`forbidden_edges` to make the counterfactual explicit and checkable.

## Running the harness

```bash
python -m harness.cli --cases scenarios/
```

See `harness/README.md` for the full runbook (live-dependency setup,
options, and report format).
