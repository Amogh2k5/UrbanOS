"""FastAPI routes for Singapore Housing Intelligence."""
from __future__ import annotations
import logging
import threading
import time
from fastapi import APIRouter, HTTPException, Query
from .agent import run_housing_agent
from .models import HousingReport

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/planning/housing", tags=["planning-housing"])
_lock = threading.Lock()
_cache: dict = {"report": None, "expires_at": 0.0}

def get_housing_report(refresh: bool = False) -> HousingReport:
    now = time.time()
    with _lock:
        report = _cache["report"]
        if report is not None and not refresh and now < _cache["expires_at"]:
            return report
        try:
            report = run_housing_agent()
        except Exception as exc:
            log.exception("Housing report generation failed")
            raise HTTPException(status_code=502, detail=f"Housing data unavailable: {exc}") from exc
        _cache["report"] = report
        # Annual/quarterly sources don't need aggressive polling. Retry sooner for partial reports.
        _cache["expires_at"] = now + (300 if report.status == "UNAVAILABLE" else 1800)
        return report

@router.get("/report")
def housing_report(refresh: bool = Query(False)):
    return get_housing_report(refresh).model_dump(mode="json")

@router.get("/sources")
def housing_sources(refresh: bool = Query(False)):
    report = get_housing_report(refresh)
    return {"generated_at": report.generated_at, "sources": [s.model_dump(mode="json") for s in report.sources],
            "errors": report.errors, "warnings": report.warnings, "limitations": report.limitations}


def start_housing_warmup() -> None:
    """Trigger one housing report build in a background thread at startup.

    Annual/quarterly housing sources are slow enough that a warm cache avoids
    the first dashboard request paying the full fetch latency. Fails silently;
    the accessor re-runs on demand.
    """
    def _run():
        try:
            get_housing_report(refresh=True)
        except Exception as exc:
            log.warning("Housing warmup failed (non-fatal): %s", exc)
    threading.Thread(target=_run, daemon=True, name="housing-warmup").start()
