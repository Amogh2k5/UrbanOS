"""Crime Agent: official-data ingestion -> deterministic processing -> CrimeReport."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from langgraph.graph import END, StateGraph

from backend.app.safety.crime.data import DataGovCrimeClient
from backend.app.safety.crime.models import CrimeReport
from backend.app.safety.crime.processing import process_snapshot


@dataclass
class CrimeAgentState:
    snapshot: Any = None
    report: Optional[CrimeReport] = None
    errors: list[str] = field(default_factory=list)


def ingest_crime_data(state: CrimeAgentState) -> CrimeAgentState:
    state.snapshot = DataGovCrimeClient().fetch_all()
    return state


def analyze_crime(state: CrimeAgentState) -> CrimeAgentState:
    if state.snapshot is None:
        raise RuntimeError("Crime data snapshot was not created")
    state.report = process_snapshot(state.snapshot)
    return state


def create_crime_agent() -> StateGraph:
    graph = StateGraph(CrimeAgentState)
    graph.add_node("ingest_crime_data", ingest_crime_data)
    graph.add_node("analyze_crime", analyze_crime)
    graph.set_entry_point("ingest_crime_data")
    graph.add_edge("ingest_crime_data", "analyze_crime")
    graph.add_edge("analyze_crime", END)
    return graph


def run_crime_agent() -> CrimeReport:
    result = create_crime_agent().compile().invoke(CrimeAgentState())
    report = result.get("report")
    if report is None:
        raise RuntimeError("Crime Agent did not produce a CrimeReport")
    return report
