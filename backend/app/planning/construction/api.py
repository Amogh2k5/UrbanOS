"""FastAPI routes for Singapore Construction Intelligence."""
from __future__ import annotations
import logging
import threading
import time
from fastapi import APIRouter, HTTPException, Query
from .agent import run_construction_agent
from .data import clear_construction_source_cache
from .models import ConstructionReport

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/planning/construction", tags=["planning-construction"])
_lock = threading.Lock()
_cache: dict = {"report": None, "expires_at": 0.0, "cached_at": 0.0}


def get_construction_report(refresh: bool = False) -> ConstructionReport:
    now = time.time()
    request_started = time.monotonic()
    with _lock:
        report = _cache["report"]
        if report is not None and refresh and _cache["cached_at"] > request_started:
            return report
        if report is not None and not refresh and now < _cache["expires_at"]:
            return report
        try:
            if refresh:
                clear_construction_source_cache()
            report = run_construction_agent()
        except Exception as exc:
            log.exception("Construction report generation failed")
            raise HTTPException(status_code=502, detail=f"Construction data unavailable: {exc}") from exc
        _cache["report"] = report
        # Annual/historical sources don't need aggressive polling
        _cache["expires_at"] = now + (300 if report.status == "UNAVAILABLE" else 1800)
        _cache["cached_at"] = time.monotonic()
        return report


def peek_construction_report():
    """Return the cached report only while it is still fresh. Never runs the
    agent and never blocks: ``get_construction_report`` holds ``_lock`` for
    the whole run, so taking it here would make a cheap Overview card read
    wait behind a full data fetch. A cold or expired cache reads as ``None``.
    """
    cached = _cache["report"]
    if cached is not None and time.time() < _cache["expires_at"]:
        return cached
    return None


@router.get("/report")
def construction_report(refresh: bool = Query(False)):
    return get_construction_report(refresh).model_dump(mode="json")


@router.get("/sources")
def construction_sources(refresh: bool = Query(False)):
    report = get_construction_report(refresh)
    return {
        "generated_at": report.generated_at.isoformat(),
        "sources": [s.model_dump(mode="json") for s in report.sources],
        "errors": report.errors,
        "warnings": report.warnings,
        "limitations": report.limitations,
    }


@router.get("/greenmark")
def greenmark_buildings(
    rating: str | None = Query(None, description="Filter by certification rating"),
    project_type: str | None = Query(None, description="Filter by project type"),
    search: str | None = Query(None, description="Search by project name"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Get paginated list of Green Mark certified buildings with filters."""
    report = get_construction_report()
    buildings = report.greenmark_buildings

    # Apply filters
    if rating:
        buildings = [b for b in buildings if b.rating and b.rating.lower() == rating.lower()]
    if project_type:
        buildings = [b for b in buildings if b.project_type and b.project_type.lower() == project_type.lower()]
    if search:
        search_lower = search.lower()
        buildings = [
            b for b in buildings
            if (b.project_name and search_lower in b.project_name.lower())
            or (b.actual_project_name and search_lower in b.actual_project_name.lower())
            or (b.reference_no and search_lower in b.reference_no.lower())
        ]

    total = len(buildings)
    paginated = buildings[offset:offset + limit]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "buildings": [b.model_dump(mode="json") for b in paginated],
    }


@router.get("/pipeline")
def construction_pipeline(
    year: int | None = Query(None, description="Filter by year"),
):
    """Get URA construction pipeline records, optionally filtered by year."""
    report = get_construction_report()
    pipeline = report.pipeline_records

    if year is not None:
        pipeline = [p for p in pipeline if p.year == year]

    return {
        "records": [p.model_dump(mode="json") for p in pipeline],
        "count": len(pipeline),
    }


@router.get("/map")
def construction_map():
    """Get GeoJSON map data for Green Mark buildings."""
    report = get_construction_report()
    return report.map_data


@router.get("/kpis")
def construction_kpis():
    """Get summary KPIs for the Construction module."""
    report = get_construction_report()
    return {
        "generated_at": report.generated_at.isoformat(),
        "kpis": report.kpis,
        "greenmark_summary": report.greenmark_summary,
        "pipeline_trend": report.pipeline_trend,
        "greenmark_by_rating": report.greenmark_by_rating,
        "greenmark_by_type": report.greenmark_by_type,
    }


def start_construction_warmup() -> None:
    """Trigger one construction report build in a background thread at startup."""
    def _run():
        try:
            get_construction_report(refresh=True)
        except Exception as exc:
            log.warning("Construction warmup failed (non-fatal): %s", exc)
    threading.Thread(target=_run, daemon=True, name="construction-warmup").start()
