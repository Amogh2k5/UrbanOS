"""Transit domain graph over the existing persisted LTA reference and alert data."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, TypedDict
from langgraph.graph import END, START, StateGraph


class TransitState(TypedDict, total=False):
    report: Dict[str, Any]
    errors: list[str]


def fetch_transit_status(state: TransitState) -> Dict[str, Any]:
    from backend.app.mobility.transit.data import TransitDataStore
    store = TransitDataStore()
    stats = store.get_stats()
    alerts = store.get_latest_train_alerts(limit=60)
    train_alerts = [a for a in alerts if a.category in ("metro", "rail")]
    return {"report": {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "bus_services_count": stats.get("bus_services"),
        "bus_routes_count": stats.get("bus_routes"),
        "bus_stops_count": stats.get("bus_stops"),
        "active_train_alerts": len(train_alerts),
        "train_alerts": [{"line": a.line, "direction": a.direction,
                           "station": a.station, "message": a.message,
                           "status": a.status} for a in train_alerts],
        "limitations": ["Bus arrival predictions are not available from the configured LTA account.",
                        "Transit status reflects stored reference data and collected train alerts."],
    }}


def validate_transit(state: TransitState) -> Dict[str, Any]:
    report = state.get("report") or {}
    if report.get("active_train_alerts") is None:
        return {"report": {"error": "Transit alert summary is unavailable"}}
    return {"report": report}


def build_transit_graph():
    graph = StateGraph(TransitState)
    graph.add_node("fetch", fetch_transit_status)
    graph.add_node("validate", validate_transit)
    graph.add_edge(START, "fetch")
    graph.add_edge("fetch", "validate")
    graph.add_edge("validate", END)
    return graph.compile()


_GRAPH = None
def get_transit_agent():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_transit_graph()
    return _GRAPH


def run_transit_agent():
    return get_transit_agent().invoke({}).get("report", {})
