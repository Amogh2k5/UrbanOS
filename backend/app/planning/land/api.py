"""FastAPI routes for the Planning -> Land domain.

Endpoints are deliberately few: one full report, one compact overview, the four
sections the UI actually renders, plus sources and a map payload. Nothing here
is created for symmetry.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.app.planning.land.agent import run_land_agent
from backend.app.planning.land.models import LandReport

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/planning/land", tags=["planning-land"])

_REPORT_CACHE: Dict[str, Any] = {"report": None, "expires_at": 0.0}
_lock = threading.Lock()


def get_land_report(refresh: bool = False) -> LandReport:
    """Single-flight TTL cache around the agent.

    The Land agent streams and aggregates ~335 MB of official GeoJSON, so it
    must never run per request. A successful report is cached for
    ``URBANOS_LAND_TTL_S`` (default 15 min); a degraded one is retried sooner.
    """
    now = time.time()
    with _lock:
        cached: Optional[LandReport] = _REPORT_CACHE["report"]
        if cached is not None and not refresh and now < _REPORT_CACHE["expires_at"]:
            return cached
        report = run_land_agent()
        ttl = 60.0 if report.errors else float(os.getenv("URBANOS_LAND_TTL_S", "900"))
        _REPORT_CACHE["report"] = report
        _REPORT_CACHE["expires_at"] = time.time() + ttl
        return report


def peek_land_report() -> Optional[LandReport]:
    """Read the current Land report cache without running or waiting on the agent."""
    cached: Optional[LandReport] = _REPORT_CACHE["report"]
    if cached is not None and time.time() < _REPORT_CACHE["expires_at"]:
        return cached
    return None


def start_land_warmup() -> None:
    """Pre-build the report in a background thread at server start.

    Disabled under pytest and by ``URBANOS_LAND_WARMUP=0`` so tests never race
    the network.
    """
    if os.getenv("URBANOS_LAND_WARMUP", "1") != "1" or "pytest" in sys.modules:
        return

    def _run() -> None:
        try:
            report = get_land_report()
            log.info("Land warm-up complete: status=%s zones=%s", report.source_status, report.land_use.total_zones)
        except Exception:  # noqa: BLE001
            log.exception("Land warm-up failed")

    threading.Thread(target=_run, name="land-warmup", daemon=True).start()


def _report(refresh: bool) -> LandReport:
    try:
        return get_land_report(refresh)
    except Exception as exc:  # noqa: BLE001
        log.exception("Land report generation failed")
        raise HTTPException(status_code=500, detail=f"land agent error: {exc}") from exc


def _meta(r: LandReport) -> Dict[str, Any]:
    return {
        "generated_at": r.generated_at.isoformat(),
        "source_status": r.source_status,
        "data_timestamps": r.data_timestamps,
        "warnings": r.warnings,
        "errors": r.errors,
    }


@router.get("/report")
def land_report(refresh: bool = Query(False)) -> Dict[str, Any]:
    """Full structured LandReport used by the frontend and coordinator."""
    return _report(refresh).model_dump(mode="json")


@router.get("/overview")
def land_overview(refresh: bool = Query(False)) -> Dict[str, Any]:
    """Compact headline summary for the Overview module."""
    r = _report(refresh)
    top = next((c for c in r.land_use.categories if c.area_sqm is not None), None)
    return {
        **_meta(r),
        "confidence": r.confidence,
        "headline": {
            "source_status": r.source_status,
            "total_area_km2": r.land_use.total_area_km2,
            "zone_count": r.land_use.total_zones,
            "planning_area_count": r.planning.planning_area_count,
            "region_count": r.planning.region_count,
            "dominant_category": top.label if top else None,
            "dominant_category_pct": top.area_pct if top else None,
            "cadastral_parcel_count": r.cadastral.parcel_count,
            "gls_site_count": r.gls.site_count,
            "industrial_land_km2": (
                round(r.industrial.industrial_land_use_area_sqm / 1e6, 2)
                if r.industrial.industrial_land_use_area_sqm else None
            ),
        },
        "alerts": [a.model_dump(mode="json") for a in r.alerts],
        "insights": [i.model_dump(mode="json") for i in r.insights],
        "limitations": r.limitations,
    }


@router.get("/use")
def land_use(refresh: bool = Query(False)) -> Dict[str, Any]:
    r = _report(refresh)
    return {**_meta(r), "land_use": r.land_use.model_dump(mode="json")}


@router.get("/planning-areas")
def land_planning_areas(refresh: bool = Query(False)) -> Dict[str, Any]:
    r = _report(refresh)
    return {**_meta(r), "planning": r.planning.model_dump(mode="json")}


@router.get("/gls")
def land_gls(refresh: bool = Query(False)) -> Dict[str, Any]:
    r = _report(refresh)
    return {**_meta(r), "gls": r.gls.model_dump(mode="json"), "cadastral": r.cadastral.model_dump(mode="json")}


@router.get("/industrial")
def land_industrial(refresh: bool = Query(False)) -> Dict[str, Any]:
    r = _report(refresh)
    return {**_meta(r), "industrial": r.industrial.model_dump(mode="json")}


@router.get("/sources")
def land_sources(refresh: bool = Query(False)) -> Dict[str, Any]:
    r = _report(refresh)
    return {**_meta(r), "sources": [s.model_dump(mode="json") for s in r.sources]}


@router.get("/map")
def land_map(refresh: bool = Query(False)) -> Dict[str, Any]:
    """Map layers as GeoJSON.

    Only layers that actually exist in an acquired source are emitted, and a
    layer is marked ``data_kind`` so the UI never presents planning geometry as
    live physical state.
    """
    r = _report(refresh)
    layers: List[Dict[str, Any]] = []

    pa_features = [
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [p.outer_ring]},
            "properties": {
                "name": p.name,
                "code": p.code,
                "region": p.region,
                "area_sqm": p.area_sqm,
                "land_use_coverage_pct": p.land_use_coverage_pct,
                "dominant_category": p.dominant_category,
            },
        }
        for p in r.planning.planning_areas
        if p.outer_ring
    ]
    if pa_features:
        layers.append({
            "id": "planning_areas",
            "label": "Master Plan 2025 Planning Areas",
            "data_kind": r.planning.data_kind,
            "data": {"type": "FeatureCollection", "features": pa_features},
        })

    gls_features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s.longitude, s.latitude]},
            "properties": {
                "location": s.location,
                "development_code": s.development_code,
                "planning_area": s.planning_area,
                "site_area_sqm": s.site_area_sqm,
                "gpr": s.gross_plot_ratio,
                "award_year": s.award_year,
            },
        }
        for s in r.gls.latest_sites
        if s.longitude is not None and s.latitude is not None
    ]
    if gls_features:
        layers.append({
            "id": "gls_sites",
            "label": "Government Land Sales sites (awarded)",
            "data_kind": "historical",
            "data": {"type": "FeatureCollection", "features": gls_features},
        })

    return {
        **_meta(r),
        "layers": layers,
        "layers_unavailable": {
            "land_use": "Land-use zone geometry is not served as a map layer; use /use for aggregates.",
            "cadastral": (
                "Full cadastral geometry is ~145 MB and is not served inline; "
                "parcel statistics are on /gls."
            ),
        },
    }
