"""Housing Agent — LangGraph workflow for HDB resale intelligence.

Pipeline:
  official sources -> acquisition/validation -> deterministic analytics -> HousingReport

No ML model is used in the core agent; forecasting is a separate module.
All insights are deterministic restatements of official HDB data.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional

from langgraph.graph import END, StateGraph

from backend.app.planning.housing.data import fetch_housing_snapshot
from backend.app.planning.housing.processing import build_housing_report
from backend.app.planning.housing.models import HousingReport, HousingSource, HousingInsight

log = logging.getLogger(__name__)
SG = timezone(timedelta(hours=8))


# ============================================================ State

@dataclass
class HousingAgentState:
    """LangGraph state for Housing Agent."""
    snapshot: Optional[Dict[str, Any]] = None
    report: Optional["HousingReport"] = None
    # Injected for tests / offline use.
    fetcher: Callable[[], Dict[str, Any]] = field(default_factory=lambda: fetch_housing_snapshot)
    # Error tracking
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ============================================================ Nodes

def ingest_housing_data(state: HousingAgentState) -> HousingAgentState:
    """Fetch all official housing datasets from data.gov.sg."""
    log.info("Fetching housing datasets from data.gov.sg...")
    try:
        state.snapshot = state.fetcher()
        # Collect warnings from source failures
        sources = state.snapshot.get("sources", {})
        for s in sources.values():
            if isinstance(s, dict):
                error = s.get("error")
                name = s.get("name", "Unknown")
            else:
                error = getattr(s, "error", None)
                name = getattr(s, "name", "Unknown")
            if error:
                state.warnings.append(f"{name}: {error}")
    except Exception as e:
        state.errors.append(f"Failed to fetch housing snapshot: {e}")
        log.exception("Housing data ingestion failed")
    return state


def build_report(state: HousingAgentState) -> HousingAgentState:
    """Build the HousingReport from the snapshot."""
    log.info("Building housing report...")
    
    if state.snapshot is None:
        state.errors.append("No snapshot available")
        state.report = HousingReport(
            generated_at=datetime.now(SG),
            status="UNAVAILABLE",
            kpis={},
            resale_trend=[],
            town_prices=[],
            resale_by_flat_type=[],
            housing_stock={},
            rental_market={"available": False, "hdb_median_rent": None, "private_rent_index": None,
                          "note": "No current median-rent dataset was configured as an accessible machine-readable source in this build."},
            private_residential={"available": False, "price_index": None, "rental_index": None, "vacancy_rate": None,
                                 "note": "URA publishes private residential market releases, but a reliable unauthenticated structured API/feed was not confirmed here.",
                                 "official_release_url": "https://www.ura.gov.sg/news/"},
            supply_pipeline={"available": False, "items": [], "note": "No verified structured pipeline feed is wired into this module."},
            household_context={"available": False, "resident_households": None, "average_household_size": None,
                              "owner_occupied_share": None, "dwelling_type_share": None,
                               "note": "SingStat household indicators are not represented as live data; a verified machine-readable table is needed."},
            map_data={"available": False, "type": "FeatureCollection", "features": [],
                      "note": "HDB property dataset has block/street fields but no coordinates; map markers are intentionally omitted."},
            sources=[],
            errors=state.errors,
            warnings=state.warnings,
            limitations=[
                "This is a periodic/historical housing intelligence view, not a live property market feed.",
                "HDB median resale price is a town/flat-type statistic, not an individual flat valuation.",
                "HDB property inventory provides block/street reference fields but no verified latitude/longitude in this dataset; no map markers are fabricated.",
                "Detailed current URA private-market datasets and SingStat household tables were not confirmed as accessible machine-readable feeds in this implementation; their metrics remain unavailable rather than inferred.",
            ],
            confidence="low",
            data_timestamps={},
            is_ml_prediction=False,
        )
        return state

    try:
        # Delegate to the existing deterministic processing function
        report = build_housing_report(state.snapshot)
        state.report = report
    except Exception as e:
        state.errors.append(f"Failed to build housing report: {e}")
        log.exception("Housing report building failed")
    
    return state


def create_housing_agent() -> StateGraph:
    """Create the Housing Agent LangGraph workflow."""
    workflow = StateGraph(HousingAgentState)
    
    workflow.add_node("ingest_housing_data", ingest_housing_data)
    workflow.add_node("build_report", build_report)
    
    workflow.set_entry_point("ingest_housing_data")
    workflow.add_edge("ingest_housing_data", "build_report")
    workflow.add_edge("build_report", END)
    
    return workflow.compile()


def run_housing_agent(fetcher: Optional[Callable[[], Dict[str, Any]]] = None) -> "HousingReport":
    """Run the Housing Agent and return a HousingReport.
    
    Never raises for source failures - they become report.errors.
    """
    state = HousingAgentState()
    if fetcher is not None:
        state.fetcher = fetcher
    result = create_housing_agent().invoke(state)
    report = result.get("report")
    if report is None:
        raise RuntimeError("Housing Agent did not produce a HousingReport")
    return report


# Global compiled graph
_housing_agent_graph = None


def get_housing_agent():
    """Get or create the compiled Housing agent graph."""
    global _housing_agent_graph
    if _housing_agent_graph is None:
        _housing_agent_graph = create_housing_agent()
    return _housing_agent_graph


# Re-export the models for backward compatibility
from backend.app.planning.housing.models import HousingReport, HousingSource, HousingInsight
