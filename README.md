# AI-Correlated Log Intelligence — POC

Implements the "Architecture at a glance" pipeline from the internal
business case (July 2026), end to end from **Log Sources** through the
**Relationship Store**, plus the **Visualization UI**:

```
Log Sources → Ingestion & Normalization → LangChain Correlation Agents → Relationship Store → Visualization UI
CloudWatch*    Parse/timestamp-align/       Deterministic ID/timestamp      Postgres: events +   Interactive graph,
Tomcat         standardize each source's    joins first; LLM only on       inferred links        colored by system,
GCP Logging    log format into a common     events left unlinked           (graph-shaped, not    grouped into
Oracle/MySQL/  LogEvent shape                                              forced into a tree)   incidents
Postgres
```
\* CloudWatch is the primary, active extraction point for this POC, matching
business case slide 10 stage 1 ("One client's CloudWatch + Tomcat logs").
Tomcat, GCP Logging, and Oracle/MySQL/Postgres extractors are implemented
against the same interface and enabled via `.env` flags — turning them on
is stage 2 ("Expand & harden"), not a rewrite.

## Module map → architecture stage

| Stage | Module |
|---|---|
| Log Sources | `extraction/cloudwatch_extractor.py` (primary), `tomcat_extractor.py`, `gcp_logging_extractor.py`, `db_log_extractor.py` (`OracleAlertLogExtractor`, `MySQLErrorLogExtractor`, `PostgresLogFileExtractor`), `extraction/registry.py` |
| Ingestion & Normalization | `normalization/normalizer.py`, `models/schema.py` |
| LangChain Correlation Agents | `correlation/deterministic.py` (ID/timestamp joins), `correlation/langchain_agents.py` (LLM semantic fallback), `correlation/pipeline.py` (orchestrates the hybrid) |
| Relationship Store | `storage/models.py`, `storage/relationship_store.py`, `storage/schema.sql` |
| Visualization UI | `visualization/app.py` (FastAPI), `visualization/graph_builder.py`, `visualization/templates/index.html` (vis-network) |

## Design decisions carried over from the business case

- **Hybrid correlation (slide 5, slide 9).** `correlation/deterministic.py`
  links events sharing a request_id/trace_id/user_id/error_code/service_name
  within a time window at confidence 1.0. Only events left unlinked go to
  `correlation/langchain_agents.py`, which further buckets by a small time
  window and batch size before ever calling the LLM — this is the cost/
  latency control slide 9 flags as a derisking item.
- **Graph, not a forced tree (slide 9).** The Relationship Store is two
  tables — `log_events` (nodes) and `correlation_edges` (edges) — and an
  "incident" is a connected component of that graph
  (`RelationshipStore.list_incidents`), not a hierarchy. Real log
  relationships are many-to-many, so the UI renders the actual graph and
  lets a force-directed layout reveal structure.
- **Correlation confidence is visible, not hidden.** Deterministic edges
  render solid; LLM-inferred edges render dashed with an opacity tied to
  confidence — so a human reviewing an incident can tell "the system is
  sure" from "the system is guessing," directly addressing slide 9's
  "keyword-only joins are fragile" / "false links are worse than missed
  ones" concern.
- **CloudWatch-first, not CloudWatch-only.** Every other source implements
  the same `BaseExtractor` interface so the POC can expand without
  touching normalization, correlation, storage, or the UI.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in AWS creds, CLOUDWATCH_LOG_GROUPS, ANTHROPIC_API_KEY, DATABASE_URL

docker compose up -d   # local Postgres for the Relationship Store
```

### Enabling the non-CloudWatch sources

Each extractor is real, working code, gated behind its own `.env` flag so the POC can start CloudWatch-only and turn sources on one at a time:

| Source | Enable with | Needs |
|---|---|---|
| Tomcat | `TOMCAT_ENABLED=true`, `TOMCAT_LOG_PATHS=...` (glob patterns and `.gz` rotated logs supported) | Read access to the log file(s); no credentials |
| GCP Logging | `GCP_LOGGING_ENABLED=true`, `GCP_PROJECT_ID`, `GCP_LOG_FILTER` | `pip install google-cloud-logging`, a service account with `roles/logging.viewer` (or ambient `gcloud auth application-default login` creds) |
| Postgres | `DB_LOGS_ENABLED=true`, `DB_LOG_SOURCES=postgres:<name>`, `DATABASE_URL_<NAME>` | Role granted `pg_read_server_files` (or superuser); `log_line_prefix` must include `%m [%p]` (RDS default) |
| Oracle | same, `oracle:<name>` | `pip install oracledb`; SELECT on `V$DIAG_ALERT_EXT` (`SELECT_CATALOG_ROLE` or a DBA grant) |
| MySQL | same, `mysql:<name>` | `pip install pymysql`; MySQL 8.0.22+ (`performance_schema.error_log` ships on by default) |

Postgres has no built-in error-log table, so `PostgresLogFileExtractor` reads the live server log file via `pg_read_file()` instead of querying a system view — see the docstring in `extraction/db_log_extractor.py` for the exact permission grant.

## Run the pipeline (Log Sources → Relationship Store)

```bash
# First run: create tables, pull the last hour from CloudWatch, hybrid correlate
python main.py --since 1h --init-schema

# Deterministic-only (no LLM calls/cost)
python main.py --since 1h --no-llm

# Specific window
python main.py --since 2026-08-01T00:00:00Z --until 2026-08-01T06:00:00Z
```

## Run the Visualization UI

```bash
uvicorn visualization.app:app --reload --port 8000
```

Open http://localhost:8000 — the sidebar lists every incident (connected
component) found in the store, ranked by size; clicking one renders its
interactive graph. Node color = source system, node size/border = log
level, solid edges = deterministic match, dashed edges = LLM-inferred
match. Click any node for its full raw message and identifiers.

## Tests

```bash
pytest tests/ -v
```

## What's intentionally out of scope here

Per the business case's proposed path (slide 10), this covers stage 1
(CloudWatch + Tomcat, deterministic join, POC) and lays the groundwork for
stage 2 (GCP + DB sources, hybrid LLM correlation, interactive UI — both
implemented and ready to enable). Stage 3 (pilot with real accounts, MTTR
measurement) and stage 4 (GTM decision) are business/ops activities, not
code, and start after a POC demo checkpoint.
