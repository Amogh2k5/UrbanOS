"""Weather domain graph over the official NEA forecast client."""
from __future__ import annotations

from typing import Any, Dict, TypedDict
from langgraph.graph import END, START, StateGraph


class WeatherState(TypedDict, total=False):
    report: Dict[str, Any]
    errors: list[str]


def fetch_weather(state: WeatherState) -> Dict[str, Any]:
    from backend.app.environment.weather.api import WeatherApiClient
    snapshot = WeatherApiClient(allow_fallback_fixture=False).fetch()
    report = snapshot.to_dict()
    report["generated_at"] = report.get("snapshot_at")
    report["source_status"] = "live" if snapshot.is_live else "unavailable"
    return {"report": report}


def validate_weather(state: WeatherState) -> Dict[str, Any]:
    report = state.get("report") or {}
    general = report.get("general")
    if not isinstance(general, dict) or not general.get("forecast_code"):
        return {"report": {"error": "NEA weather forecast contains no valid general forecast"}}
    if report.get("source_status") != "live":
        return {"report": {"error": "Weather forecast is not confirmed as live"}}
    return {"report": report}


def build_weather_graph():
    graph = StateGraph(WeatherState)
    graph.add_node("fetch", fetch_weather)
    graph.add_node("validate", validate_weather)
    graph.add_edge(START, "fetch")
    graph.add_edge("fetch", "validate")
    graph.add_edge("validate", END)
    return graph.compile()


_GRAPH = None
def get_weather_agent():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_weather_graph()
    return _GRAPH


def run_weather_agent():
    return get_weather_agent().invoke({}).get("report", {})
