"""Roads API routes for UrbanOS."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from backend.app.mobility.roads.data import (
    RoadWorksApiClient,
    RoadOpeningsApiClient,
    TaxiStandsApiClient,
    RoadDataProcessor,
    RoadWork,
    RoadOpening,
    TaxiStand,
    RoadWorkEvent,
    TaxiStandInfo,
    parse_datetime,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mobility/roads", tags=["mobility", "roads"])


# ============================================================
# ROAD WORKS
# ============================================================

@router.get("/works")
async def get_road_works(
    limit: int = Query(100, ge=1, le=500, description="Number of records to return"),
    offset: int = Query(0, ge=0, description="Number of records to skip"),
    status: Optional[str] = Query(None, description="Filter by status: active, upcoming, completed"),
    road_name: Optional[str] = Query(None, description="Filter by road name (partial match)"),
) -> Dict[str, Any]:
    """Get road works with optional filtering and pagination."""
    try:
        client = RoadWorksApiClient()
        raw_works = []
        
        # Fetch all pages (or up to limit)
        for work in client.fetch_all():
            raw_works.append(work)
            if len(raw_works) >= limit + offset:
                break
        
        # Process raw data into Pydantic models
        all_works = RoadDataProcessor.process_road_works(raw_works)
        
        # Apply filters
        filtered = all_works
        if status:
            if status == "active":
                filtered = [w for w in filtered if w.is_active]
            elif status == "upcoming":
                filtered = [w for w in filtered if w.is_upcoming]
            elif status == "completed":
                filtered = [w for w in filtered if not w.is_active and not w.is_upcoming]
        
        if road_name:
            filtered = [w for w in filtered if road_name.lower() in w.road_name.lower()]
        
        # Apply pagination
        total = len(filtered)
        paginated = filtered[offset:offset + limit]
        
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "works": [w.model_dump() for w in paginated]
        }
    except Exception as e:
        log.exception("Failed to fetch road works")
        raise HTTPException(status_code=500, detail=f"Failed to fetch road works: {e}")


@router.get("/works/{event_id}")
async def get_road_work(event_id: str) -> Dict[str, Any]:
    """Get a specific road work by event ID."""
    try:
        client = RoadWorksApiClient()
        raw_works = []
        for work in client.fetch_all():
            raw_works.append(work)
            if work.get("EventID") == event_id or work.get("event_id") == event_id:
                break
        works = RoadDataProcessor.process_road_works(raw_works)
        for work in works:
            if work.event_id == event_id:
                return work.model_dump()
        raise HTTPException(status_code=404, detail="Road work not found")
    except Exception as e:
        log.exception("Failed to fetch road work")
        raise HTTPException(status_code=500, detail=f"Failed to fetch road work: {e}")


# ============================================================
# ROAD OPENINGS
# ============================================================

@router.get("/openings")
async def get_road_openings(
    limit: int = Query(100, ge=1, le=500, description="Number of records to return"),
    offset: int = Query(0, ge=0, description="Number of records to skip"),
    status: Optional[str] = Query(None, description="Filter by status: active, upcoming, completed"),
) -> Dict[str, Any]:
    """Get road openings with optional filtering and pagination."""
    try:
        client = RoadOpeningsApiClient()
        raw_openings = []
        for opening in client.fetch_all():
            raw_openings.append(opening)
        
        # Process raw data into Pydantic models
        all_openings = RoadDataProcessor.process_road_openings(raw_openings)
        
        filtered = all_openings
        if status:
            if status == "active":
                filtered = [o for o in filtered if o.is_active]
            elif status == "upcoming":
                filtered = [o for o in filtered if o.is_upcoming]
            elif status == "completed":
                filtered = [o for o in filtered if not o.is_active and not o.is_upcoming]
        
        total = len(filtered)
        paginated = filtered[offset:offset + limit]
        
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "openings": [o.model_dump() for o in paginated]
        }
    except Exception as e:
        log.exception("Failed to fetch road openings")
        raise HTTPException(status_code=500, detail=f"Failed to fetch road openings: {e}")


@router.get("/openings/{event_id}")
async def get_road_opening(event_id: str) -> Dict[str, Any]:
    """Get a specific road opening by event ID."""
    try:
        client = RoadOpeningsApiClient()
        raw_openings = []
        for opening in client.fetch_all():
            raw_openings.append(opening)
            if opening.get("EventID") == event_id or opening.get("event_id") == event_id:
                break
        openings = RoadDataProcessor.process_road_openings(raw_openings)
        for opening in openings:
            if opening.event_id == event_id:
                return opening.model_dump()
        raise HTTPException(status_code=404, detail="Road opening not found")
    except Exception as e:
        log.exception("Failed to fetch road opening")
        raise HTTPException(status_code=500, detail=f"Failed to fetch road opening: {e}")


# ============================================================
# TAXI STANDS
# ============================================================

@router.get("/taxi-stands")
async def get_taxi_stands(
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    bfa_only: bool = Query(False, description="Filter to BFA accessible stands only"),
    ownership: Optional[str] = Query(None, description="Filter by ownership type"),
) -> Dict[str, Any]:
    """Get taxi stands with optional filtering."""
    try:
        raw_stands = TaxiStandsApiClient().fetch()
        
        # Process raw data into Pydantic models
        stands = RoadDataProcessor.process_taxi_stands(raw_stands)
        
        filtered = stands
        if bfa_only:
            filtered = [s for s in stands if s.is_bfa_accessible]
        if ownership:
            filtered = [s for s in filtered if ownership.lower() in s.ownership.lower()]
        
        total = len(filtered)
        paginated = filtered[offset:offset + limit]
        
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "stands": [s.model_dump() for s in paginated]
        }
    except Exception as e:
        log.exception("Failed to fetch taxi stands")
        raise HTTPException(status_code=500, detail=f"Failed to fetch taxi stands: {e}")


@router.get("/taxi-stands/{taxi_code}")
async def get_taxi_stand(taxi_code: str) -> Dict[str, Any]:
    """Get a specific taxi stand by code."""
    try:
        raw_stands = TaxiStandsApiClient().fetch()
        stands = RoadDataProcessor.process_taxi_stands(raw_stands)
        for stand in stands:
            if stand.taxi_code == taxi_code:
                return stand.model_dump()
        raise HTTPException(status_code=404, detail="Taxi stand not found")
    except Exception as e:
        log.exception("Failed to fetch taxi stand")
        raise HTTPException(status_code=500, detail=f"Failed to fetch taxi stand: {e}")


# ============================================================
# UNIFIED ROAD EVENTS (WORKS + OPENINGS)
# ============================================================

@router.get("/events")
async def get_road_events(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    event_type: Optional[str] = Query(None, description="Filter by type: road_work, road_opening"),
    status: Optional[str] = Query(None, description="Filter by status: active, upcoming, completed"),
) -> Dict[str, Any]:
    """Get unified road events (works + openings) with unified schema."""
    try:
        events = []
        
        # Fetch road works
        if event_type in [None, "road_work"]:
            raw_works = list(RoadWorksApiClient().fetch_all())
            works = RoadDataProcessor.process_road_works(raw_works)
            for work in works:
                events.append({
                    "event_id": work.event_id,
                    "event_type": "road_work",
                    "road_name": work.road_name,
                    "start_date": work.start_date,
                    "end_date": work.end_date,
                    "svc_dept": work.svc_dept,
                    "description": work.other,
                    "status": "active" if work.is_active else ("upcoming" if work.is_upcoming else "completed")
                })
        
        # Fetch road openings
        if event_type in [None, "road_opening"]:
            raw_openings = list(RoadOpeningsApiClient().fetch_all())
            openings = RoadDataProcessor.process_road_openings(raw_openings)
            for opening in openings:
                events.append({
                    "event_id": opening.event_id,
                    "event_type": "road_opening",
                    "road_name": opening.road_name,
                    "start_date": opening.start_date,
                    "end_date": opening.end_date,
                    "svc_dept": opening.svc_dept,
                    "description": opening.other,
                    "status": "active" if opening.is_active else ("upcoming" if opening.is_upcoming else "completed")
                })
        
        # Apply filters
        filtered = events
        if status:
            filtered = [e for e in filtered if e["status"] == status]
        
        total = len(filtered)
        paginated = filtered[offset:offset + limit]
        
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "events": paginated
        }
    except Exception as e:
        log.exception("Failed to fetch road events")
        raise HTTPException(status_code=500, detail=f"Failed to fetch road events: {e}")


# ============================================================
# ROAD SPEED CONTEXT (from TrafficSpeedBands)
# ============================================================

@router.get("/speed-context")
async def get_road_speed_context() -> Dict[str, Any]:
    """
    Get current road speed context from TrafficSpeedBands.
    Provides current road network speed context for the Roads page.
    """
    try:
        from backend.app.mobility.traffic.api import TrafficSpeedBandsV2ApiClient
        from backend.app.mobility.traffic.data import TrafficObservationCSVStore
        from backend.app.mobility.traffic.predictor import TrafficPredictor
        
        store = TrafficObservationCSVStore()
        predictor = TrafficPredictor()
        features_df, link_preds, diagnostics = predictor.predict_latest(store)
        
        # Aggregate by road
        road_speeds = {}
        for pred in link_preds:
            road = pred.road_name
            if road not in road_speeds:
                road_speeds[road] = {"current": [], "predicted": [], "count": 0}
            road_speeds[road]["current"].append(pred.current_speed)
            road_speeds[road]["predicted"].append(pred.predicted_speed)
            road_speeds[road]["count"] += 1
        
        # Calculate averages
        road_summary = []
        for road, data in road_speeds.items():
            if data["count"] > 0:
                avg_current = sum(data["current"]) / len(data["current"])
                avg_predicted = sum(data["predicted"]) / len(data["predicted"])
                road_summary.append({
                    "road": road,
                    "avg_current_speed": round(avg_current, 1),
                    "avg_predicted_speed": round(avg_predicted, 1),
                    "avg_change": round(avg_predicted - avg_current, 1),
                    "segment_count": data["count"]
                })
        
        return {
            "timestamp": datetime.now().isoformat(),
            "roads": road_summary[:50],  # Top 50
            "total_roads": len(road_summary)
        }
    except Exception as e:
        log.exception("Failed to get road speed context")
        raise HTTPException(status_code=500, detail=f"Failed to get road speed context: {e}")


# ============================================================
# ANALYTICS
# ============================================================

@router.get("/analytics/summary")
async def get_roads_analytics() -> Dict[str, Any]:
    """Get roads analytics summary."""
    try:
        # Fetch all data
        raw_works = list(RoadWorksApiClient().fetch_all())
        raw_openings = list(RoadOpeningsApiClient().fetch_all())
        raw_stands = TaxiStandsApiClient().fetch()
        
        # Process raw data into Pydantic models
        road_works = RoadDataProcessor.process_road_works(raw_works)
        road_openings = RoadDataProcessor.process_road_openings(raw_openings)
        taxi_stands = RoadDataProcessor.process_taxi_stands(raw_stands)
        
        # Road works stats
        active_works = [w for w in road_works if w.is_active]
        upcoming_works = [w for w in road_works if w.is_upcoming]
        completed_works = [w for w in road_works if not w.is_active and not w.is_upcoming]
        
        # Road openings stats
        active_openings = [o for o in road_openings if o.is_active]
        upcoming_openings = [o for o in road_openings if o.is_upcoming]
        
        # Taxi stands stats
        bfa_stands = [s for s in taxi_stands if s.is_bfa_accessible]
        ownership_counts = {}
        for s in taxi_stands:
            ownership_counts[s.ownership] = ownership_counts.get(s.ownership, 0) + 1
        
        return {
            "road_works": {
                "total": len(road_works),
                "active": len(active_works),
                "upcoming": len(upcoming_works),
                "completed": len(completed_works),
            },
            "road_openings": {
                "total": len(road_openings),
                "active": len(active_openings),
                "upcoming": len(upcoming_openings),
            },
            "taxi_stands": {
                "total": len(taxi_stands),
                "bfa_accessible": len(bfa_stands),
                "by_ownership": ownership_counts,
            },
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        log.exception("Failed to generate analytics")
        raise HTTPException(status_code=500, detail=f"Failed to generate analytics: {e}")


@router.get("/map-data")
async def get_map_data() -> Dict[str, Any]:
    """
    Get data for the Roads map visualization.
    Returns geoJSON-like structure for map rendering.
    """
    try:
        # Fetch all data
        raw_works = list(RoadWorksApiClient().fetch_all())
        raw_openings = list(RoadOpeningsApiClient().fetch_all())
        raw_stands = TaxiStandsApiClient().fetch()
        
        # Process taxi stands (have coordinates)
        taxi_stands = RoadDataProcessor.process_taxi_stands(raw_stands)
        
        features = []
        
        # Add taxi stands (have coordinates)
        for stand in taxi_stands:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [stand.longitude, stand.latitude]
                },
                "properties": {
                    "type": "taxi_stand",
                    "taxi_code": stand.taxi_code,
                    "name": stand.name,
                    "ownership": stand.ownership,
                    "type": stand.type,
                    "bfa_accessible": stand.is_bfa_accessible,
                }
            })
        
        return {
            "type": "FeatureCollection",
            "features": features,
            "bbox": [103.5, 1.15, 104.1, 1.47]  # Singapore bounds
        }
    except Exception as e:
        log.exception("Failed to generate map data")
        raise HTTPException(status_code=500, detail=f"Failed to generate map data: {e}")


__all__ = ["router"]