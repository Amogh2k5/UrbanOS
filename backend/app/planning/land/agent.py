"""Land Agent.

Pipeline:
  official sources -> streaming acquisition/validation -> deterministic
  processing -> LandReport (+ rule-based insights answering the standard Land
  questions).

No ML model is used and none is planned: every insight below is a restatement of
an aggregated official field. Source failures never raise; they land in
``report.errors`` and the module degrades to partial.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from langgraph.graph import END, StateGraph

from backend.app.planning.land.models import LandInsight, LandReport
from backend.app.planning.land.processing import (
    GROUP_LABELS, build_alerts, build_cadastral_section, build_gls_section,
    build_gpr_section, build_industrial_section, build_land_use_section,
    build_planning_section, construction_context, housing_context,
)
from backend.app.planning.land.sources import LandSnapshot, fetch_land_snapshot, source_status

log = logging.getLogger(__name__)
SG = timezone(timedelta(hours=8))

STANDARD_QUESTIONS = (
    "What is the dominant land use in Singapore?",
    "How much land is zoned for each major use?",
    "Which planning areas have the most residential land?",
    "How is land use distributed across planning areas?",
    "What Government Land Sales activity has been recorded?",
    "How much industrial land is there?",
    "What is the cadastral parcel coverage?",
    "How does land relate to housing and construction?",
)


@dataclass
class LandAgentState:
    snapshot: Optional[LandSnapshot] = None
    report: Optional[LandReport] = None
    # Injected for tests / offline use.
    fetcher: Callable[[], LandSnapshot] = fetch_land_snapshot


def ingest_land_data(state: LandAgentState) -> LandAgentState:
    state.snapshot = state.fetcher()
    return state


def _fmt(value: Optional[float], unit: str = "") -> str:
    return "n/a" if value is None else f"{value:g}{(' ' + unit) if unit else ''}"


def _km2(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value / 1e6:,.1f} km2"


def build_insights(report: LandReport) -> List[LandInsight]:
    lu, planning, gls, cad, ind = (
        report.land_use, report.planning, report.gls, report.cadastral, report.industrial,
    )
    out: List[LandInsight] = []

    # 1. Dominant land use
    with_area = [c for c in lu.categories if c.area_sqm is not None]
    if with_area:
        top = with_area[0]
        out.append(LandInsight(
            question=STANDARD_QUESTIONS[0],
            answer=(
                f"{top.label} is the largest official land-use designation by area, "
                f"covering {_fmt(top.area_sqm, 'm2')} ({_fmt(top.area_pct, '%')}) across "
                f"{_fmt(top.zone_count, 'zones')}. This is planned statutory zoning, "
                "not current physical land use."
            ),
            data_kind="latest_available",
        ))
    else:
        out.append(LandInsight(
            question=STANDARD_QUESTIONS[0], answer="Land-use area data unavailable.",
            data_kind="unavailable",
        ))

    # 2. Area by major group
    group_bits = [
        f"{GROUP_LABELS[g]}: {_km2(v)}"
        for g, v in lu.by_group.items()
        if v is not None and v > 0
    ]
    out.append(LandInsight(
        question=STANDARD_QUESTIONS[1],
        answer=(
            f"{_km2(lu.total_area_sqm)} of Master Plan land-use area across "
            f"{_fmt(lu.total_zones, 'zones')}. " + "; ".join(group_bits) + "."
            if group_bits else "No land-use area could be summarised."
        ),
        data_kind="latest_available" if lu.total_area_sqm else "unavailable",
    ))

    # 3. Most residential planning areas
    res = [
        p for p in planning.planning_areas if (p.group_area_sqm or {}).get("residential")
    ]
    res_sorted = sorted(res, key=lambda p: -(p.group_area_sqm or {}).get("residential", 0.0))[:5]
    if res_sorted:
        out.append(LandInsight(
            question=STANDARD_QUESTIONS[2],
            answer="; ".join(
                f"{p.name} ({_km2((p.group_area_sqm or {}).get('residential'))})"
                for p in res_sorted
            ) + ".",
            data_kind="latest_available",
        ))
    else:
        out.append(LandInsight(
            question=STANDARD_QUESTIONS[2],
            answer="Residential zoning could not be attributed to planning areas.",
            data_kind="unavailable",
        ))

    # 4. Planning-area distribution
    if planning.planning_areas:
        with_lu = [p for p in planning.planning_areas if p.land_use_area_sqm is not None]
        cov = [p.land_use_coverage_pct for p in with_lu if p.land_use_coverage_pct is not None]
        out.append(LandInsight(
            question=STANDARD_QUESTIONS[3],
            answer=(
                f"{_fmt(planning.planning_area_count, 'planning areas')} in "
                f"{_fmt(planning.region_count, 'regions')}. Land-use coverage of "
                f"{len(cov)} areas ranges {_fmt(min(cov), '%')} to {_fmt(max(cov), '%')} "
                "of planning-area area."
                if cov else "Planning areas loaded without attributable land-use area."
            ),
            data_kind="latest_available" if planning.planning_area_count else "unavailable",
        ))
    else:
        out.append(LandInsight(
            question=STANDARD_QUESTIONS[3], answer="Planning areas unavailable.",
            data_kind="unavailable",
        ))

    # 5. GLS
    if gls.site_count:
        recent = gls.by_year.get(str(gls.award_year_max), 0) if gls.award_year_max else None
        out.append(LandInsight(
            question=STANDARD_QUESTIONS[4],
            answer=(
                f"{_fmt(gls.site_count, 'sites')} awarded GLS sites recorded from "
                f"{_fmt(gls.award_year_min)} to {_fmt(gls.award_year_max)}, totalling "
                f"{_km2(gls.total_site_area_sqm)} of site area"
                + (f"; {_fmt(recent, 'sites')} awarded in {gls.award_year_max}." if recent is not None else ".")
                + f" {gls.current_program_note}"
            ),
            data_kind="historical",
        ))
    else:
        out.append(LandInsight(
            question=STANDARD_QUESTIONS[4], answer="GLS site records unavailable.",
            data_kind="unavailable",
        ))

    # 6. Industrial
    ind_bits = []
    if ind.industrial_land_use_area_sqm is not None:
        ind_bits.append(f"{_km2(ind.industrial_land_use_area_sqm)} zoned BUSINESS 1/BUSINESS 2 (URA land use)")
    if ind.total_estate_area_km2 is not None:
        ind_bits.append(f"{_fmt(ind.estate_count, 'JTC estates')} covering {ind.total_estate_area_km2} km2")
    out.append(LandInsight(
        question=STANDARD_QUESTIONS[5],
        answer="; ".join(ind_bits) + "." if ind_bits else "Industrial land data unavailable.",
        data_kind=ind.data_kind,
    ))

    # 7. Cadastral
    if cad.parcel_count:
        out.append(LandInsight(
            question=STANDARD_QUESTIONS[6],
            answer=(
                f"{_fmt(cad.parcel_count, 'surveyed parcels')} totalling "
                f"{_km2(cad.total_area_sqm)}, median parcel area {_km2(cad.median_area_sqm)}. "
                f"{cad.ownership_note} Parcel counts do not indicate available land."
            ),
            data_kind="latest_available",
        ))
    else:
        out.append(LandInsight(
            question=STANDARD_QUESTIONS[6], answer="Cadastral parcel layer unavailable.",
            data_kind="unavailable",
        ))

    # 8. Cross-domain
    out.append(LandInsight(
        question=STANDARD_QUESTIONS[7],
        answer=(
            f"Residential planned land allocation is concentrated in "
            f"{', '.join(h['planning_area'] for h in housing_context(planning)['residential_zoned_planning_areas'][:3]) or 'no area'}. "
            f"{_fmt(gls.site_count, 'GLS sites')} are recorded. "
            f"{housing_context(planning)['note']} {construction_context(gls)['note']}"
        ),
        data_kind="latest_available",
    ))
    return out


def analyze_land(state: LandAgentState) -> LandAgentState:
    snap = state.snapshot or LandSnapshot(generated_at=datetime.now(SG))

    land_use = build_land_use_section(snap)
    land_use.gpr = build_gpr_section(snap, land_use)
    planning = build_planning_section(snap)
    cadastral = build_cadastral_section(snap)
    gls = build_gls_section(snap)
    industrial = build_industrial_section(snap, land_use)

    ok_sources = sum(1 for s in snap.sources if s.status == "ok")
    total_sources = len(snap.sources) or 1
    if ok_sources == total_sources:
        confidence = "high"
    elif ok_sources >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    limitations = [
        "Cadastral parcel is NOT available land: it is a surveyed legal boundary only.",
        "Planned land use (Master Plan 2025 zoning) is NOT current physical land use.",
        "A GLS site is one specific government land sale; it is NOT all available land.",
        "Land-use zones are attributed to planning areas by centroid against a "
        "~280 m grid, so a zone straddling a planning-area edge is attributed to "
        "the area containing its centroid.",
        "The current GLS Confirmed/Reserve List is published by URA as a web page "
        "and press-release PDF rather than an open dataset, so it is not included.",
    ]

    report = LandReport(
        generated_at=datetime.now(SG),
        source_status=source_status(snap),  # type: ignore[arg-type]
        land_use=land_use,
        planning=planning,
        cadastral=cadastral,
        gls=gls,
        industrial=industrial,
        alerts=build_alerts(land_use, planning, gls, industrial, snap),
        sources=snap.sources,
        data_timestamps={
            s.key: {
                "status": s.status,
                "record_count": s.record_count,
                "update_frequency": s.update_frequency,
                "crs": s.crs,
                "error": s.error,
            }
            for s in snap.sources
        },
        confidence=confidence,  # type: ignore[arg-type]
        limitations=limitations,
        warnings=list(snap.warnings),
        errors=list(snap.errors),
        is_ml_prediction=False,
    )
    report.insights = build_insights(report)
    state.report = report
    return state


def build_report(state: LandAgentState) -> LandAgentState:
    if state.report is None:
        return analyze_land(state)
    return state


def create_land_agent() -> StateGraph:
    graph = StateGraph(LandAgentState)
    graph.add_node("ingest_land_data", ingest_land_data)
    graph.add_node("analyze_land", analyze_land)
    graph.add_node("build_report", build_report)
    graph.set_entry_point("ingest_land_data")
    graph.add_edge("ingest_land_data", "analyze_land")
    graph.add_edge("analyze_land", "build_report")
    graph.add_edge("build_report", END)
    return graph


def run_land_agent(fetcher: Optional[Callable[[], LandSnapshot]] = None) -> LandReport:
    """Run the agent. Never raises for source failures - they become report.errors."""
    state = LandAgentState()
    if fetcher is not None:
        state.fetcher = fetcher
    result = create_land_agent().compile().invoke(state)
    report = result.get("report")
    if report is None:
        raise RuntimeError("Land Agent did not produce a LandReport")
    return report


def agent_capabilities() -> Dict[str, Any]:
    """Static description used by the Overview module summary."""
    return {
        "standard_questions": list(STANDARD_QUESTIONS),
        "graph_nodes": ["ingest_land_data", "analyze_land", "build_report"],
        "uses_ml": False,
    }