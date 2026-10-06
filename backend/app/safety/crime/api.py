"""FastAPI routes for the Safety -> Crime domain."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from backend.app.safety.crime.agent import run_crime_agent

router = APIRouter(prefix="/api/crime", tags=["crime"])


@router.get("/report")
def crime_report() -> Dict[str, Any]:
    """Return the current verified official-data CrimeReport.

    This is not a live crime-incident feed. The response carries the source
    period and limitations so the frontend can distinguish historical data
    from real-time operational information.
    """
    try:
        return run_crime_agent().model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"crime data unavailable: {exc}") from exc
