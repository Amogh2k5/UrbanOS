"""FastAPI routes for the Waste Management domain (same style as the Water / Fire routers)."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query

from backend.app.infrastructure.waste.agent import run_waste_agent
from backend.app.infrastructure.waste.models import WasteReport
from backend.app.infrastructure.waste.sources import FACILITY_LABELS, WasteSnapshot, fetch_waste_snapshot

log = logging.getLogger(__name__)
router = APIRouter(tags=["infrastructure-waste"])

_OK_TTL_S = 600.0     # upstream data is annual / static; the source layer also caches for hours
_ERR_TTL_S = 60.0     # retry sooner when something failed
_LOADING_TTL_S = 10.0  # location layers still downloading: re-check often so they appear promptly
_lock = threading.Lock()
_cache: Dict[str, Any] = {"report": None, "snapshot": None, "expires_at": 0.0}


def get_waste_bundle(refresh: bool = False) -> Tuple[WasteReport, WasteSnapshot]:
    """Report + the snapshot it was built from (the snapshot carries the map points)."""
    now = time.time()
    with _lock:
        if _cache["report"] is not None and not refresh and now < _cache["expires_at"]:
            return _cache["report"], _cache["snapshot"]
        snap = fetch_waste_snapshot(wait_for_layers=False)
        report = run_waste_agent(fetcher=lambda: snap)
        loading = any(src.status == "loading" for src in report.sources)
        ttl = _LOADING_TTL_S if loading else (_ERR_TTL_S if report.errors else _OK_TTL_S)
        _cache.update(report=report, snapshot=snap, expires_at=now + ttl)
        return report, snap


def get_waste_report(refresh: bool = False) -> WasteReport:
    return get_waste_bundle(refresh)[0]


def _bundle(refresh: bool) -> Tuple[WasteReport, WasteSnapshot]:
    try:
        return get_waste_bundle(refresh)
    except Exception as exc:  # noqa: BLE001
        log.exception("Waste report generation failed")
        raise HTTPException(status_code=500, detail=f"waste agent error: {exc}")


def _meta(r: WasteReport) -> Dict[str, Any]:
    return {"generated_at": r.generated_at.isoformat(), "data_timestamps": r.data_timestamps, "errors": r.errors, "warnings": r.warnings}


@router.get("/api/waste/report")
def waste_report(refresh: bool = Query(False)) -> Dict[str, Any]:
    """Full structured WasteReport (used by the City Coordinator and the frontend)."""
    return _bundle(refresh)[0].model_dump(mode="json")


@router.get("/api/waste/overview")
def waste_overview(refresh: bool = Query(False)) -> Dict[str, Any]:
    r = _bundle(refresh)[0]
    return {
        **_meta(r), "status": r.status, "overall_risk": r.overall_risk, "confidence": r.confidence, "summary": r.summary,
        "kpis": [k.model_dump(mode="json") for k in r.kpis],
        "alerts": [a.model_dump(mode="json") for a in r.alerts],
        "limitations": r.limitations,
    }


@router.get("/api/waste/categories")
def waste_categories(refresh: bool = Query(False)) -> Dict[str, Any]:
    r = _bundle(refresh)[0]
    return {**_meta(r), "categories": r.categories.model_dump(mode="json")}


@router.get("/api/waste/food")
def waste_food(refresh: bool = Query(False)) -> Dict[str, Any]:
    r = _bundle(refresh)[0]
    return {**_meta(r), "food": r.food.model_dump(mode="json")}


@router.get("/api/waste/services")
def waste_services(refresh: bool = Query(False)) -> Dict[str, Any]:
    r = _bundle(refresh)[0]
    return {**_meta(r), "services": r.services.model_dump(mode="json")}


@router.get("/api/waste/sources")
def waste_sources(refresh: bool = Query(False)) -> Dict[str, Any]:
    r = _bundle(refresh)[0]
    return {**_meta(r), "sources": [s.model_dump(mode="json") for s in r.sources]}


@router.get("/api/waste/map")
def waste_map(refresh: bool = Query(False), kind: Optional[str] = Query(None, description="recycling_bins | ewaste | lighting_waste | disposal_sites")) -> Dict[str, Any]:
    """GeoJSON of NEA waste infrastructure. REFERENCE data (static listings), not live."""
    if kind is not None and kind not in FACILITY_LABELS:
        raise HTTPException(status_code=422, detail=f"unknown kind '{kind}'; expected one of {sorted(FACILITY_LABELS)}")
    r, snap = _bundle(refresh)
    features: List[Dict[str, Any]] = []
    for k, layer in snap.facilities.items():
        if kind and k != kind:
            continue
        for f in layer.facilities:
            props: Dict[str, Any] = {"kind": k, "name": f.name}
            if k != "recycling_bins":          # ~10k+ bins: keep the payload small
                props.update(address=f.address, description=f.description, record_date=f.record_date)
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(f.lon, 5), round(f.lat, 5)]}, "properties": props})
    return {
        "type": "FeatureCollection", "features": features,
        "metadata": {
            "data_kind": "reference" if features else "unavailable",
            "kinds": [k.model_dump(mode="json") for k in r.infrastructure.kinds],
            "limitations": r.infrastructure.limitations,
            **_meta(r),
        },
    }
