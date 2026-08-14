"""
Visualization UI (architecture slide 5, final stage): "Interactive tree /
graph of one incident across all systems."

A small FastAPI service: one page (templates/index.html) rendering an
interactive, force-directed graph via vis-network, backed by two JSON
endpoints that read straight from the Relationship Store.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from storage.relationship_store import RelationshipStore
from visualization.graph_builder import build_graph_json

app = FastAPI(title="AI-Correlated Log Intelligence — Visualization UI")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
store = RelationshipStore()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/incidents")
def api_incidents():
    """List every incident (connected component) currently in the
    Relationship Store, most systems/events-involved first."""
    return store.list_incidents()


@app.get("/api/graph")
def api_graph(incident_id: str = Query(default=None, description="Restrict to one incident; omit for the full graph")):
    graph = store.load_graph()

    if incident_id is None:
        return build_graph_json(graph)

    incidents = store.list_incidents()
    match = next((i for i in incidents if i["incident_id"] == incident_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident_id: {incident_id}")
    return build_graph_json(graph, event_ids=set(match["event_ids"]))


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
