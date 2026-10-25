"""Energy Agent — LangGraph workflow for official Singapore energy statistics.

Pipeline:
  official sources -> acquisition/validation -> deterministic analytics -> EnergyReport

All requests are live at runtime. No current values are hardcoded into the report.
No ML model is used; all insights are deterministic restatements of official data.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional

import requests

from langgraph.graph import END, StateGraph

from backend.app.infrastructure.energy.data import DATASETS, _num, fetch_dataset, fetch_snapshot
from backend.app.infrastructure.energy.models import EnergyReport, EnergySource

log = logging.getLogger(__name__)
SG = timezone(timedelta(hours=8))
BASE = "https://data.gov.sg/api/action/datastore_search"


@dataclass
class EnergyAgentState:
    """LangGraph state for Energy Agent."""
    snapshot: Optional[Dict[str, Any]] = None
    report: Optional["EnergyReport"] = None
    # Injected for tests / offline use.
    fetcher: Callable[[], Dict[str, Any]] = field(default_factory=lambda: fetch_snapshot)
    # Error tracking
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _field(row, *names):
    lower = {str(k).lower(): v for k, v in row.items()}
    for name in names:
        if name.lower() in lower: return lower[name.lower()]
    return None


def _source(key, item, error=None):
    m = DATASETS[key]
    if item is None:
        return EnergySource(name=DATASETS[key]["name"], dataset_id=m["id"], url=m["url"],
            frequency=m["frequency"], coverage=m["coverage"], unit=m["unit"],
            status="unavailable", error=error)
    records = item["records"]
    period = None
    if records:
        if key == "peak_demand":
            period = f'{_field(records[-1], "year")} {_field(records[-1], "mth", "month")}'
        elif key in ("solar_capacity", "solar_region"):
            period = str(_field(records[-1], "year") or "historical")
        else: period = str(_field(records[-1], "year") or "historical")
    return EnergySource(name=DATASETS[key]["name"], dataset_id=m["id"], url=m["url"],
        frequency=m["frequency"], coverage=m["coverage"], unit=m["unit"],
        status="ok" if records else "unavailable", latest_period=period, records=len(records),
        error=None if records else "Official API returned no records")


@dataclass
class EnergyAgentState:
    """LangGraph state for Energy Agent."""
    snapshot: Optional[Dict[str, Any]] = None
    report: Optional["EnergyReport"] = None
    # Injected for tests / offline use.
    fetcher: Callable[[], Dict[str, Any]] = field(default_factory=lambda: fetch_snapshot)
    # Error tracking
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _field(row, *names):
    lower = {str(k).lower(): v for k, v in row.items()}
    for name in names:
        if name.lower() in lower: return lower[name.lower()]
    return None


def ingest_energy_data(state: EnergyAgentState) -> EnergyAgentState:
    """Fetch all official energy datasets from data.gov.sg."""
    log.info("Fetching energy datasets from data.gov.sg...")
    try:
        state.snapshot = state.fetcher()
        state.warnings.extend(state.snapshot.get("errors", []))
    except Exception as e:
        state.errors.append(f"Failed to fetch energy snapshot: {e}")
        log.exception("Energy data ingestion failed")
    return state


def _field(row, *names):
    lower = {str(k).lower(): v for k, v in row.items()}
    for name in names:
        if name.lower() in lower: return lower[name.lower()]
    return None


def _source(key, item, error=None):
    m = DATASETS[key]
    if item is None:
        return EnergySource(name=DATASETS[key]["name"], dataset_id=m["id"], url=m["url"],
            frequency=m["frequency"], coverage=m["coverage"], unit=m["unit"],
            status="unavailable", error=error)
    records = item["records"]
    period = None
    if records:
        if key == "peak_demand":
            period = f'{_field(records[-1], "year")} {_field(records[-1], "mth", "month")}'
        elif key in ("solar_capacity", "solar_region"):
            period = str(_field(records[-1], "year") or "historical")
        else: period = str(_field(records[-1], "year") or "historical")
    return EnergySource(name=DATASETS[key]["name"], dataset_id=m["id"], url=m["url"],
        frequency=m["frequency"], coverage=m["coverage"], unit=m["unit"],
        status="ok" if records else "unavailable", latest_period=period, records=len(records),
        error=None if records else "Official API returned no records")


def build_report(state: EnergyAgentState) -> EnergyAgentState:
    """Build the final EnergyReport from the snapshot."""
    log.info("Building energy report...")
    
    if state.snapshot is None:
        state.errors.append("No snapshot available")
        state.report = EnergyReport(
            generated_at=datetime.now(SG),
            status="UNAVAILABLE",
            summary="Energy data unavailable",
            key_metrics={},
            peak_demand=[],
            consumption=[],
            solar_by_region=[],
            solar_capacity=[],
            sources=[],
            limitations=["No data snapshot available"],
            warnings=[],
            errors=state.errors,
            confidence="low",
        )
        return state

    try:
        datasets = state.snapshot.get("datasets", {})
        sources = [_source(k, datasets.get(k), next((e for e in state.snapshot.get("errors", []) if DATASETS[k]["name"] in e), None)) for k in DATASETS]
        demand = []
        for row in (datasets.get("peak_demand") or {}).get("records", []):
            year = _field(row, "year"); month = _field(row, "mth", "month")
            value = _num(_field(row, "peak_system_demand_mw", "Peak System Demand"))
            if year is not None and month is not None:
                demand.append({"period": f"{year}-{int(float(month)):02d}", "value_mw": value})
        demand.sort(key=lambda x: x["period"])
        cons = []
        for row in (datasets.get("consumption") or {}).get("records", []):
            year = _field(row, "year")
            sector = _field(row, "sector")
            product = _field(row, "energy_products")
            value = _num(_field(row, "consumption_ktoe", "consumption"))
            if year is not None:
                cons.append({"year": str(year), "sector": sector, "energy_product": product, "consumption_ktoe": value})
        cons.sort(key=lambda x: (x["year"], str(x["sector"]), str(x["energy_product"])))
        solar_region = []
        for row in (datasets.get("solar_region") or {}).get("records", []):
            year = _field(row, "year"); region = _field(row, "ura_planning_region")
            if year is None or region is None: continue
            solar_region.append({
                "year": str(year), "region": str(region),
                "residential_status": _field(row, "residential_status"),
                "installations": _num(_field(row, "num_solar_pv_inst")),
                "capacity_kwac": _num(_field(row, "inst_cap_kwac")),
                "share_percent": _num(_field(row, "total_inst_cap_percent")),
            })
        solar_cap = []
        for row in (datasets.get("solar_capacity") or {}).get("records", []):
            year = _field(row, "year")
            if year is None: continue
            solar_cap.append({
                "year": str(year), "residential_status": _field(row, "residential_status"),
                "user_type": _field(row, "user_type"),
                "capacity_mwp": _num(_field(row, "inst_cap_mwp")),
                "capacity_mwac": _num(_field(row, "inst_cap_mwac")),
            })
        valid_demands = [x["value_mw"] for x in demand if x["value_mw"] is not None]
        valid_solar = [x for x in solar_cap if x["capacity_mwp"] is not None]
        latest_solar_year = max((x["year"] for x in valid_solar), default=None)
        latest_solar = [x["capacity_mwp"] for x in valid_solar if x["year"] == latest_solar_year]
        metrics = {
            "latest_peak_demand_mw": valid_demands[-1] if valid_demands else None,
            "latest_peak_demand_period": next((x["period"] for x in reversed(demand) if x["value_mw"] is not None), None),
            "max_peak_demand_mw": max(valid_demands) if valid_demands else None,
            "average_peak_demand_mw": round(sum(valid_demands)/len(valid_demands), 2) if valid_demands else None,
            "latest_solar_capacity_mwp": round(sum(latest_solar), 3) if latest_solar else None,
            "latest_solar_capacity_year": latest_solar_year,
            "demand_records": len(valid_demands),
            "consumption_records": len(cons),
        }
        available = sum(s.status == "ok" for s in sources)
        status = "OK" if available == len(sources) else ("PARTIAL" if available else "UNAVAILABLE")
        summary = (f"{available} of {len(sources)} official energy datasets are available. "
                   "Demand, consumption and solar indicators are historical statistics, not live grid telemetry.")
        limitations = [
            "The verified public peak-system-demand dataset ends in July 2021 and is monthly; it cannot support a truthful current-demand KPI or half-hourly forecast.",
            "The verified solar datasets end in March 2021; figures must be labelled historical and must not be presented as current installed capacity.",
            "The consumption dataset covers 2009–2019 and reports total final energy consumption in ktoe, not electricity-only consumption in MWh.",
            "No half-hourly system-demand series was verified as accessible in the public dataset catalogue during implementation. ML forecasting is therefore disabled rather than fabricated.",
            "A current USEP series, current generation mix, generation capacity/availability, and transmission availability were not added because a directly accessible, verified dataset was not established in this implementation."
        ]
        errors = [s.error for s in sources if s.error]
        warnings = []
        if available < len(sources):
            warnings.append(f"{len(sources) - available} of {len(sources)} energy datasets unavailable or returned no records")
        confidence = "high" if available == len(sources) else ("medium" if available >= len(sources) // 2 else "low")
        data_timestamps = {}
        for key, source in zip(DATASETS, sources):
            item = datasets.get(key)
            fetched_at = item.get("fetched_at") if isinstance(item, dict) else None
            fetched_iso = datetime.fromtimestamp(fetched_at, SG).isoformat() if fetched_at else None
            data_timestamps[source.name] = {
                "last_fetched_at": fetched_iso,
                "latest_data_period": source.latest_period,
                "status": source.status,
                "data_kind": "historical" if source.status == "ok" else "unavailable",
            }
        state.report = EnergyReport(generated_at=datetime.now(SG), status=status, summary=summary,
            key_metrics=metrics, peak_demand=demand, consumption=cons,
            solar_by_region=solar_region, solar_capacity=solar_cap, sources=sources,
            limitations=limitations, warnings=warnings, errors=errors,
            confidence=confidence, data_timestamps=data_timestamps)
    except Exception as e:
        state.errors.append(f"Failed to build energy report: {e}")
        log.exception("Energy report building failed")
    return state


def create_energy_agent() -> StateGraph:
    """Create the Energy Agent LangGraph workflow."""
    workflow = StateGraph(EnergyAgentState)
    
    workflow.add_node("ingest_energy_data", ingest_energy_data)
    workflow.add_node("build_report", build_report)
    
    workflow.set_entry_point("ingest_energy_data")
    workflow.add_edge("ingest_energy_data", "build_report")
    workflow.add_edge("build_report", END)
    
    return workflow.compile()


def run_energy_agent(fetcher: Optional[Callable[[], Dict[str, Any]]] = None) -> "EnergyReport":
    """Run the Energy Agent and return an EnergyReport.
    
    Never raises for source failures - they become report.errors.
    """
    state = EnergyAgentState()
    if fetcher is not None:
        state.fetcher = fetcher
    result = create_energy_agent().invoke(state)
    report = result.get("report")
    if report is None:
        raise RuntimeError("Energy Agent did not produce an EnergyReport")
    return report


# Global compiled graph
_energy_agent_graph = None


def get_energy_agent():
    """Get or create the compiled Energy agent graph."""
    global _energy_agent_graph
    if _energy_agent_graph is None:
        _energy_agent_graph = create_energy_agent()
    return _energy_agent_graph


# Re-export the original function for backward compatibility
# This maintains backward compatibility with the coordinator's import
from backend.app.infrastructure.energy.data import fetch_snapshot as _fetch_snapshot
from backend.app.infrastructure.energy.processing import build_report as _build_report

# Re-export the models for backward compatibility
from backend.app.infrastructure.energy.models import EnergyReport, EnergySource
