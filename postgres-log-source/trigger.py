"""
postgres-log-source/trigger.py

Standalone invoker for harness.emit_log() (see emit_log.sql). Used both for
manual bootstrap verification (see README.md) and reused by
harness/triggers.py's PostgresTrigger (the scenario harness, Phase 7) to
fire scenario JSON `sql.args` payloads.

Connects via psycopg2 with autocommit=True. This is load-bearing, not
cosmetic: harness.emit_log()'s ERROR path deliberately raises UNCAUGHT
(see emit_log.sql's header comment — a caught RAISE EXCEPTION was found,
empirically, to write NOTHING to the Postgres server log). Under
autocommit, each statement is its own implicit transaction, so an uncaught
error aborts only that one statement — the connection stays fully usable
for the next call with no ROLLBACK needed. emit_log() below expects and
swallows exactly that one expected error (tagged with SQLSTATE ZZ001);
anything else propagates as a real failure.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import psycopg2

# Custom SQLSTATE emit_log.sql tags its intentional ERROR-level RAISE
# EXCEPTION with — distinguishes "the harness meant to emit an ERROR line"
# from a genuine failure (bad args, unsupported level, connection issue).
_EXPECTED_ERROR_SQLSTATE = "ZZ001"


def dsn_from_env(env_var: str = "DATABASE_URL_APP") -> str:
    url = os.getenv(env_var)
    if not url:
        raise RuntimeError(f"{env_var} is not set — see postgres-log-source/README.md")
    # storage/db.py uses SQLAlchemy's "postgresql+psycopg2://" dialect form;
    # psycopg2.connect() only understands the plain "postgresql://" DSN.
    return url.replace("postgresql+psycopg2://", "postgresql://")


def connect(dsn: Optional[str] = None):
    conn = psycopg2.connect(dsn or dsn_from_env())
    conn.autocommit = True
    return conn


def emit_log(conn, args: Dict[str, Any]) -> None:
    """Invoke harness.emit_log() with named params straight from a scenario
    JSON step's `sql.args` block (see scenarios/README.md for the schema).

    Requires `conn.autocommit = True` (see connect()). For p_level='ERROR',
    harness.emit_log() raises UNCAUGHT by design — this function catches
    exactly that expected exception (SQLSTATE ZZ001) so the ERROR path
    looks the same to callers as INFO/WARNING: the emission happened, the
    connection is still usable. Any other exception (bad args, unsupported
    level, connection dropped) propagates.
    """
    with conn.cursor() as cur:
        try:
            cur.execute(
                """
                SELECT harness.emit_log(
                    %(p_level)s, %(p_message)s, %(p_trx_id)s, %(p_username)s,
                    %(p_component_id)s, %(p_error_code)s, %(p_identifier_free)s
                )
                """,
                {
                    "p_level": args["p_level"],
                    "p_message": args["p_message"],
                    "p_trx_id": args.get("p_trx_id"),
                    "p_username": args.get("p_username"),
                    "p_component_id": args.get("p_component_id"),
                    "p_error_code": args.get("p_error_code"),
                    "p_identifier_free": args.get("p_identifier_free", False),
                },
            )
        except psycopg2.Error as exc:
            if args.get("p_level") == "ERROR" and getattr(exc, "pgcode", None) == _EXPECTED_ERROR_SQLSTATE:
                return  # expected — the ERROR line was written server-side
            raise


def _bootstrap_check() -> None:
    """Manual bootstrap check — see postgres-log-source/README.md:

        DATABASE_URL_APP=postgresql://postgres:postgres@localhost:5432/log_intelligence \\
          ./.venv/bin/python postgres-log-source/trigger.py
    """
    conn = connect()
    try:
        emit_log(conn, {"p_level": "INFO", "p_message": "harness bootstrap check: INFO line"})
        emit_log(conn, {"p_level": "WARNING", "p_message": "harness bootstrap check: WARNING line"})
        emit_log(conn, {"p_level": "ERROR", "p_message": "harness bootstrap check: ERROR line"})
        # The connection must still be usable after the ERROR path — this is
        # exactly what autocommit=True + emit_log()'s expected-exception
        # catch guarantees (see module docstring).
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)
        print("OK: emitted INFO/WARNING/ERROR lines; connection survived the ERROR path.")
    finally:
        conn.close()


if __name__ == "__main__":
    _bootstrap_check()
