"""
ORM models for the Relationship Store. Two tables model the graph
directly: log_events are nodes, correlation_edges are edges — this is
what lets slide 9's concern ("tree may oversimplify... may need a
graph/DAG view") be a query change, not a schema change.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LogEventORM(Base):
    __tablename__ = "log_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_system: Mapped[str] = mapped_column(String(32), nullable=False)
    origin: Mapped[str] = mapped_column(String(512), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    identifiers: Mapped[dict] = mapped_column(JSONB, default=dict)
    host: Mapped[str] = mapped_column(String(256), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_log_events_timestamp", "timestamp"),
        Index("ix_log_events_source_system", "source_system"),
        Index("ix_log_events_identifiers", "identifiers", postgresql_using="gin"),
    )


class CorrelationEdgeORM(Base):
    __tablename__ = "correlation_edges"

    edge_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("log_events.event_id", ondelete="CASCADE"), nullable=False
    )
    target_event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("log_events.event_id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    matched_on: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_edges_source", "source_event_id"),
        Index("ix_edges_target", "target_event_id"),
    )
