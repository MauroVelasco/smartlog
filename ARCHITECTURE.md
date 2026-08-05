# AI-Correlated Log Intelligence — Architecture (Draft)

Status: draft, POC scope. Covers the code already built in `log_correlation_poc/`, plus a proposed (not yet implemented) deployment view. Maps directly to "Architecture at a glance" in the business case (slide 5) and the phased plan on slide 10.

## 1. Overview

Five stages, each independently swappable behind a narrow interface:

```
Log Sources → Ingestion & Normalization → Correlation Agents → Relationship Store → Visualization UI
```

CloudWatch is the primary, active extraction point for the POC. Tomcat, GCP Logging, and Oracle/MySQL/Postgres are implemented against the same extractor interface and enabled via config flags — bringing them online is a phase 2 config change, not new code (business case slide 10, "Expand & harden").

## 2. Components & Services

### 2.1 Log Sources (extraction)

| Component | Responsibility | Tech stack | Files |
|---|---|---|---|
| CloudWatch Extractor | Primary log pull via `filter_log_events`, pagination, throttling backoff | Python, boto3, botocore | `extraction/cloudwatch_extractor.py` |
| Tomcat Extractor | Reads catalina.out / rotated (`.gz`) logs from disk or mounted volume; stitches multi-line stack traces into one logical record | Python (stdlib: `gzip`, `re`) | `extraction/tomcat_extractor.py` |
| GCP Logging Extractor | Pulls entries via Cloud Logging API (disabled by default); flattens text/JSON/proto payloads to text | Python, google-cloud-logging | `extraction/gcp_logging_extractor.py` |
| Oracle Alert Log Extractor | Queries `V$DIAG_ALERT_EXT` for the alert log | Python, SQLAlchemy, python-oracledb | `extraction/db_log_extractor.py` (`OracleAlertLogExtractor`) |
| MySQL Error Log Extractor | Queries `performance_schema.error_log` (MySQL 8.0.22+, on by default) | Python, SQLAlchemy, PyMySQL | `extraction/db_log_extractor.py` (`MySQLErrorLogExtractor`) |
| Postgres Log File Extractor | Reads the live server log via `pg_read_file()`, parses/stitches multi-line entries | Python, SQLAlchemy, psycopg2 | `extraction/db_log_extractor.py` (`PostgresLogFileExtractor`) |
| Extractor Registry | Builds the active extractor set from config | Python | `extraction/registry.py`, `extraction/base.py` |

### 2.2 Ingestion & Normalization

| Component | Responsibility | Tech stack | Files |
|---|---|---|---|
| Normalizer | Parses each source's raw format, aligns timestamps to UTC, extracts correlation identifiers via regex (request_id, trace_id, user_id, error_code, service_name) | Python, python-dateutil, `re` | `normalization/normalizer.py` |
| Schema | Common `RawLogRecord` / `LogEvent` / `CorrelationEdge` contracts used by every downstream stage | Pydantic v2 | `models/schema.py` |

### 2.3 Correlation Agents

| Component | Responsibility | Tech stack | Files |
|---|---|---|---|
| Deterministic Correlator | Links events sharing an identifier within a time window at confidence 1.0 — runs first, no LLM cost | Python (stdlib) | `correlation/deterministic.py` |
| Semantic Correlation Agent | LLM fallback for events left unlinked; time-bucketed and batch-capped before any model call; structured-output parsing | LangChain (`langchain-core`), `langchain-anthropic` (default) or `langchain-openai`, Claude/GPT API | `correlation/langchain_agents.py` |
| Correlation Pipeline | Orchestrates deterministic-then-semantic hybrid, reports stats | Python | `correlation/pipeline.py` |

### 2.4 Relationship Store

| Component | Responsibility | Tech stack | Files |
|---|---|---|---|
| ORM models | `log_events` (nodes) and `correlation_edges` (edges) tables — graph-shaped, not tree-shaped | SQLAlchemy 2.0 | `storage/models.py`, `storage/schema.sql` |
| RelationshipStore | Persists events/edges, loads the graph, computes incidents as connected components | SQLAlchemy, NetworkX | `storage/relationship_store.py` |
| Database | Stores everything; JSONB column for identifiers with a GIN index | PostgreSQL 16 (Docker Compose for local dev; RDS for cloud) | `docker-compose.yml` |

### 2.5 Visualization UI

| Component | Responsibility | Tech stack | Files |
|---|---|---|---|
| API service | Serves the page, `/api/incidents`, `/api/graph` | FastAPI, Uvicorn | `visualization/app.py` |
| Graph builder | Shapes the NetworkX graph into vis-network node/edge JSON; colors by source system, borders by severity, solid vs. dashed edges by correlation confidence | Python | `visualization/graph_builder.py` |
| Frontend | Interactive force-directed graph, incident sidebar, node detail panel | HTML/CSS/JS, vis-network.js (CDN), Jinja2 template | `visualization/templates/index.html` |

