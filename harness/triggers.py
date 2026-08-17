"""
Per-source trigger implementations (postgres-scenario-harness harness
architecture). Each fires one Step's descriptor against the live generator;
CloudWatch is schema-valid but harness-inert (spec: "CloudWatch is
describable but never triggered").
"""
from __future__ import annotations

import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from harness.models import CloudWatchStep, PostgresStep, TomcatStep

# postgres-log-source/ has a hyphen in its name, so it can't be a normal
# Python package import (`import postgres-log-source.trigger` is invalid
# syntax) — path-inject it once, same approach as
# tests/test_zero_deterministic_edges_gate.py.
_PG_LOG_SOURCE_DIR = str(Path(__file__).resolve().parent.parent / "postgres-log-source")
if _PG_LOG_SOURCE_DIR not in sys.path:
    sys.path.insert(0, _PG_LOG_SOURCE_DIR)
import trigger as pg_trigger  # noqa: E402  (path-injected sibling module, not a package)

DEFAULT_TOMCAT_BASE_URL = "http://localhost:8080"
DEFAULT_POSTGRES_DSN = "postgresql://postgres:postgres@localhost:5432/log_intelligence"


class TomcatTrigger:
    """Fires a Tomcat step's HTTP GET against the live servlet
    (tomcat-log-source). Plain urllib — no extra dependency needed for a
    single GET with query params."""

    def __init__(self, base_url: str = DEFAULT_TOMCAT_BASE_URL):
        self.base_url = base_url.rstrip("/")

    def fire(self, step: TomcatStep) -> None:
        query = urllib.parse.urlencode(step.http.query)
        url = f"{self.base_url}{step.http.path}"
        if query:
            url = f"{url}?{query}"
        try:
            urllib.request.urlopen(url, timeout=10).read()
        except urllib.error.HTTPError:
            # Several scenario endpoints deliberately return non-2xx (e.g.
            # /error -> 500, /db-error -> 503) — the harness only cares
            # that the log line was written, which already happened
            # server-side before the response status was set.
            pass


class PostgresTrigger:
    """Fires a Postgres step's harness.emit_log() call.

    MUST use autocommit=True — see postgres-log-source/emit_log.sql's
    header comment and trigger.py's module docstring: the ERROR-level path
    raises UNCAUGHT by design (a caught RAISE EXCEPTION was found,
    empirically, to write nothing to the Postgres server log), and
    autocommit is what lets the connection survive that per-statement
    failure. Reuses postgres_log_source.trigger.emit_log(), which already
    catches exactly the expected SQLSTATE ZZ001 on that path.
    """

    def __init__(self, dsn: str = DEFAULT_POSTGRES_DSN):
        self.dsn = dsn
        self._conn = None

    def _connection(self):
        if self._conn is None or self._conn.closed:
            self._conn = pg_trigger.connect(self.dsn)
        return self._conn

    def fire(self, step: PostgresStep) -> None:
        pg_trigger.emit_log(self._connection(), step.sql.args)

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()


class CloudWatchTrigger:
    """No-op — CloudWatch's @Scheduled tick model is incompatible with this
    synchronous trigger→wait→run→compare loop (spec requirement:
    "CloudWatch is describable but never triggered"). Exists so the harness
    loop can treat all three sources uniformly without a source-specific
    branch at the call site."""

    def fire(self, step: CloudWatchStep) -> None:
        return None
