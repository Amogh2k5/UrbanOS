"""Traffic API router for backend integration."""

from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from backend.app.mobility.traffic.agent import run_traffic_agent
from backend.app.mobility.traffic.models import TrafficReport

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mobility/traffic", tags=["mobility", "traffic"])


@router.get("/report", response_model=TrafficReport)
async def get_traffic_report(
    offline: bool = Query(False, description="Use offline mode (deterministic fixture)")
) -> TrafficReport:
    """Get combined traffic report with ML predictions and live incidents."""
    try:
        report = run_traffic_agent(offline=offline)
        return report
    except Exception as e:
        log.exception("Failed to generate traffic report")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/report/offline", response_model=TrafficReport)
async def get_traffic_report_offline() -> TrafficReport:
    """Get traffic report in offline mode (deterministic fixture)."""
    return await get_traffic_report(offline=True)