### 2.6 Cross-cutting

| Component | Responsibility | Tech stack | Files |
|---|---|---|---|
| Orchestrator | CLI entrypoint: extract → normalize → correlate → persist | Python, argparse | `main.py` |
| Config | Central settings, all overridable via env vars | python-dotenv | `config.py`, `.env.example` |
| Tests | Unit tests for normalization, deterministic correlation, graph shaping | pytest | `tests/` |
| Local dev environment | Postgres for local runs | Docker Compose | `docker-compose.yml` |

## 3. Data model (summary)

- **RawLogRecord** — `source_system`, `origin`, `raw_payload` (source-specific), `fetched_at`. Output of extraction, untouched.
- **LogEvent** — `event_id`, `source_system`, `origin`, `timestamp` (UTC), `level`, `message`, `identifiers` (dict), `host`. Output of normalization; everything downstream depends on this shape.
- **CorrelationEdge** — `source_event_id`, `target_event_id`, `relation_type` (`id_match` | `time_window` | `semantic_similarity`), `confidence`, `matched_on`. Output of correlation.

## 4. Proposed deployment (not yet implemented — for review)

| Layer | Proposal | Rationale |
|---|---|---|
| Pipeline runner | AWS ECS Fargate task, triggered on a schedule via EventBridge (or ad hoc for POC demos) | Log extraction windows can run long; Fargate avoids Lambda's 15-minute cap and cold-start cost for a job that already batches LLM calls |
| Relationship Store | Amazon RDS for PostgreSQL (single-AZ for POC, Multi-AZ for pilot) | Managed backups/patching; same engine as local Docker Compose so no code changes |
| Visualization UI | ECS Fargate service behind an internal ALB, restricted to VPN/office IPs for the POC phase | Matches "internal tool first" sequencing from the business case (slide 8) |
| Secrets | AWS Secrets Manager for AWS creds (if not using task IAM role), DB credentials, and the LLM API key | Avoids plaintext secrets in `.env` outside local dev |
| IAM | Least-privilege role for the pipeline task: `logs:FilterLogEvents`/`logs:GetLogEvents` scoped to the specific log groups, RDS connect, Secrets Manager read | Limits blast radius; CloudWatch access shouldn't imply account-wide log access |
| Networking | RDS in private subnets; pipeline task and UI service in the same VPC | Standard isolation for a service holding raw log content, which may include sensitive data |
| Runtime | Linux containers throughout (matches your existing stack) | Consistent with AWS/GCP/Oracle/MySQL/Postgres/Linux environments already in use |

## 5. Cost & scaling notes (ties to business case slide 9)

- The hybrid design is the primary cost control: deterministic joins are free; the LLM only sees events that survive the deterministic pass, pre-bucketed by a small time window and capped batch size (`SEMANTIC_TIME_BUCKET_SECONDS`, `SEMANTIC_MAX_BATCH_SIZE` in `config.py`).
- `SEMANTIC_MIN_CONFIDENCE` discards low-confidence LLM links before they're persisted, reducing false-link noise flagged as a risk in the business case.
- Postgres indexes (`timestamp`, `source_system`, GIN on `identifiers`) keep the deterministic join and graph load performant as log volume grows; if the events table grows large, time-based partitioning is a natural next step (not yet implemented).

## 6. Security notes (draft — needs a real review before pilot)

- Raw log messages may contain PII or secrets (tokens, connection strings). Before this reaches an LLM API, add a redaction/masking pass — not yet implemented.
- CloudWatch, DB, and GCP credentials should be scoped read-only and log-group/table specific, not account-wide.
- The Visualization UI currently has no auth layer — fine for a local POC, not acceptable once it's reachable outside a laptop; add SSO/IAM-based auth before the pilot phase (slide 10, stage 3).

## 7. Phase mapping (business case slide 10)

| Phase | What's already built | What's still needed |
|---|---|---|
| 1. POC (4–6 wks) | CloudWatch extractor, deterministic correlation, static graph output all functional | Point at one real client's CloudWatch + Tomcat logs; enable `TOMCAT_ENABLED` |
| 2. Expand & harden (6–8 wks) | GCP Logging and DB extractors coded against the same interface; LangChain semantic fallback implemented; interactive UI built | Real GCP/DB credentials and testing against live data; redaction pass; load testing |
| 3. Pilot (4–6 wks) | — | Auth on the UI, deployment to AWS (section 4), MTTR baseline measurement |
| 4. Decision point | — | Business/GTM decision, not code |

## 8. Open questions

- Confirm target LLM provider (Anthropic vs. OpenAI) and expected monthly log volume, to size `SEMANTIC_*` cost-control thresholds realistically.
- Confirm whether Tomcat logs are already shipped into CloudWatch (common with the unified CloudWatch agent) — if so, the dedicated Tomcat file-extractor may be unnecessary for phase 1.
- Decide on redaction approach for PII/secrets in log messages before any LLM call.
