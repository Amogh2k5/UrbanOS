"""Construction Agent — LangGraph workflow for BCA/URA construction intelligence.

Pipeline:
  official sources -> acquisition/validation -> deterministic analytics -> ConstructionReport

No ML model is used; all insights are deterministic restatements of official data.
Source failures never raise; they land in report.errors and the module degrades to partial.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional

from langgraph.graph import END, StateGraph

from backend.app.planning.construction.data import SourceResult, fetch_construction_snapshot
from backend.app.planning.construction.processing import build_construction_report
from backend.app.planning.construction.models import ConstructionReport, ConstructionSource, ConstructionInsight

log = logging.getLogger(__name__)
SG = timezone(timedelta(hours=8))


@dataclass
class ConstructionAgentState:
    """LangGraph state for Construction Agent."""
    snapshot: Optional[Dict[str, Any]] = None
    report: Optional["ConstructionReport"] = None
    # Injected for tests / offline use.
    fetcher: Callable[[], Dict[str, Any]] = field(default_factory=lambda: fetch_construction_snapshot)
    # Error tracking
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def ingest_construction_data(state: ConstructionAgentState) -> ConstructionAgentState:
    """Fetch all official construction datasets from data.gov.sg."""
    log.info("Fetching construction datasets from data.gov.sg...")
    try:
        state.snapshot = state.fetcher()
        # Source adapters return SourceResult dataclasses. Normalize mapping
        # fixtures and custom fetchers at this boundary so downstream report
        # processing always receives the same typed source contract.
        # Collect warnings from source failures
        sources = state.snapshot.get("sources", {})
        normalized = {}
        for key, source in sources.items():
            if isinstance(source, dict):
                source = SourceResult(
                    key=source.get("key", key),
                    name=source.get("name", "Unknown"),
                    agency=source.get("agency", "Unknown"),
                    url=source.get("url", ""),
                    status=source.get("status", "unavailable"),
                    records=source.get("records") or [],
                    retrieved_at=source.get("retrieved_at"),
                    error=source.get("error"),
                    fields=source.get("fields") or [],
                    total_count=source.get("total_count"),
                    coverage_start=source.get("coverage_start"),
                    coverage_end=source.get("coverage_end"),
                    last_updated_at=source.get("last_updated_at"),
                )
            normalized[key] = source
            status = getattr(source, "status", None)
            error = getattr(source, "error", None)
            if error:
                state.warnings.append(f"{getattr(source, 'name', key)}: {error}")
            elif status in {"unavailable", "empty"}:
                state.warnings.append(
                    f"{getattr(source, 'name', key)} returned source status '{status}'."
                )
        state.snapshot["sources"] = normalized
    except Exception as e:
        state.errors.append(f"Failed to fetch construction snapshot: {e}")
        log.exception("Construction data ingestion failed")
    return state


def build_report(state: ConstructionAgentState) -> ConstructionAgentState:
    """Build the ConstructionReport from the snapshot."""
    log.info("Building construction report...")
    
    if state.snapshot is None:
        state.errors.append("No snapshot available")
        state.report = ConstructionReport(
            generated_at=datetime.now(SG),
            status="UNAVAILABLE",
            kpis={},
            greenmark_summary={},
            pipeline_trend=[],
            greenmark_by_rating=[],
            greenmark_by_type=[],
            greenmark_buildings=[],
            pipeline_records=[],
            map_data={},
            sources=[],
            errors=state.errors,
            warnings=state.warnings,
            limitations=[
                "Green Mark dataset covers voluntary certification only; legislated projects and opt-outs excluded.",
                "URA pipeline data covers private residential only (2013–2017); no recent years available.",
                "Building Energy dataset covers 2018 only; not current performance.",
                "GeoJSON dataset may not have valid geometry for all buildings; verify before use.",
                "Postal codes are not precise coordinates; do not use for exact mapping.",
                "Data refresh frequency varies by source; check source metadata for latest update.",
            ],
            confidence="low",
            data_timestamps={},
            is_ml_prediction=False,
        )
        return state

    try:
        # Delegate to the existing deterministic processing function
        report = build_construction_report(state.snapshot)
        # Source-level failures are also surfaced as warnings, while the
        # snapshot's original errors remain in the report's errors array.
        report.warnings.extend(state.warnings)
        state.report = report
    except Exception as e:
        state.errors.append(f"Failed to build construction report: {e}")
        log.exception("Construction report building failed")
    
    return state


def create_construction_agent() -> StateGraph:
    """Create the Construction Agent LangGraph workflow."""
    workflow = StateGraph(ConstructionAgentState)
    
    workflow.add_node("ingest_construction_data", ingest_construction_data)
    workflow.add_node("build_report", build_report)
    
    workflow.set_entry_point("ingest_construction_data")
    workflow.add_edge("ingest_construction_data", "build_report")
    workflow.add_edge("build_report", END)
    
    return workflow.compile()


def run_construction_agent(fetcher: Optional[Callable[[], Dict[str, Any]]] = None) -> "ConstructionReport":
    """Run the Construction Agent and return a ConstructionReport.
    
    Never raises for source failures - they become report.errors.
    """
    state = ConstructionAgentState()
    if fetcher is not None:
        state.fetcher = fetcher
    result = create_construction_agent().invoke(state)
    report = result.get("report")
    if report is None:
        raise RuntimeError("Construction Agent did not produce a ConstructionReport")
    return report


# Global compiled graph
_construction_agent_graph = None


def get_construction_agent():
    """Get or create the compiled Construction agent graph."""
    global _construction_agent_graph
    if _construction_agent_graph is None:
        _construction_agent_graph = create_construction_agent()
    return _construction_agent_graph


# Re-export the models for backward compatibility
from backend.app.planning.construction.models import ConstructionReport, ConstructionSource, ConstructionInsight
