-- Relationship Store DDL (reference copy of storage/models.py).
-- RelationshipStore.create_schema() applies this automatically via
-- SQLAlchemy; kept here for manual review / DBA sign-off since this is
-- the one component of the architecture with real infra cost implications.

CREATE TABLE IF NOT EXISTS log_events (
    event_id        VARCHAR(36) PRIMARY KEY,
    source_system   VARCHAR(32)  NOT NULL,
    origin          VARCHAR(512) NOT NULL,
    "timestamp"     TIMESTAMPTZ  NOT NULL,
    level           VARCHAR(16),
    message         TEXT         NOT NULL,
    identifiers     JSONB        NOT NULL DEFAULT '{}'::jsonb,
    host            VARCHAR(256),
    ingested_at     TIMESTAMPTZ  NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_log_events_timestamp ON log_events ("timestamp");
CREATE INDEX IF NOT EXISTS ix_log_events_source_system ON log_events (source_system);
CREATE INDEX IF NOT EXISTS ix_log_events_identifiers ON log_events USING gin (identifiers);

CREATE TABLE IF NOT EXISTS correlation_edges (
    edge_id           VARCHAR(36) PRIMARY KEY,
    source_event_id   VARCHAR(36) NOT NULL REFERENCES log_events(event_id) ON DELETE CASCADE,
    target_event_id   VARCHAR(36) NOT NULL REFERENCES log_events(event_id) ON DELETE CASCADE,
    relation_type     VARCHAR(32) NOT NULL, -- id_match | time_window | semantic_similarity
    confidence        FLOAT       NOT NULL DEFAULT 1.0,
    matched_on        TEXT,
    created_at        TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_edges_source ON correlation_edges (source_event_id);
CREATE INDEX IF NOT EXISTS ix_edges_target ON correlation_edges (target_event_id);
