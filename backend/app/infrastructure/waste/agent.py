"""WasteManagementAgent (LangGraph).

Pipeline:
  official sources -> acquisition/validation -> deterministic analytics -> WasteReport
  (+ rule-based insights that answer the standard Waste Management questions).

The agent only *reads* the structured analytics: every sentence it writes is assembled from
numbers already present in the report, so it cannot introduce a statistic the data does not
contain.  No ML model is used; see ``processing.build_forecast_section`` for why.
Cross-domain reasoning belongs to the City Coordinator, not here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

from langgraph.graph import END, StateGraph

from backend.app.infrastructure.waste import processing as P
from backend.app.infrastructure.waste.models import WasteInsight, WasteReport
from backend.app.infrastructure.waste.sources import WasteSnapshot, fetch_waste_snapshot

log = logging.getLogger(__name__)
SG = timezone(timedelta(hours=8))


def _mt(tonnes: Optional[float]) -> str:
    """Tonnes -> 'N.NN million tonnes', rounded half-up (binary floats would turn 7.015 into 7.01)."""
    if tonnes is None:
        return "n/a"
    mt = (Decimal(str(tonnes)) / Decimal(1_000_000)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{mt} million tonnes"


def _pct(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{v:g}%"


def _kpi(report: WasteReport, key: str):
    return next((k for k in report.kpis if k.key == key), None)


def _build_summary(report: WasteReport) -> str:
    gen, rec, dis, rate = (_kpi(report, k) for k in ("total_generated", "total_recycled", "total_disposed", "overall_recycling_rate"))
    if not gen or gen.value is None:
        return "Official waste statistics are currently unavailable."
    y = gen.period
    parts = [f"Singapore generated {_mt(gen.value)} of waste in {y}"]
    if rec and rec.value is not None and rate and rate.value is not None:
        parts.append(f"of which {_mt(rec.value)} ({_pct(rate.value)}) was recycled")
    if dis and dis.value is not None:
        parts.append(f"and {_mt(dis.value)} was disposed of")
    text = ", ".join(parts) + "."
    if rate and rate.change_abs is not None:
        text += f" The recycling rate moved {rate.change_abs:+g} percentage points from {rate.previous_period}."
    text += " These are annual national statistics, not live measurements."
    return text


def _build_insights(report: WasteReport) -> List[WasteInsight]:
    g, c, f, s, inf = report.generation, report.categories, report.food, report.services, report.infrastructure
    out: List[WasteInsight] = []

    # 1. Latest picture
    if report.kpis and report.kpis[0].value is not None:
        out.append(WasteInsight(question="What is the latest national waste picture?", answer=report.summary, data_kind="latest_available"))
    else:
        out.append(WasteInsight(question="What is the latest national waste picture?",
                                answer="Official waste statistics are unavailable right now.", data_kind="unavailable"))

    # 2. Generation trend
    gen_k = _kpi(report, "total_generated")
    if gen_k and gen_k.value is not None:
        bits = []
        if gen_k.change_pct is not None:
            bits.append(f"{gen_k.change_pct:+.1f}% vs {gen_k.previous_period}")
        if g.peak_generated_year and g.generated_change_since_peak_pct is not None:
            bits.append(f"{g.generated_change_since_peak_pct:+.1f}% vs the series peak of {_mt(g.peak_generated_tonnes)} in {g.peak_generated_year}")
        out.append(WasteInsight(question="How has waste generation changed?",
                                answer=f"Total waste generated was {_mt(gen_k.value)} in {gen_k.period}"
                                       + (": " + "; ".join(bits) if bits else "") + ".", data_kind="historical"))
    else:
        out.append(WasteInsight(question="How has waste generation changed?", answer="Generation trend unavailable.", data_kind="unavailable"))

    # 3. Recycling rate
    rate_k, ex_k = _kpi(report, "overall_recycling_rate"), _kpi(report, "recycling_rate_excl_cd")
    if rate_k and rate_k.value is not None:
        bits = [f"Overall recycling rate {_pct(rate_k.value)} in {rate_k.period}"]
        if rate_k.change_abs is not None:
            bits.append(f"{rate_k.change_abs:+g} pp vs {rate_k.previous_period}")
        if g.peak_recycling_rate_pct is not None:
            bits.append(f"published peak {_pct(g.peak_recycling_rate_pct)} in {g.peak_recycling_rate_year}")
        if ex_k and ex_k.value is not None:
            bits.append(f"{_pct(ex_k.value)} excluding construction & demolition waste")
        out.append(WasteInsight(question="How is recycling performing?", answer="; ".join(bits) + ".", data_kind="historical"))
    else:
        out.append(WasteInsight(question="How is recycling performing?", answer="Recycling rate unavailable.", data_kind="unavailable"))

    # 4. Disposal
    dis_k = _kpi(report, "total_disposed")
    if dis_k and dis_k.value is not None:
        txt = f"{_mt(dis_k.value)} of waste was disposed of in {dis_k.period}"
        if dis_k.change_pct is not None:
            txt += f" ({dis_k.change_pct:+.1f}% vs {dis_k.previous_period})"
        if g.disposed_is_series_high:
            txt += ", the highest level in the series"
        out.append(WasteInsight(question="How much waste is disposed of?", answer=txt + ".", data_kind="historical"))

    # 5. Which categories are least recycled
    rows = {r.key: r for r in c.rows}
    if c.top_disposed:
        parts = []
        for k in c.top_disposed[:4]:
            r = rows[k]
            parts.append(f"{r.label} ({_mt(r.disposed)} disposed, {_pct(r.recycling_rate_computed)} recycled)")
        out.append(WasteInsight(question="Which waste types make up most of what is disposed of?",
                                answer=f"In {c.latest_year}: " + "; ".join(parts) + ".", data_kind="historical"))
    else:
        out.append(WasteInsight(question="Which waste types make up most of what is disposed of?",
                                answer="Waste-type breakdown unavailable.", data_kind="unavailable"))

    # 6. Food waste
    if f.generated and f.generated.value is not None:
        txt = (f"Food waste: {_mt(f.generated.value)} generated in {f.latest_year}, recycling rate "
               f"{_pct(f.recycling_rate.value if f.recycling_rate else None)}")
        if f.share_of_total_disposed_pct is not None:
            txt += f"; food makes up {f.share_of_total_disposed_pct:g}% of all waste disposed of"
        out.append(WasteInsight(question="What is the food-waste situation?", answer=txt + ".", data_kind="historical"))
    else:
        out.append(WasteInsight(question="What is the food-waste situation?", answer="Food-waste data unavailable.", data_kind="unavailable"))

    # 7. Services and infrastructure
    bits = []
    if s.licensee_count is not None:
        bits.append(f"{s.licensee_count} NEA-licensed general waste collectors ({', '.join(f'{x.label}: {x.licensees}' for x in s.classes)})")
    if inf.map_available:
        bits.append("; ".join(f"{k.count} {k.label.lower()}" for k in inf.kinds if k.count))
    loading = [k.label.lower() for k in inf.kinds if k.status == "loading"]
    if bits:
        answer = "; ".join(bits) + ". These are reference listings, not live service data."
        if loading:
            answer += f" Still downloading: {', '.join(loading)}."
    elif loading:
        answer = f"Location listings are still downloading from data.gov.sg ({', '.join(loading)}); they will appear automatically."
    else:
        answer = "Service and infrastructure listings unavailable."
    out.append(WasteInsight(
        question="What waste services and infrastructure are on record?", answer=answer,
        data_kind="reference" if bits else "unavailable"))

    # 8. Limits
    out.append(WasteInsight(
        question="What cannot be assessed from the data?",
        answer="No forecast is produced. " + report.forecast.reason + " Also unavailable: "
               + "; ".join(m.label.lower() for m in report.unavailable_metrics if m.key != "forecast") + ".",
        data_kind="unavailable"))
    return out


@dataclass
class WasteAgentState:
    snapshot: Optional[WasteSnapshot] = None
    report: Optional[WasteReport] = None
    # Injected for tests.
    fetcher: Callable[[], WasteSnapshot] = lambda: fetch_waste_snapshot(wait_for_layers=False)


def ingest_waste_data(state: WasteAgentState) -> WasteAgentState:
    state.snapshot = state.fetcher()
    return state


def analyze_waste(state: WasteAgentState) -> WasteAgentState:
    snap = state.snapshot or WasteSnapshot(generated_at=datetime.now(SG))
    now = datetime.now(SG)
    table = snap.table
    year = P.latest_complete_year(table) if table else None

    if table is not None and year is not None:
        kpis = P.build_kpis(table, year)
        generation = P.build_generation_section(table, year)
        categories = P.build_category_section(table, year)
        food = P.build_food_section(table, year)
        dq = P.build_data_quality(table)
    else:
        from backend.app.infrastructure.waste.models import (
            CategorySection, DataQualitySection, FoodSection, GenerationSection,
        )
        kpis, generation, categories, food, dq = [], GenerationSection(), CategorySection(), FoodSection(), DataQualitySection()
        generation.limitations.append("Official waste statistics could not be loaded.")
    services = P.build_services_section(snap)
    infra = P.build_infrastructure_section(snap)
    forecast = P.build_forecast_section(table)
    alerts = P.build_alerts(snap, generation, categories, dq, now)

    stats_ok = table is not None and year is not None
    any_ok = any(s.status != "unavailable" for s in snap.sources)
    status = "STATISTICS_AVAILABLE" if stats_ok else ("PARTIAL" if any_ok else "UNAVAILABLE")
    ok_sources = sum(1 for s in snap.sources if s.status == "ok")
    checks_pass = bool(dq.checks) and all(c.passed for c in dq.checks)
    if stats_ok and checks_pass and ok_sources >= 5:
        confidence = "high"
    elif stats_ok:
        confidence = "medium"
    else:
        confidence = "low"

    warnings = list(snap.warnings) + list(table.warnings if table else [])
    warnings += [f"Data quality check failed: {c.key}" for c in dq.checks if not c.passed]
    limitations = [
        "All waste data is official annual statistics or static location/licence listings; nothing in this module is live.",
        "Facility, collection-point and disposal-site layers are reference data with per-record dates from 2017-2022; they may not reflect today's network.",
        "Domestic vs non-domestic waste, per-capita figures, landfill capacity, truck tracking and bin fill levels are not available as official open data and are not shown.",
        "Waste does not assess water, energy, flood, fire, roads or traffic; cross-domain reasoning is done by the City Coordinator.",
    ]
    report = WasteReport(
        generated_at=now, status=status, overall_risk="UNKNOWN",  # type: ignore[arg-type]
        kpis=kpis, generation=generation, categories=categories, food=food, services=services,
        infrastructure=infra, unavailable_metrics=P.build_unavailable_metrics(), forecast=forecast, data_quality=dq,
        alerts=alerts, sources=snap.sources,
        data_timestamps={
            s.key: {"last_fetched_at": s.last_fetched_at.isoformat() if s.last_fetched_at else None,
                    "latest_data_period": s.latest_data_period, "status": s.status, "data_kind": s.data_kind}
            for s in snap.sources
        },
        confidence=confidence,  # type: ignore[arg-type]
        limitations=limitations, warnings=warnings, errors=list(snap.errors), is_ml_prediction=False,
    )
    report.summary = _build_summary(report)
    report.insights = _build_insights(report)
    state.report = report
    return state


def build_report(state: WasteAgentState) -> WasteAgentState:
    if state.report is None:
        return analyze_waste(state)
    return state


def create_waste_agent() -> StateGraph:
    graph = StateGraph(WasteAgentState)
    graph.add_node("ingest_waste_data", ingest_waste_data)
    graph.add_node("analyze_waste", analyze_waste)
    graph.add_node("build_report", build_report)
    graph.set_entry_point("ingest_waste_data")
    graph.add_edge("ingest_waste_data", "analyze_waste")
    graph.add_edge("analyze_waste", "build_report")
    graph.add_edge("build_report", END)
    return graph


class WasteManagementAgent:
    """The single Waste Management domain agent."""

    def __init__(self, fetcher: Optional[Callable[[], WasteSnapshot]] = None) -> None:
        self._fetcher = fetcher

    def run(self) -> WasteReport:
        """Never raises for source failures - they become ``report.errors`` / unavailable sections."""
        state = WasteAgentState()
        if self._fetcher is not None:
            state.fetcher = self._fetcher
        result = create_waste_agent().compile().invoke(state)
        return result["report"]


def run_waste_agent(fetcher: Optional[Callable[[], WasteSnapshot]] = None) -> WasteReport:
    return WasteManagementAgent(fetcher).run()
