"""
Common data contracts shared by every stage of the pipeline.

RawLogRecord  -> produced by extraction/*  (Log Sources stage)
LogEvent      -> produced by normalization/normalizer.py (Ingestion & Normalization stage)
CorrelationEdge -> produced by correlation/* (LangChain Correlation Agents stage)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SourceSystem(str, Enum):
    CLOUDWATCH = "cloudwatch"
    TOMCAT = "tomcat"
    GCP_LOGGING = "gcp_logging"
    ORACLE = "oracle"
    MYSQL = "mysql"
    POSTGRES = "postgres"


class RawLogRecord(BaseModel):
    """Unopinionated payload straight off the wire from a Log Source."""

    source_system: SourceSystem
    origin: str  # log group/stream name, file path, table name, etc.
    raw_payload: Dict[str, Any]
    fetched_at: datetime = Field(default_factory=utcnow)


class LogEvent(BaseModel):
    """
    Standardized event shape every downstream stage (correlation, storage,
    visualization) operates on — this is the output of "Ingestion &
    Normalization" in the architecture diagram.
    """

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_system: SourceSystem
    origin: str
    timestamp: datetime  # normalized to UTC
    level: Optional[str] = None
    message: str
    identifiers: Dict[str, str] = Field(default_factory=dict)
    host: Optional[str] = None
    ingested_at: datetime = Field(default_factory=utcnow)

    class Config:
        use_enum_values = True


class RelationType(str, Enum):
    ID_MATCH = "id_match"
    TIME_WINDOW = "time_window"
    SEMANTIC_SIMILARITY = "semantic_similarity"


class CorrelationEdge(BaseModel):
    """One inferred relationship between two LogEvents — an edge in the
    Relationship Store graph."""

    edge_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_event_id: str
    target_event_id: str
    relation_type: RelationType
    confidence: float = 1.0
    matched_on: str = ""  # e.g. "request_id" or LLM rationale
    created_at: datetime = Field(default_factory=utcnow)

    class Config:
        use_enum_values = True
