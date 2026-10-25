
"""Energy Intelligence API."""
from __future__ import annotations
import logging, threading, time
from fastapi import APIRouter, HTTPException, Query
from .agent import run_energy_agent
from .data import clear_energy_source_cache
from .models import EnergyReport

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/infrastructure/energy", tags=["infrastructure-energy"])
_lock = threading.Lock()
_cache = {"report": None, "expires_at": 0.0, "cached_at": 0.0}

def get_energy_report(refresh: bool = False) -> EnergyReport:
    request_started = time.monotonic()
    with _lock:
        if _cache["report"] is not None and refresh and _cache["cached_at"] > request_started:
            return _cache["report"]
        if _cache["report"] is not None and not refresh and time.time() < _cache["expires_at"]:
            return _cache["report"]
        try:
            if refresh:
                clear_energy_source_cache()
            report = run_energy_agent()
            _cache["report"] = report
            _cache["expires_at"] = time.time() + (300 if report.status != "OK" else 1800)
            _cache["cached_at"] = time.monotonic()
            return report
        except Exception as exc:
            log.exception("Energy report generation failed")
            raise HTTPException(status_code=502, detail=f"Energy data unavailable: {exc}") from exc


def peek_energy_report():
    """Return the cached report only while it is still fresh. Never runs the
    agent and never blocks: ``get_energy_report`` holds ``_lock`` for the
    whole run, so taking it here would make a cheap Overview card read wait
    behind a full data fetch. A cold or expired cache reads as ``None``.
    """
    cached = _cache["report"]
    if cached is not None and time.time() < _cache["expires_at"]:
        return cached
    return None

@router.get("/report")
def energy_report(refresh: bool = Query(False)):
    return get_energy_report(refresh).model_dump(mode="json")

@router.get("/sources")
def energy_sources(refresh: bool = Query(False)):
    report = get_energy_report(refresh)
    return {"generated_at": report.generated_at.isoformat(), "sources": [s.model_dump(mode="json") for s in report.sources]}


def start_energy_warmup() -> None:
    """Trigger one energy report build in a background thread at startup."""
    def _run():
        try:
            get_energy_report(refresh=True)
        except Exception as exc:
            log.warning("Energy warmup failed (non-fatal): %s", exc)
    threading.Thread(target=_run, daemon=True, name="energy-warmup").start()
