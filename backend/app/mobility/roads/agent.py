"""Roads domain LangGraph built around the existing LTA aggregator."""
from __future__ import annotations

from typing import Any, Dict, TypedDict
from langgraph.graph import END, START, StateGraph


class RoadsState(TypedDict, total=False):
    report: Dict[str, Any]
    errors: list[str]
    warnings: list[str]


def fetch_roads(state: RoadsState) -> Dict[str, Any]:
    from backend.app.mobility.roads.aggregator import get_roads_snapshot
    return {"report": get_roads_snapshot()}


def validate_roads(state: RoadsState) -> Dict[str, Any]:
    report = state.get("report") or {}
    works = report.get("road_works")
    if not isinstance(works, dict) or works.get("active") is None:
        reason = "; ".join(report.get("warnings") or []) or "LTA road works summary is unavailable"
        return {"report": {"error": reason, "warnings": report.get("warnings", [])}}
    return {"report": report}


def build_roads_graph():
    graph = StateGraph(RoadsState)
    graph.add_node("fetch", fetch_roads)
    graph.add_node("validate", validate_roads)
    graph.add_edge(START, "fetch")
    graph.add_edge("fetch", "validate")
    graph.add_edge("validate", END)
    return graph.compile()


_GRAPH = None
def get_roads_agent():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_roads_graph()
    return _GRAPH


def run_roads_agent():
    return get_roads_agent().invoke({}).get("report", {})
