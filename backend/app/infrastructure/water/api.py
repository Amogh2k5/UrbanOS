"""FastAPI routes for the Water domain (same style as the Fire/Flood routers)."""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.app.infrastructure.water.agent import run_water_agent
from backend.app.infrastructure.water.models import WaterReport

log = logging.getLogger(__name__)
router = APIRouter(tags=["infrastructure-water"])

_OK_TTL_S = 600.0     # upstream datasets are annual; the source layer also caches for hours
_ERR_TTL_S = 60.0     # retry sooner when something failed
_lock = threading.Lock()
_cache: Dict[str, Any] = {"report": None, "expires_at": 0.0}


def get_water_report(refresh: bool = False) -> WaterReport:
    now = time.time()
    with _lock:
        cached: Optional[WaterReport] = _cache["report"]
        if cached is not None and not refresh and now < _cache["expires_at"]:
            return cached
        report = run_water_agent()
        _cache["report"] = report
        _cache["expires_at"] = now + (_ERR_TTL_S if report.errors else _OK_TTL_S)
        return report


def start_water_warmup() -> None:
    """Fetch the official data in a background thread at server start, so the first page
    load finds a ready report instead of waiting for the sources. Concurrent requests wait on
    the same lock and reuse the result (no duplicate fetches). Disabled under pytest, or with
    URBANOS_WATER_WARMUP=0."""
    if os.getenv("URBANOS_WATER_WARMUP", "1") != "1" or "pytest" in sys.modules:
        return

    def _run() -> None:
        try:
            get_water_report()
            log.info("Water warm-up complete")
        except Exception:  # noqa: BLE001
            log.exception("Water warm-up failed")

    threading.Thread(target=_run, name="water-warmup", daemon=True).start()


def _report(refresh: bool) -> WaterReport:
    try:
        return get_water_report(refresh)
    except Exception as exc:  # noqa: BLE001
        log.exception("Water report generation failed")
        raise HTTPException(status_code=500, detail=f"water agent error: {exc}")


def _meta(r: WaterReport) -> Dict[str, Any]:
    return {"generated_at": r.generated_at.isoformat(), "data_timestamps": r.data_timestamps, "errors": r.errors, "warnings": r.warnings}


@router.get("/api/water/report")
def water_report(refresh: bool = Query(False)) -> Dict[str, Any]:
    """Full structured WaterReport (used by the City Coordinator and the frontend)."""
    return _report(refresh).model_dump(mode="json")


@router.get("/api/water/overview")
def water_overview(refresh: bool = Query(False)) -> Dict[str, Any]:
    r = _report(refresh)
    return {
        **_meta(r),
        "overall_status": r.overall_status,
        "overall_risk": r.overall_risk,
        "confidence": r.confidence,
        "headline": {
            "potable_total": r.usage.potable_total.model_dump(mode="json") if r.usage.potable_total else None,
            "newater": r.newater.latest.model_dump(mode="json") if r.newater.latest else None,
            "drain_sensor_count": r.drain.sensor_count,
            "drain_readings_available": r.drain.readings_available,
            "reservoir_storage_available": r.supply.reservoir_storage_available,
            "forecast_available": r.forecast.available,
        },
        "alerts": [a.model_dump(mode="json") for a in r.alerts],
        "insights": [i.model_dump(mode="json") for i in r.insights],
        "limitations": r.limitations,
    }


@router.get("/api/water/supply")
def water_supply(refresh: bool = Query(False)) -> Dict[str, Any]:
    r = _report(refresh)
    return {**_meta(r), "supply": r.supply.model_dump(mode="json")}


@router.get("/api/water/drain")
def water_drain(refresh: bool = Query(False)) -> Dict[str, Any]:
    r = _report(refresh)
    return {**_meta(r), "drain": r.drain.model_dump(mode="json")}


@router.get("/api/water/usage")
def water_usage(refresh: bool = Query(False)) -> Dict[str, Any]:
    r = _report(refresh)
    return {**_meta(r), "usage": r.usage.model_dump(mode="json")}


@router.get("/api/water/forecast")
def water_forecast(refresh: bool = Query(False)) -> Dict[str, Any]:
    r = _report(refresh)
    return {**_meta(r), "forecast": r.forecast.model_dump(mode="json")}


@router.get("/api/water/newater")
def water_newater(refresh: bool = Query(False)) -> Dict[str, Any]:
    r = _report(refresh)
    return {**_meta(r), "newater": r.newater.model_dump(mode="json")}


@router.get("/api/water/quality")
def water_quality(refresh: bool = Query(False)) -> Dict[str, Any]:
    r = _report(refresh)
    return {**_meta(r), "quality": r.quality.model_dump(mode="json")}


@router.get("/api/water/sources")
def water_sources(refresh: bool = Query(False)) -> Dict[str, Any]:
    r = _report(refresh)
    return {**_meta(r), "sources": [s.model_dump(mode="json") for s in r.sources]}


@router.get("/api/water/map")
def water_map(refresh: bool = Query(False)) -> Dict[str, Any]:
    """GeoJSON of PUB drain sensors. Condition is UNAVAILABLE unless real readings exist."""
    r = _report(refresh)
    features = []
    for st in r.drain.sensors:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [st.sensor.longitude, st.sensor.latitude]},
            "properties": {
                "id": st.sensor.id,
                "name": st.sensor.name,
                "condition": st.condition,
                "percentage": st.percentage,
                "water_level_m": st.water_level_m,
                "reference_depth_m": st.reference_depth_m,
                "observed_at": st.observed_at.isoformat() if st.observed_at else None,
                "trend": st.trend,
            },
        })
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "data_kind": r.drain.data_kind,
            "readings_available": r.drain.readings_available,
            "sensor_count": r.drain.sensor_count,
            "thresholds": r.drain.thresholds,
            "limitations": r.drain.limitations,
            **_meta(r),
        },
    }
