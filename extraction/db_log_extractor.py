"""
Oracle / MySQL / Postgres log extraction — business case slide 10 stage 2.
Disabled by default in the POC. Each engine exposes its error log
differently, so this module has one extractor class per engine rather
than a single generic query:

  - OracleAlertLogExtractor: queries V$DIAG_ALERT_EXT (the alert log
    exposed as a relation since 11g) via a bind-parameterized SELECT.
  - MySQLErrorLogExtractor: queries performance_schema.error_log
    (MySQL 8.0.22+, on by default).
  - PostgresLogFileExtractor: Postgres has no built-in error-log table,
    so this reads the current log file straight off the server via
    pg_read_file() and groups multi-line entries the same way the
    Tomcat extractor does.

All three share `DBLogSourceConfig`, resolved from DB_LOG_SOURCES
entries like "oracle:billing" / "mysql:orders" / "postgres:app", where
the part after the colon is a connection name looked up via
storage.db.get_engine_for() -> DATABASE_URL_<NAME> in the environment.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from extraction.base import BaseExtractor
from models.schema import RawLogRecord, SourceSystem

logger = logging.getLogger(__name__)


@dataclass
class DBLogSourceConfig:
    engine: str  # oracle | mysql | postgres
    connection_name: str


def _get_engine(connection_name: str):
    from storage.db import get_engine_for  # local import: avoid a hard dep at module load

    return get_engine_for(connection_name)


# ---------------------------------------------------------------------------
# Oracle
# ---------------------------------------------------------------------------
class OracleAlertLogExtractor(BaseExtractor):
    """Reads the Oracle alert log via V$DIAG_ALERT_EXT.

    Requires a connection with SELECT on V$DIAG_ALERT_EXT (typically
    granted via SELECT_CATALOG_ROLE, or explicitly by a DBA). Connection
    string in DATABASE_URL_<NAME> should use a SQLAlchemy Oracle driver,
    e.g. `oracle+oracledb://user:pass@host:1521/?service_name=ORCLPDB1`.
    """

    source_system = SourceSystem.ORACLE.value

    _QUERY = """
        SELECT originating_timestamp, message_text, module_id, host_id
        FROM v$diag_alert_ext
        WHERE originating_timestamp >= :start_time
          AND originating_timestamp < :end_time
        ORDER BY originating_timestamp
    """

    def __init__(self, connection_name: str):
        self.connection_name = connection_name

    def extract(self, start_time: datetime, end_time: datetime) -> List[RawLogRecord]:
        from sqlalchemy import text

        records: List[RawLogRecord] = []
        try:
            engine = _get_engine(self.connection_name)
            with engine.connect() as conn:
                result = conn.execute(text(self._QUERY), {"start_time": start_time, "end_time": end_time})
                for row in result.mappings():
                    records.append(
                        RawLogRecord(
                            source_system=SourceSystem.ORACLE,
                            origin=self.connection_name,
                            raw_payload={
                                "timestamp": _iso(row.get("originating_timestamp")),
                                "message": row.get("message_text") or "",
                                "module": row.get("module_id"),
                                "host": row.get("host_id"),
                            },
                        )
                    )
        except Exception as exc:  # pragma: no cover - depends on a live DB
            logger.warning(
                "Oracle alert log extraction failed for '%s' (need SELECT on V$DIAG_ALERT_EXT): %s",
                self.connection_name,
                exc,
            )
        return records


# ---------------------------------------------------------------------------
# MySQL
# ---------------------------------------------------------------------------
class MySQLErrorLogExtractor(BaseExtractor):
    """Reads the MySQL error log via performance_schema.error_log
    (available and on by default since MySQL 8.0.22).

    For slow-query correlation, also enable log_output='TABLE' and
    extend this class to additionally query mysql.slow_log — left out
    here to keep the POC's first pass focused on errors, which is what
    the business case's correlation scenarios (500s, timeouts, pool
    exhaustion) actually need.
    """

    source_system = SourceSystem.MYSQL.value

    _QUERY = """
        SELECT LOGGED AS event_time, PRIO AS prio, ERROR_CODE AS error_code,
               SUBSYSTEM AS subsystem, DATA AS message
        FROM performance_schema.error_log
        WHERE LOGGED >= :start_time AND LOGGED < :end_time
        ORDER BY LOGGED
    """

    def __init__(self, connection_name: str):
        self.connection_name = connection_name

    def extract(self, start_time: datetime, end_time: datetime) -> List[RawLogRecord]:
        from sqlalchemy import text

        records: List[RawLogRecord] = []
        try:
            engine = _get_engine(self.connection_name)
            with engine.connect() as conn:
                result = conn.execute(text(self._QUERY), {"start_time": start_time, "end_time": end_time})
                for row in result.mappings():
                    records.append(
                        RawLogRecord(
                            source_system=SourceSystem.MYSQL,
                            origin=self.connection_name,
                            raw_payload={
                                "timestamp": _iso(row.get("event_time")),
                                "level": row.get("prio"),
                                "message": row.get("message") or "",
                                "error_code": row.get("error_code"),
                                "subsystem": row.get("subsystem"),
                            },
                        )
                    )
        except Exception as exc:  # pragma: no cover - depends on a live DB
            logger.warning(
                "MySQL error log extraction failed for '%s' (requires MySQL 8.0.22+): %s",
                self.connection_name,
                exc,
            )
        return records


# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------
_PG_ENTRY_START = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) (?P<tz>\S+) \[(?P<pid>\d+)\] (?P<level>[A-Z]+):\s?(?P<rest>.*)$"
)
_PG_MAX_LOG_BYTES = 50_000_000  # cap a single read; POC scale, not a log-shipping pipeline


class PostgresLogFileExtractor(BaseExtractor):
    """Reads the currently active Postgres server log via pg_read_file().

    Requires either superuser or a role granted `pg_read_server_files`
    (PG 11+), and a `log_line_prefix` that includes `%m [%p]` (the
    default on most managed Postgres, including RDS). This is a
    single-shot read capped at _PG_MAX_LOG_BYTES — fine for a POC; a
    production version would track a byte offset between runs instead
    of re-reading from the start each time.
    """

    source_system = SourceSystem.POSTGRES.value

    def __init__(self, connection_name: str):
        self.connection_name = connection_name

    def extract(self, start_time: datetime, end_time: datetime) -> List[RawLogRecord]:
        from sqlalchemy import text

        try:
            engine = _get_engine(self.connection_name)
            with engine.connect() as conn:
                current_logfile = conn.execute(text("SELECT pg_current_logfile()")).scalar()
                if not current_logfile:
                    logger.warning(
                        "'%s': pg_current_logfile() returned nothing — is logging_collector on?",
                        self.connection_name,
                    )
                    return []
                content = conn.execute(
                    text("SELECT pg_read_file(:path, 0, :max_bytes)"),
                    {"path": current_logfile, "max_bytes": _PG_MAX_LOG_BYTES},
                ).scalar()
        except Exception as exc:  # pragma: no cover - depends on a live DB
            logger.warning(
                "Postgres log file extraction failed for '%s' (needs pg_read_server_files): %s",
                self.connection_name,
                exc,
            )
            return []

        return self._parse_log_text(content or "")

    def _parse_log_text(self, content: str) -> List[RawLogRecord]:
        records: List[RawLogRecord] = []
        entry_lines: List[str] = []
        entry_meta: Optional[dict] = None

        def flush():
            if entry_meta is None:
                return
            records.append(
                RawLogRecord(
                    source_system=SourceSystem.POSTGRES,
                    origin=self.connection_name,
                    raw_payload={
                        "timestamp": entry_meta["timestamp"],
                        "level": entry_meta["level"],
                        "pid": entry_meta["pid"],
                        "message": "\n".join(entry_lines),
                    },
                )
            )

        for line in content.splitlines():
            match = _PG_ENTRY_START.match(line)
            if match:
                flush()
                entry_meta = {
                    "timestamp": f"{match.group('ts')} {match.group('tz')}",
                    "level": match.group("level"),
                    "pid": match.group("pid"),
                }
                entry_lines = [match.group("rest")]
            elif entry_meta is not None:
                entry_lines.append(line)
        flush()

        return records


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)


def build_db_extractor(source_config: DBLogSourceConfig) -> BaseExtractor:
    if source_config.engine == "oracle":
        return OracleAlertLogExtractor(source_config.connection_name)
    if source_config.engine == "mysql":
        return MySQLErrorLogExtractor(source_config.connection_name)
    if source_config.engine == "postgres":
        return PostgresLogFileExtractor(source_config.connection_name)
    raise ValueError(f"Unsupported DB engine: {source_config.engine}")
