"""LangGraph Fire/Safety agent.

Pipeline:
SCDF/data.gov.sg sources -> normalization -> deterministic classification ->
FireReport. No predictive ML is used.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from langgraph.graph import END, StateGraph

from backend.app.safety.fire.api import fetch_fire_snapshot
from backend.app.safety.fire.models import FireIncident, FireReport

log = logging.getLogger(__name__)
SG = timezone(timedelta(hours=8))
REGIONS = ("Central", "East", "North", "South", "West")


@dataclass
class FireAgentState:
    incidents: List[FireIncident] = field(default_factory=list)
    historical: List[Any] = field(default_factory=list)
    source_status: str = "unavailable"
    data_sources: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    report: Optional[FireReport] = None


def ingest_fire_data(state: FireAgentState) -> FireAgentState:
    snapshot = fetch_fire_snapshot()
    state.incidents = snapshot.incidents
    state.historical = snapshot.historical
    state.source_status = snapshot.source_status
    state.data_sources = snapshot.data_sources
    state.limitations = snapshot.limitations
    state.warnings = snapshot.warnings
    state.errors = snapshot.errors
    return state


def analyze_fire(state: FireAgentState) -> FireAgentState:
    # Only source-reported/published status is used. Unknown stays unknown.
    today = datetime.now(SG).date()
    active = [i for i in state.incidents if i.status == "ACTIVE"]
    resolved = [i for i in state.incidents if i.status == "RESOLVED"]
    today_incidents = [
        i for i in state.incidents
        if i.reported_at is not None and i.reported_at.astimezone(SG).date() == today
    ]
    critical = [i for i in active if i.severity == "CRITICAL"]

    regional = {r: 0 for r in REGIONS}
    for i in state.incidents:
        if i.region in regional:
            regional[i.region] += 1

    # If the published feed has records, zero is meaningful within that feed's
    # scope. If it has no records, active KPIs remain None to avoid false claims.
    feed_available = bool(state.incidents)
    state.report = FireReport(
        generated_at=datetime.now(SG),
        active_incidents=active,
        recent_incidents=state.incidents,
        active_incident_count=len(active) if feed_available else None,
        critical_incident_count=len(critical) if feed_available else None,
        incidents_today=len(today_incidents) if feed_available else None,
        resolved_recent_count=len(resolved) if feed_available else None,
        regional_counts=regional if feed_available else {r: None for r in REGIONS},
        historical_fire_counts=state.historical,
        source_status=state.source_status,
        data_sources=state.data_sources,
        limitations=state.limitations,
        warnings=state.warnings,
        errors=state.errors,
        is_ml_prediction=False,
    )
    return state


def build_report(state: FireAgentState) -> FireAgentState:
    if state.report is None:
        return analyze_fire(state)
    return state


def create_fire_agent() -> StateGraph:
    graph = StateGraph(FireAgentState)
    graph.add_node("ingest_fire_data", ingest_fire_data)
    graph.add_node("analyze_fire", analyze_fire)
    graph.add_node("build_report", build_report)
    graph.set_entry_point("ingest_fire_data")
    graph.add_edge("ingest_fire_data", "analyze_fire")
    graph.add_edge("analyze_fire", "build_report")
    graph.add_edge("build_report", END)
    return graph


def run_fire_agent() -> FireReport:
    state = FireAgentState()
    result = create_fire_agent().compile().invoke(state)
    return result["report"]
