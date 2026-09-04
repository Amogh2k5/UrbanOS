"""Transit API router for backend integration."""

from __future__ import annotations

import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from datetime import datetime

from backend.app.mobility.transit.collector import (
    TransitCollector,
    collect_transit_reference_once,
    collect_transit_alerts_once,
    collect_transit_all_once,
    get_transit_stats,
)
from backend.app.mobility.transit.storage import TransitDataStore
from backend.app.mobility.transit.models import (
    BusServiceResponse,
    BusRouteResponse,
    BusStopResponse,
    TrainAlertResponse,
    TransitStatusResponse,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mobility/transit", tags=["mobility", "transit"])


@router.get("/status", response_model=TransitStatusResponse)
async def get_transit_status(
    limit_alerts: int = Query(20, ge=1, le=100, description="Max train alerts to return")
) -> TransitStatusResponse:
    """Get overall transit system status with recent train alerts."""
    try:
        store = TransitDataStore()
        stats = store.get_stats()
        alerts = store.get_latest_train_alerts(limit=limit_alerts)

        return TransitStatusResponse(
            generated_at=datetime.now(),
            bus_services_count=stats["bus_services"],
            bus_routes_count=stats["bus_routes"],
            bus_stops_count=stats["bus_stops"],
            active_train_alerts=stats["train_alerts"],
            train_alerts=[
                TrainAlertResponse(
                    line=a.line,
                    direction=a.direction,
                    station=a.station,
                    message=a.message,
                    status=a.status,
                )
                for a in alerts
            ],
            limitations=[
                "Bus arrival predictions (BusArrivalv2) not available with current LTA account",
                "Taxi availability not available with current LTA account",
                "Reference data (services/routes/stops) updated daily",
                "Train alerts collected every 5 minutes",
            ],
        )
    except Exception as e:
        log.exception("Failed to get transit status")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bus-services", response_model=List[BusServiceResponse])
async def get_bus_services(
    limit: int = Query(100, ge=1, le=1000),
    service_no: Optional[str] = Query(None, description="Filter by service number"),
    operator: Optional[str] = Query(None, description="Filter by operator (SBST, SMRT, etc.)"),
) -> List[BusServiceResponse]:
    """Get bus services reference data."""
    try:
        store = TransitDataStore()
        if service_no and operator:
            svc = store.get_bus_service(service_no, operator, 1)
            if svc:
                return [_stored_to_response(svc)]
            return []
        elif service_no:
            # Search all directions
            results = []
            for direction in [1, 2]:
                for op in ["SBST", "SMRT", "TTS", "GAS"]:
                    svc = store.get_bus_service(service_no, op, direction)
                    if svc:
                        results.append(_stored_to_response(svc))
            return results[:limit]
        else:
            services = store.get_bus_services(limit=limit)
            if operator:
                services = [s for s in services if s.operator == operator]
            return [_stored_to_response(s) for s in services[:limit]]
    except Exception as e:
        log.exception("Failed to get bus services")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bus-routes", response_model=List[BusRouteResponse])
async def get_bus_routes(
    service_no: str = Query(..., description="Bus service number"),
    operator: str = Query(..., description="Operator (SBST, SMRT, etc.)"),
    direction: int = Query(..., ge=1, le=2, description="Direction (1 or 2)"),
) -> List[BusRouteResponse]:
    """Get bus route (stop sequence) for a specific service."""
    try:
        store = TransitDataStore()
        routes = store.get_bus_routes_for_service(service_no, operator, direction)
        return [
            BusRouteResponse(
                service_no=r.service_no,
                operator=r.operator,
                direction=r.direction,
                stop_sequence=r.stop_sequence,
                bus_stop_code=r.bus_stop_code,
                distance=r.distance,
                wd_first_bus=r.wd_first_bus,
                wd_last_bus=r.wd_last_bus,
                sat_first_bus=r.sat_first_bus,
                sat_last_bus=r.sat_last_bus,
                sun_first_bus=r.sun_first_bus,
                sun_last_bus=r.sun_last_bus,
            )
            for r in routes
        ]
    except Exception as e:
        log.exception("Failed to get bus routes")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bus-stops", response_model=List[BusStopResponse])
async def get_bus_stops(
    bus_stop_code: Optional[str] = Query(None, description="Specific bus stop code"),
    lat: Optional[float] = Query(None, description="Latitude for nearby search"),
    lon: Optional[float] = Query(None, description="Longitude for nearby search"),
    radius_km: float = Query(1.0, ge=0.1, le=10.0, description="Search radius in km"),
    limit: int = Query(50, ge=1, le=200),
) -> List[BusStopResponse]:
    """Get bus stop information."""
    try:
        store = TransitDataStore()

        if bus_stop_code:
            stop = store.get_bus_stop(bus_stop_code)
            if stop:
                return [_stored_stop_to_response(stop)]
            return []

        if lat is not None and lon is not None:
            stops = store.get_bus_stops_near(lat, lon, radius_km=radius_km, limit=limit)
            return [_stored_stop_to_response(s) for s in stops]

        raise HTTPException(status_code=400, detail="Provide either bus_stop_code or lat/lon")
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Failed to get bus stops")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/train-alerts", response_model=List[TrainAlertResponse])
async def get_train_alerts(
    line: Optional[str] = Query(None, description="Filter by MRT line (NSL, EWL, CCL, DTL, TEL, etc.)"),
    limit: int = Query(20, ge=1, le=100),
) -> List[TrainAlertResponse]:
    """Get train service alerts."""
    try:
        store = TransitDataStore()
        if line:
            alerts = store.get_train_alerts_for_line(line, limit=limit)
        else:
            alerts = store.get_latest_train_alerts(limit=limit)

        return [
            TrainAlertResponse(
                line=a.line,
                direction=a.direction,
                station=a.station,
                message=a.message,
                status=a.status,
            )
            for a in alerts
        ]
    except Exception as e:
        log.exception("Failed to get train alerts")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/collect/reference")
