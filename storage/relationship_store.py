"""
High-level API over the Relationship Store: persist normalized events +
inferred links, and read them back grouped into incidents (connected
components of the correlation graph) for the Visualization UI.
"""
from __future__ import annotations

import logging
from typing import Dict, List

import networkx as nx
from sqlalchemy.dialects.postgresql import insert as pg_insert

from models.schema import CorrelationEdge, LogEvent
from storage.db import get_session
from storage.models import Base, CorrelationEdgeORM, LogEventORM

logger = logging.getLogger(__name__)


class RelationshipStore:
    def __init__(self):
        from storage.db import get_engine

        self._engine = get_engine()

    def create_schema(self) -> None:
        Base.metadata.create_all(self._engine)

    def save_events(self, events: List[LogEvent]) -> None:
        if not events:
            return
        rows = [
            dict(
                event_id=e.event_id,
                source_system=e.source_system,
                origin=e.origin,
                timestamp=e.timestamp,
                level=e.level,
                message=e.message,
                identifiers=e.identifiers,
                host=e.host,
                ingested_at=e.ingested_at,
            )
            for e in events
        ]
        with get_session() as session:
            stmt = pg_insert(LogEventORM).values(rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=["event_id"])
            session.execute(stmt)
        logger.info("Persisted %d log events", len(events))

    def save_edges(self, edges: List[CorrelationEdge]) -> None:
        if not edges:
            return
        rows = [
            dict(
                edge_id=edge.edge_id,
                source_event_id=edge.source_event_id,
                target_event_id=edge.target_event_id,
                relation_type=edge.relation_type,
                confidence=edge.confidence,
                matched_on=edge.matched_on,
                created_at=edge.created_at,
            )
            for edge in edges
        ]
        with get_session() as session:
            stmt = pg_insert(CorrelationEdgeORM).values(rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=["edge_id"])
            session.execute(stmt)
        logger.info("Persisted %d correlation edges", len(edges))

    def load_graph(self) -> nx.Graph:
        """Loads the full events+edges graph from Postgres into an
        in-memory networkx graph — used both to compute incidents
        (connected components) and to serve the visualization API."""
        graph = nx.Graph()
        with get_session() as session:
            for row in session.query(LogEventORM).all():
                graph.add_node(
                    row.event_id,
                    source_system=row.source_system,
                    origin=row.origin,
                    timestamp=row.timestamp.isoformat(),
                    level=row.level,
                    message=row.message,
                    identifiers=row.identifiers,
                    host=row.host,
                )
            for row in session.query(CorrelationEdgeORM).all():
                if row.source_event_id in graph and row.target_event_id in graph:
                    graph.add_edge(
                        row.source_event_id,
                        row.target_event_id,
                        relation_type=row.relation_type,
                        confidence=row.confidence,
                        matched_on=row.matched_on,
                    )
        return graph

    def list_incidents(self) -> List[Dict]:
        """An 'incident' is a connected component of the correlation
        graph: one root cause, every system it touched. This directly
        implements slide 9's takeaway that real relationships are
        many-to-many, so incidents are graph components rather than a
        forced tree."""
        graph = self.load_graph()
        incidents = []
        for i, component in enumerate(nx.connected_components(graph)):
            nodes = [graph.nodes[n] for n in component]
            sources = sorted({n["source_system"] for n in nodes})
            timestamps = sorted(n["timestamp"] for n in nodes)
            incidents.append(
                {
                    "incident_id": f"incident-{i}",
                    "event_ids": list(component),
                    "event_count": len(component),
                    "sources_involved": sources,
                    "start_time": timestamps[0] if timestamps else None,
                    "end_time": timestamps[-1] if timestamps else None,
                }
            )
        incidents.sort(key=lambda x: x["event_count"], reverse=True)
        return incidents
