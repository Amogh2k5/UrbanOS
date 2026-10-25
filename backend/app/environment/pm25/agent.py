"""PM2.5 observation graph over the shared, provenance-carrying live snapshot."""
from __future__ import annotations

from typing import Any, Dict, TypedDict
from langgraph.graph import END, START, StateGraph


class Pm25State(TypedDict, total=False):
    report: Dict[str, Any]
    errors: list[str]


def fetch_pm25(state: Pm25State) -> Dict[str, Any]:
    from backend.app.environment.pm25.live_service import get_pm25_live_service
    snapshot = get_pm25_live_service().snapshot()
    if snapshot is None:
        return {"report": {"error": "No PM2.5 observation snapshot is available"}}
    report = snapshot.to_dict()
    report["generated_at"] = snapshot.snapshot_at
    report["source_status"] = "live" if snapshot.is_live else "stored_snapshot"
    report["timestamp"] = snapshot.raw_issue_timestamp or snapshot.snapshot_at
    return {"report": report}


def validate_pm25(state: Pm25State) -> Dict[str, Any]:
    report = state.get("report") or {}
    regions = report.get("regions")
    if not isinstance(regions, dict) or not regions:
        return {"report": {"error": "PM2.5 snapshot has no regional observations"}}
    values = [row.get("value") for row in regions.values() if isinstance(row, dict)]
    if not any(isinstance(value, (int, float)) for value in values):
        return {"report": {"error": "PM2.5 snapshot has no numeric regional observations"}}
    return {"report": report}


def build_pm25_graph():
    graph = StateGraph(Pm25State)
    graph.add_node("fetch", fetch_pm25)
    graph.add_node("validate", validate_pm25)
    graph.add_edge(START, "fetch")
    graph.add_edge("fetch", "validate")
    graph.add_edge("validate", END)
    return graph.compile()


_GRAPH = None
def get_pm25_agent():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_pm25_graph()
    return _GRAPH


def run_pm25_agent():
    return get_pm25_agent().invoke({}).get("report", {})