async def collect_reference_data() -> dict:
    """Trigger bus reference data collection (services, routes, stops)."""
    try:
        result = collect_transit_reference_once()
        return {
            "timestamp": result.timestamp,
            "bus_services_received": result.bus_services_received,
            "bus_services_stored": result.bus_services_stored,
            "bus_routes_received": result.bus_routes_received,
            "bus_routes_stored": result.bus_routes_stored,
            "bus_stops_received": result.bus_stops_received,
            "bus_stops_stored": result.bus_stops_stored,
            "errors": result.errors,
        }
    except Exception as e:
        log.exception("Transit reference collection failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/collect/alerts")
async def collect_train_alerts() -> dict:
    """Trigger train service alerts collection."""
    try:
        result = collect_transit_alerts_once()
        return {
            "timestamp": result.timestamp,
            "train_alerts_received": result.train_alerts_received,
            "train_alerts_stored": result.train_alerts_stored,
            "errors": result.errors,
        }
    except Exception as e:
        log.exception("Train alerts collection failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/collect/all")
async def collect_all_transit() -> dict:
    """Trigger full transit data collection."""
    try:
        result = collect_transit_all_once()
        return {
            "timestamp": result.timestamp,
            "bus_services_received": result.bus_services_received,
            "bus_services_stored": result.bus_services_stored,
            "bus_routes_received": result.bus_routes_received,
            "bus_routes_stored": result.bus_routes_stored,
            "bus_stops_received": result.bus_stops_received,
            "bus_stops_stored": result.bus_stops_stored,
            "train_alerts_received": result.train_alerts_received,
            "train_alerts_stored": result.train_alerts_stored,
            "errors": result.errors,
        }
    except Exception as e:
        log.exception("Transit collection failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_stats() -> dict:
    """Get transit storage statistics."""
    try:
        return get_transit_stats()
    except Exception as e:
        log.exception("Transit stats failed")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _stored_to_response(svc) -> BusServiceResponse:
    return BusServiceResponse(
        service_no=svc.service_no,
        operator=svc.operator,
        direction=svc.direction,
        category=svc.category,
        origin_code=svc.origin_code,
        destination_code=svc.destination_code,
        am_peak_freq=svc.am_peak_freq,
        am_offpeak_freq=svc.am_offpeak_freq,
        pm_peak_freq=svc.pm_peak_freq,
        pm_offpeak_freq=svc.pm_offpeak_freq,
        loop_desc=svc.loop_desc,
    )


def _stored_stop_to_response(stop) -> BusStopResponse:
    return BusStopResponse(
        bus_stop_code=stop.bus_stop_code,
        road_name=stop.road_name,
        description=stop.description,
        latitude=stop.latitude,
        longitude=stop.longitude,
    )