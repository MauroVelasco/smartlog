"""
Central configuration for the AI-Correlated Log Intelligence POC.

Maps directly to "Architecture at a glance" (business case, slide 5):
  Log Sources -> Ingestion & Normalization -> LangChain Correlation Agents
  -> Relationship Store -> Visualization UI

All values are overridable via environment variables / .env so the same
code runs against a real AWS account without edits.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: str = "") -> List[str]:
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


# ---------------------------------------------------------------------------
# Log Sources (CloudWatch is the primary/active extraction point for the POC,
# per business case slide 10 stage 1 — Tomcat/GCP/DB are wired to the same
# BaseExtractor interface so stage 2 "Expand & harden" is a config change,
# not a rewrite).
# ---------------------------------------------------------------------------
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
CLOUDWATCH_LOG_GROUPS: List[str] = _list(
    "CLOUDWATCH_LOG_GROUPS", "/ecs/app-service,/aws/rds/instance/app-db/error"
)
CLOUDWATCH_FILTER_PATTERN = os.getenv("CLOUDWATCH_FILTER_PATTERN", "")
CLOUDWATCH_ENABLED = _bool("CLOUDWATCH_ENABLED", True)

TOMCAT_LOG_PATHS: List[str] = _list("TOMCAT_LOG_PATHS", "")
TOMCAT_ENABLED = _bool("TOMCAT_ENABLED", False)

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
GCP_LOG_FILTER = os.getenv("GCP_LOG_FILTER", "")
GCP_LOGGING_ENABLED = _bool("GCP_LOGGING_ENABLED", False)

DB_LOG_SOURCES: List[str] = _list("DB_LOG_SOURCES", "")  # e.g. "oracle:app,postgres:billing"
DB_LOGS_ENABLED = _bool("DB_LOGS_ENABLED", False)

# ---------------------------------------------------------------------------
# Correlation — identifiers an SRE would chase manually (business case slide 4)
# ---------------------------------------------------------------------------
CORRELATION_KEY_PATTERNS: Dict[str, str] = {
    "request_id": r"(?:request[_-]?id|req[_-]?id|x-request-id)[=:\s]+([a-zA-Z0-9\-]{8,})",
    "trace_id": r"(?:trace[_-]?id|x-b3-traceid|x-amzn-trace-id)[=:\s]+([a-zA-Z0-9\-]{8,})",
    "user_id": r"(?:user[_-]?id|uid)[=:\s]+([a-zA-Z0-9\-]{3,})",
    "error_code": r"(?:error[_-]?code|err[_-]?code|status)[=:\s]+([A-Z0-9_\-]{2,})",
    "service_name": r"(?:service[_-]?name|svc)[=:\s]+([a-zA-Z0-9\-_.]{2,})",
}

# Deterministic join window: events sharing an identifier within this many
# seconds are linked with confidence 1.0 before any LLM is invoked.
DETERMINISTIC_TIME_WINDOW_SECONDS = int(os.getenv("DETERMINISTIC_TIME_WINDOW_SECONDS", "300"))

# Semantic (LLM) fallback only runs on events that remain unlinked after the
# deterministic pass, and only within this bucket size — this is the
# "hybrid design" cost control called out in slide 5 / slide 9.
SEMANTIC_TIME_BUCKET_SECONDS = int(os.getenv("SEMANTIC_TIME_BUCKET_SECONDS", "120"))
SEMANTIC_MAX_BATCH_SIZE = int(os.getenv("SEMANTIC_MAX_BATCH_SIZE", "25"))
SEMANTIC_MIN_CONFIDENCE = float(os.getenv("SEMANTIC_MIN_CONFIDENCE", "0.55"))

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")  # "anthropic" | "openai"
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))

# ---------------------------------------------------------------------------
# Relationship Store (Postgres, graph-shaped: events + edges)
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/log_intelligence"
)

# ---------------------------------------------------------------------------
# Visualization UI
# ---------------------------------------------------------------------------
VIZ_HOST = os.getenv("VIZ_HOST", "0.0.0.0")
VIZ_PORT = int(os.getenv("VIZ_PORT", "8000"))


@dataclass
class Settings:
    aws_region: str = AWS_REGION
    cloudwatch_log_groups: List[str] = field(default_factory=lambda: CLOUDWATCH_LOG_GROUPS)
    cloudwatch_filter_pattern: str = CLOUDWATCH_FILTER_PATTERN
    cloudwatch_enabled: bool = CLOUDWATCH_ENABLED
    tomcat_enabled: bool = TOMCAT_ENABLED
    gcp_logging_enabled: bool = GCP_LOGGING_ENABLED
    db_logs_enabled: bool = DB_LOGS_ENABLED
    database_url: str = DATABASE_URL


settings = Settings()
