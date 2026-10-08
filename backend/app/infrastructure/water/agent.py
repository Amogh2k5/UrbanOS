"""LangGraph Water agent.

Pipeline:
  official sources -> acquisition/validation -> deterministic processing ->
  WaterReport (+ rule-based insights that answer the standard Water questions).

No ML model is used; see processing.build_forecast_section for why.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

from langgraph.graph import END, StateGraph

from backend.app.infrastructure.water.models import (
    DrainReading, WaterInsight, WaterReport,
)
from backend.app.infrastructure.water.processing import (
    DrainReadingProvider, build_alerts, build_drain_section, build_forecast_section,
    build_newater_section, build_quality_section, build_supply_section, build_usage_section,
    overall_from_drain,
)
from backend.app.infrastructure.water.sources import WaterSnapshot, fetch_water_snapshot

log = logging.getLogger(__name__)
SG = timezone(timedelta(hours=8))


@dataclass
class WaterAgentState:
    snapshot: Optional[WaterSnapshot] = None
    readings: List[DrainReading] = field(default_factory=list)
    reading_errors: List[str] = field(default_factory=list)
    report: Optional[WaterReport] = None
    # Injected for tests / future live provider.
    fetcher: Callable[[], WaterSnapshot] = fetch_water_snapshot
    reading_provider: Optional[DrainReadingProvider] = None


def ingest_water_data(state: WaterAgentState) -> WaterAgentState:
    state.snapshot = state.fetcher()
    if state.reading_provider is not None:
        try:
            state.readings = state.reading_provider.fetch()
        except Exception as exc:  # noqa: BLE001
            log.warning("Drain reading provider failed: %s", exc)
            state.reading_errors.append(f"Drain readings provider failed: {exc}")
    return state


def _fmt(v: Optional[float], unit: str = "") -> str:
    return "n/a" if v is None else f"{v:g}{(' ' + unit) if unit else ''}"


def _build_insights(report: WaterReport) -> List[WaterInsight]:
    u, s, d, n, q = report.usage, report.supply, report.drain, report.newater, report.quality
    out: List[WaterInsight] = []

    # 1. Supply status
    if s.status == "SALES_DATA_ONLY":
        parts = [f"{i.label}: {_fmt(i.value, i.unit)} ({i.period})" for i in s.indicators]
        out.append(WaterInsight(
            question="What is the current/latest water supply status?",
            answer=("Reservoir storage levels are not published as open data, so live supply status cannot be stated. "
                    "Latest ANNUAL supply-side sales: " + "; ".join(parts) + "."),
            data_kind="latest_available"))
    else:
        out.append(WaterInsight(question="What is the current/latest water supply status?",
                                answer="Supply indicators are unavailable right now.", data_kind="unavailable"))

    # 2 + 3. Drains
    if d.readings_available:
        elevated = [x for x in d.sensors if x.condition in ("ELEVATED", "HIGH", "CRITICAL")]
        ans = (f"{d.sensors_with_readings} of {d.sensor_count} sensors have readings; "
               f"{len(elevated)} show elevated or worse conditions.")
        out.append(WaterInsight(question="What is happening with drain conditions?", answer=ans, data_kind="live"))
        out.append(WaterInsight(question="Are any monitored drains showing elevated conditions?",
                                answer=("Yes: " + ", ".join(f"{x.sensor.name or x.sensor.id} ({x.condition}, {x.percentage}%)" for x in elevated[:5])) if elevated else "No sensor is currently above 75% of its reference depth.",
                                data_kind="live"))
    else:
        ans = (f"{d.sensor_count} PUB drain/canal sensor locations are known, but no official live water-level readings are "
               "available, so drain condition cannot be assessed." if d.sensor_count else
               "Neither sensor locations nor readings are available.")
        out.append(WaterInsight(question="What is happening with drain conditions?", answer=ans, data_kind="unavailable"))
        out.append(WaterInsight(question="Are any monitored drains showing elevated conditions?",
                                answer="Unknown - there are no official live readings. Absence of data is not evidence that drains are normal.",
                                data_kind="unavailable"))

    # 4. Usage change
    if u.potable_total:
        t = u.potable_total
        bits = [f"Total potable sales {_fmt(t.value, t.unit)} in {t.period}"]
        if t.change_pct is not None:
            bits.append(f"{t.change_pct:+.1f}% vs {t.previous_period}")
        if u.domestic_share_pct is not None:
            bits.append(f"domestic {u.domestic_share_pct}% / non-domestic {u.non_domestic_share_pct}%")
        out.append(WaterInsight(question="How is water usage changing?", answer="; ".join(bits) + " (annual data).", data_kind="historical"))
    else:
        out.append(WaterInsight(question="How is water usage changing?", answer="Usage data unavailable.", data_kind="unavailable"))

    # 5. Forecast
    out.append(WaterInsight(question="What is the expected future water usage?",
                            answer="No forecast is produced. " + report.forecast.reason, data_kind="unavailable"))

    # 6. Latest indicators
    latest = []
    if n.latest:
        latest.append(f"NEWater {_fmt(n.latest.value, n.latest.unit)} ({n.latest.period})")
    if q.reporting_period:
        for p in q.parameters:
            if p.key in ("ph", "turbidity", "ecoli"):
                latest.append(f"{p.parameter.strip()} avg {p.average} {p.unit} ({p.compliance.replace('_', ' ').lower()})")
    out.append(WaterInsight(question="What are the latest available water indicators?",
                            answer="; ".join(latest) + "." if latest else "No indicators available.", data_kind="latest_available"))

    # 7. Change from previous period
    changes = [f"{i.label} {i.change_pct:+.1f}% ({i.previous_period}->{i.period})"
               for i in (u.potable_total, u.domestic, u.non_domestic, n.latest) if i and i.change_pct is not None]
    out.append(WaterInsight(question="What has changed from the previous period?",
                            answer="; ".join(changes) + "." if changes else "No previous-period comparison available.",
                            data_kind="historical"))
    return out


def analyze_water(state: WaterAgentState) -> WaterAgentState:
    snap = state.snapshot or WaterSnapshot(generated_at=datetime.now(SG))
    usage = build_usage_section(snap)
    newater = build_newater_section(snap)
    supply = build_supply_section(snap, usage, newater)
    quality = build_quality_section(snap)
    sensors_info = next((s for s in snap.sources if s.key == "drain_sensors"), None)
    drain = build_drain_section(
        snap.sensors, snap.invalid_sensors, state.readings,
        sensors_source_ok=not (sensors_info and sensors_info.status == "stale_cache"),
    )
    forecast = build_forecast_section(usage)
    status, risk = overall_from_drain(drain)
    alerts = build_alerts(usage, newater, quality, drain)

    ok_sources = sum(1 for s in snap.sources if s.status == "ok")
    if drain.readings_available and ok_sources >= 4:
        confidence = "high"
    elif ok_sources >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    limitations = [
        "No official live drain water-level readings or reservoir-storage feed was found; drain condition and "
        "live supply status are therefore reported as unavailable, not as normal.",
        "Usage, NEWater and quality data are annual/periodic official statistics, not real-time measurements.",
        "Water does not assess rainfall or flood risk; see the Flood & Rainfall module.",
    ]
    report = WaterReport(
        generated_at=datetime.now(SG),
        overall_status=status, overall_risk=risk,  # type: ignore[arg-type]
        supply=supply, drain=drain, usage=usage, forecast=forecast, newater=newater, quality=quality,
        alerts=alerts, sources=snap.sources,
        data_timestamps={
            s.key: {
                "last_fetched_at": s.last_fetched_at.isoformat() if s.last_fetched_at else None,
                "latest_data_period": s.latest_data_period,
                "status": s.status,
            } for s in snap.sources
        },
        confidence=confidence,  # type: ignore[arg-type]
        limitations=limitations,
        warnings=list(snap.warnings),
        errors=list(snap.errors) + list(state.reading_errors),
        is_ml_prediction=False,
    )
    report.insights = _build_insights(report)
    state.report = report
    return state


def build_report(state: WaterAgentState) -> WaterAgentState:
    if state.report is None:
        return analyze_water(state)
    return state


def create_water_agent() -> StateGraph:
    graph = StateGraph(WaterAgentState)
    graph.add_node("ingest_water_data", ingest_water_data)
    graph.add_node("analyze_water", analyze_water)
    graph.add_node("build_report", build_report)
    graph.set_entry_point("ingest_water_data")
    graph.add_edge("ingest_water_data", "analyze_water")
    graph.add_edge("analyze_water", "build_report")
    graph.add_edge("build_report", END)
    return graph


def run_water_agent(
    fetcher: Optional[Callable[[], WaterSnapshot]] = None,
    reading_provider: Optional[DrainReadingProvider] = None,
) -> WaterReport:
    """Run the agent. Never raises for source failures - they become report.errors."""
    state = WaterAgentState(reading_provider=reading_provider)
    if fetcher is not None:
        state.fetcher = fetcher
    result = create_water_agent().compile().invoke(state)
    return result["report"]
