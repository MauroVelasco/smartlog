# postgres-log-source

A bootstrap-and-emit helper for the root Postgres service (`docker-compose.yml`,
container `log_intelligence_postgres`) that makes it possible to trigger
real, caller-controlled server log lines at INFO/WARNING/ERROR on demand —
the Postgres leg of the `postgres-scenario-harness` correlation harness.

Unlike `tomcat-log-source/` and `cloudwatch-log-generator/`, this is not a
separate app/container. It's a SQL function (`emit_log.sql`) installed into
the existing `log_intelligence_postgres` database, plus a thin Python
invoker (`trigger.py`).

## Why this exists

`extraction/db_log_extractor.py`'s `PostgresLogFileExtractor` already reads
the live Postgres server log via `pg_read_file()`. What was missing was a
supported way to make the server *emit* a log line on demand, at a chosen
level, with chosen identifier fields, without the caller's own database
connection dying on the ERROR path (a naive uncaught `RAISE EXCEPTION`
aborts the current transaction). `harness.emit_log()` solves that with a
nested `BEGIN … EXCEPTION WHEN OTHERS THEN NULL END` block — see
`emit_log.sql`'s header comment for the full mechanism.

## Setup

1. `docker-compose.yml` at the repo root already sets the required logging
   flags (`logging_collector=on`, `log_line_prefix='%m [%p] '`,
   `log_min_messages=info`, `log_error_verbosity=terse`,
   `log_min_error_statement=panic`, `TZ=UTC`). Start/restart the service so
   they take effect:

   ```bash
   docker compose up -d postgres
   ```

2. Install the `harness` schema + `emit_log()` function:

   ```bash
   docker compose exec -T postgres \
     psql -U postgres -d log_intelligence \
     < postgres-log-source/emit_log.sql
   ```

3. Configure the app-side connection the extractor and trigger script use
   (root `.env` or exported in your shell):

   ```bash
   DATABASE_URL_APP=postgresql://postgres:postgres@localhost:5432/log_intelligence
   DB_LOG_SOURCES=postgres:app
   DB_LOGS_ENABLED=true
   ```

   `DB_LOG_SOURCES=postgres:app` tells `extraction/db_log_extractor.py` to
   build a `PostgresLogFileExtractor` whose connection name is `app`, which
   resolves to `DATABASE_URL_APP` via `storage/db.py:get_engine_for()`.

## Verifying it works (manual runbook)

```bash
DATABASE_URL_APP=postgresql://postgres:postgres@localhost:5432/log_intelligence \
  ./.venv/bin/python postgres-log-source/trigger.py
```

Expected output:

```
OK: emitted INFO/WARNING/ERROR lines; connection survived the ERROR path.
```

This confirms, end to end:

- `pg_current_logfile()` returns a non-NULL path (logging_collector is on)
- `harness.emit_log()` writes INFO, WARNING, and ERROR lines to that file
- the caller's own psycopg2 connection survives the ERROR path and can run
  another query afterwards
- no phantom `CONTEXT:`/`STATEMENT:` lines are written (verify by tailing
  the container's log file — `docker compose exec postgres bash -c
  'tail -f "$(psql -U postgres -d log_intelligence -tAc "SELECT
  pg_current_logfile()")"'`, prefixed with the container's data directory)

Then confirm the Python extraction side sees a real emitted entry:

```python
from datetime import datetime, timedelta, timezone
from extraction.db_log_extractor import PostgresLogFileExtractor

extractor = PostgresLogFileExtractor("app")
records = extractor.extract(
    start_time=datetime.now(timezone.utc) - timedelta(minutes=5),
    end_time=datetime.now(timezone.utc) + timedelta(minutes=1),
)
assert any("harness bootstrap check" in r.raw_payload["message"] for r in records)
```

## `harness.emit_log()` signature

```sql
harness.emit_log(
    p_level           text,       -- 'INFO' | 'WARNING' | 'ERROR' (anything else raises, uncaught)
    p_message         text,
    p_trx_id          text    DEFAULT NULL,
    p_username        text    DEFAULT NULL,
    p_component_id    text    DEFAULT NULL,
    p_error_code      text    DEFAULT NULL,
    p_identifier_free boolean DEFAULT false
) RETURNS void
```

When `p_identifier_free = false` (default), the provided fields are
appended as `request_id=`/`trace_id=`/`user_id=`/`service_name=`/
`error_code=` tokens — the same vocabulary
`normalization/normalizer.py:extract_identifiers()` already matches. When
`true`, nothing is appended; only `p_message` is written, which is the mode
the harness's Tier 2 (identifier-free, semantic-only) scenario cases use.

## Known limitation this generator does not fix

The shared-`error_code` deterministic false-link (two unrelated events that
happen to carry the same `error_code=`/`status=` value link at confidence
1.0, by design of `correlation/deterministic.py`) applies here exactly as
it does for the other two generators. This is documented, not patched, in
`scenarios/README.md` — see the `doc-error-code-false-link` case.
