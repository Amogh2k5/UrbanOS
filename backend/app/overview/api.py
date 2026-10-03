"""UrbanOS Overview API endpoints - direct service aggregation (no HTTP loopback)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Path, Query, status, Request
from pydantic import BaseModel

from backend.app.ai.service import get_ai_service, UrbanOSAIService

log = logging.getLogger(__name__)

# Singapore timezone offset (UTC+8)
SG_OFFSET = timezone(timedelta(hours=8))

router = APIRouter(prefix="/api/overview", tags=["overview"])


# ============================================================
# Response Models (matching frontend expectations)
# ============================================================

class ModuleKPI(BaseModel):
    label: str
    value: Any
    unit: str


class ModuleSummary(BaseModel):
    id: str
    name: str
    status: str  # "normal" | "elevated" | "critical" | "unavailable"
    kpi: Optional[ModuleKPI] = None
    updated_at: Optional[str] = None
    detail_route: str


class AlertItem(BaseModel):
    domain: str
    severity: str
    title: str
    description: str
    timestamp: str
    affected_zones: List[str] = []


class CityOverviewResponse(BaseModel):
    generated_at: str
    modules: List[ModuleSummary]
    alerts: List[AlertItem]
    ai_brief: Optional[str] = None


class ModuleDetailResponse(BaseModel):
    module_id: str
    module_name: str
    status: str
    kpi: Optional[ModuleKPI] = None
    updated_at: Optional[str] = None
    summary: str
    alerts: List[AlertItem] = []
    cross_domain: List[str] = []
    detail_route: str


class ChatRequest(BaseModel):
    message: str
    module_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str


# ============================================================
# Helper: AI Brief Generation
# ============================================================

async def _generate_ai_brief(ai_service: UrbanOSAIService, context: Dict[str, Any], brief_type: str = "city") -> Optional[str]:
    """Generate AI brief with timeout and fallback."""
    if not ai_service.is_available():
        return None
    try:
        if brief_type == "city":
            return await asyncio.wait_for(
                asyncio.to_thread(ai_service.generate_city_brief, context),
                timeout=10.0
            )
        else:
            return await asyncio.wait_for(
                asyncio.to_thread(ai_service.generate_module_brief, context),
                timeout=10.0
            )
    except asyncio.TimeoutError:
        log.warning("AI brief generation timed out")
        return None
    except Exception as e:
        log.warning("AI brief generation failed: %s", e)
        return None


def _generate_deterministic_city_brief(modules: List[Dict[str, Any]], alerts: List[Dict]) -> str:
    """Generate deterministic city briefing from structured data."""
    brief_parts = ["UrbanOS City Intelligence Report."]
    
    available = [m["name"] for m in modules if m.get("status") != "unavailable"]
    degraded = [m["name"] for m in modules if m.get("status") == "unavailable"]
    
    if available:
        brief_parts.append(f"Active modules: {', '.join(available)}.")
    if degraded:
        brief_parts.append(f"Degraded: {', '.join(degraded)}.")
    if alerts:
        brief_parts.append(f"{len(alerts)} priority incidents active.")
        first = alerts[0]
        if first.get("description"):
            brief_parts.append(f"Most recent: {first['description']}.")
    
    return " ".join(brief_parts)


def _generate_deterministic_module_brief(module_id: str, module_data: Dict[str, Any]) -> str:
    """Generate deterministic module brief from structured data."""
    name_map = {
        "traffic": "Traffic",
        "roads": "Roads",
        "transit": "Transit",
        "pm25": "Air Quality",
        "weather": "Weather",
        "flood": "Flood & Rain",
        "fire": "Fire",
        "crime": "Crime",
    }
    name = name_map.get(module_id, module_id.capitalize())
    
    if module_data.get("error"):
        return f"{name} module: data currently unavailable."
    
    brief = f"{name} module update. "
    
    if module_id == "traffic":
        congestion = module_data.get("overall_congestion_level")
        speed = module_data.get("overall_average_speed")
        if congestion and speed is not None:
            brief += f"Congestion: {congestion}, avg speed {speed:.1f} km/h."
        elif congestion:
            brief += f"Congestion: {congestion}."
        elif speed is not None:
            brief += f"Avg speed: {speed:.1f} km/h."
    
    elif module_id == "roads":
        if isinstance(module_data, dict) and "road_works" in module_data:
            rw = module_data["road_works"]
            brief += f"{rw.get('active', 0)} active road works, {rw.get('upcoming', 0)} upcoming."
    
    elif module_id == "transit":
        alerts = module_data.get("active_train_alerts", 0)
        if alerts:
            brief += f"{alerts} active train alerts."
    
    elif module_id == "pm25":
        # Live snapshot has regions with current readings (value), not predictions
        regions = module_data.get("regions", {})
        if regions:
            values = [v.get("value", 0) for v in regions.values() if isinstance(v, dict) and v.get("value") is not None]
            if values:
                avg = sum(values) / len(values)
                brief += f"Current avg PM2.5: {avg:.1f} µg/m³."
    
    elif module_id == "weather":
        general = module_data.get("general", {})
        temp = general.get("temperature_c")
        if temp is not None:
            brief += f"Current temp: {temp}°C."
    
    elif module_id == "flood":
        risk = module_data.get("risk_level")
        if risk:
            brief += f"Flood risk: {risk}."
    
    elif module_id == "fire":
        active = module_data.get("active_incident_count")
        if active is not None:
            brief += f"{active} active fire incidents."
    
    return brief


# ============================================================
# Direct Service Access Helpers (NO HTTP LOOPBACK)
# ============================================================

async def _fetch_traffic_overview(app_state) -> Dict[str, Any]:
    """Fetch lightweight traffic overview using shared prediction service."""
    try:
        service = app_state.traffic_prediction_service
        bundle = await asyncio.to_thread(service.get_bundle)
        
        if bundle is None or not bundle.link_preds:
            return {"error": "No traffic prediction data available"}
        
        link_preds = bundle.link_preds
        
        # Compute overall metrics
        current_speeds = [lp.current_speed for lp in link_preds if lp.current_speed is not None]
        predicted_speeds = [lp.predicted_speed for lp in link_preds if lp.predicted_speed is not None]
        
        overall_current = sum(current_speeds) / len(current_speeds) if current_speeds else None
        overall_predicted = sum(predicted_speeds) / len(predicted_speeds) if predicted_speeds else None
        
        # Determine congestion level
        speed_for_congestion = overall_predicted if overall_predicted is not None else overall_current
        if speed_for_congestion is not None:
            if speed_for_congestion >= 70:
                congestion = "free_flow"
            elif speed_for_congestion >= 50:
                congestion = "moderate"
            elif speed_for_congestion >= 30:
                congestion = "heavy"
            else:
                congestion = "severe"
        else:
            congestion = "unknown"
        
        # Count incidents using existing client
        try:
            incidents_client = app_state.traffic_incidents_client
            incidents_snap = await asyncio.to_thread(incidents_client.fetch)
            incident_count = len(incidents_snap.incidents) if incidents_snap and incidents_snap.incidents else 0
        except Exception:
            incident_count = 0
        
        return {
            "overall_average_speed": round(overall_current, 1) if overall_current else None,
            "overall_predicted_speed": round(overall_predicted, 1) if overall_predicted else None,
            "overall_congestion_level": congestion,
            "incident_count": incident_count,
            "prediction_timestamp": bundle.link_preds[0].prediction_timestamp if link_preds else None,
            "target_timestamp": bundle.link_preds[0].target_timestamp if link_preds else None,
        }
    except Exception as e:
        log.warning("Traffic overview fetch failed: %s", e)
        return {"error": str(e)}


async def _fetch_roads_overview(app_state) -> Dict[str, Any]:
    """Fetch lightweight roads overview from analytics."""
    try:
        from backend.app.mobility.roads.api import RoadWorksApiClient, RoadOpeningsApiClient, TaxiStandsApiClient, RoadDataProcessor
        
        raw_works = list(RoadWorksApiClient().fetch_all())
        raw_openings = list(RoadOpeningsApiClient().fetch_all())
        raw_stands = TaxiStandsApiClient().fetch()
        
        road_works = RoadDataProcessor.process_road_works(raw_works)
        road_openings = RoadDataProcessor.process_road_openings(raw_openings)
        taxi_stands = RoadDataProcessor.process_taxi_stands(raw_stands)
        
        active_works = [w for w in road_works if w.is_active]
        upcoming_works = [w for w in road_works if w.is_upcoming]
        completed_works = [w for w in road_works if not w.is_active and not w.is_upcoming]
        
        active_openings = [o for o in road_openings if o.is_active]
        upcoming_openings = [o for o in road_openings if o.is_upcoming]
        
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
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        log.warning("Roads overview fetch failed: %s", e)
        return {"error": str(e)}


async def _fetch_transit_overview(app_state) -> Dict[str, Any]:
    """Fetch lightweight transit overview."""
    try:
        from backend.app.mobility.transit.data import TransitDataStore
        store = TransitDataStore()
        stats = store.get_stats()
        all_alerts = store.get_latest_train_alerts(limit=60)
        train_alerts = [a for a in all_alerts if a.category in ("metro", "rail")]
        active_train_count = sum(1 for a in all_alerts if a.category in ("metro", "rail"))
        
        return {
            "bus_services_count": stats["bus_services"],
            "bus_routes_count": stats["bus_routes"],
            "bus_stops_count": stats["bus_stops"],
            "active_train_alerts": active_train_count,
            "train_alerts_count": len(train_alerts),
        }
    except Exception as e:
        log.warning("Transit overview fetch failed: %s", e)
        return {"error": str(e)}


async def _fetch_pm25_overview(app_state) -> Dict[str, Any]:
    """Fetch lightweight PM2.5 overview from live snapshot service."""
    try:
        snap = app_state.pm25_live_service.snapshot()
        if snap is None:
            return {"error": "No PM2.5 live snapshot available"}
        return snap.to_dict()
    except Exception as e:
        log.warning("PM2.5 overview fetch failed: %s", e)
        return {"error": str(e)}


async def _fetch_weather_overview(app_state) -> Dict[str, Any]:
    """Fetch lightweight weather overview from weather client. Handle 429 gracefully."""
    try:
        client = app_state.weather_client
        snap = await asyncio.to_thread(client.fetch)
        return snap.to_dict()
    except Exception as e:
        # Check if it's a 429 rate limit
        if "429" in str(e):
            log.warning("Weather API rate limited (429): %s", e)
            return {"error": "rate_limited", "message": "Weather API rate limited"}
        log.warning("Weather overview fetch failed: %s", e)
        return {"error": str(e)}


async def _fetch_flood_overview(app_state) -> Dict[str, Any]:
    """Fetch lightweight flood overview from flood client."""
    try:
        client = app_state.flood_client
        snap = await asyncio.to_thread(client.fetch)
        return snap.to_dict()
    except Exception as e:
        log.warning("Flood overview fetch failed: %s", e)
        return {"error": str(e)}


async def _fetch_fire_overview(app_state) -> Dict[str, Any]:
    """Fetch lightweight fire overview using fire agent."""
    try:
        from backend.app.safety.fire.agent import run_fire_agent
        report = await asyncio.to_thread(run_fire_agent)
        return report.model_dump()
    except Exception as e:
        log.warning("Fire overview fetch failed: %s", e)
        return {"error": str(e)}


# ============================================================
# Alert Fetching (direct service calls, NO HTTP LOOPBACK)
# ============================================================

async def _fetch_traffic_incidents() -> List[Dict]:
    """Fetch traffic incidents for alerts."""
    try:
        from backend.app.mobility.traffic.api import TrafficIncidentsApiClient
        client = TrafficIncidentsApiClient(offline=False)
        snap = await asyncio.to_thread(client.fetch)
        incidents = []
        for inc in (snap.incidents or [])[:3]:
            incidents.append({
                "domain": "traffic",
                "severity": inc.type or "UNKNOWN",
                "title": inc.type or "Traffic Incident",
                "description": inc.message,
                "timestamp": inc.timestamp,
                "affected_zones": [inc.zone_id] if inc.zone_id else [],
            })
        return incidents
    except Exception:
        return []


async def _fetch_fire_incidents() -> List[Dict]:
    """Fetch fire incidents for alerts."""
    try:
        from backend.app.safety.fire.agent import run_fire_agent
        report = await asyncio.to_thread(run_fire_agent)
        incidents = []
        for inc in (report.active_incidents or [])[:3]:
            incidents.append({
                "domain": "fire",
                "severity": inc.severity,
                "title": inc.title,
                "description": inc.summary or inc.title,
                "timestamp": inc.reported_at,
                "affected_zones": [inc.region] if inc.region else [],
            })
        return incidents
    except Exception:
        return []


async def _fetch_flood_alerts() -> List[Dict]:
    """Fetch flood alerts."""
    try:
        from backend.app.environment.flood.api import FloodAlertsApiClient
        client = FloodAlertsApiClient(offline=False)
        snap = await asyncio.to_thread(client.fetch)
        alerts = []
        for alert in (snap.alerts or [])[:2]:
            alerts.append({
                "domain": "flood",
                "severity": alert.severity,
                "title": alert.type,
                "description": alert.message,
                "timestamp": alert.issued_at,
                "affected_zones": [alert.zone_id] if alert.zone_id else [],
            })
        return alerts
    except Exception:
        return []


# ============================================================
# Main Endpoints
# ============================================================

@router.get("/city", response_model=CityOverviewResponse)
async def get_overview_city(request: Request) -> CityOverviewResponse:
    """
    Get lightweight city overview using direct service calls (NO HTTP LOOPBACK).
    """
    app_state = request.app.state
    
    # Fetch all modules concurrently with error isolation
    tasks = [
        _fetch_traffic_overview(request.app.state),
        _fetch_roads_overview(request.app.state),
        _fetch_transit_overview(request.app.state),
        _fetch_pm25_overview(request.app.state),
        _fetch_weather_overview(request.app.state),
        _fetch_flood_overview(request.app.state),
        _fetch_fire_overview(request.app.state),
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    module_data = {}
    module_ids = ["traffic", "roads", "transit", "pm25", "weather", "flood", "fire"]
    
    for module_id, result in zip(module_ids, results):
        if isinstance(result, Exception):
            log.exception("Module %s failed with exception: %s", module_id, result)
            module_data[module_id] = {"error": str(result)}
        else:
            module_data[module_id] = result
    
    # Build module summaries
    module_configs = {
        "traffic": {"name": "Traffic", "detail_route": "/traffic"},
        "roads": {"name": "Roads", "detail_route": "/roads"},
        "transit": {"name": "Transit", "detail_route": "/transit"},
        "pm25": {"name": "Air Quality", "detail_route": "/pollution"},
        "weather": {"name": "Weather", "detail_route": "/weather"},
        "flood": {"name": "Flood & Rain", "detail_route": "/flood"},
        "fire": {"name": "Fire", "detail_route": "/safety/fire"},
    }
    
    modules = []
    for module_id, config in module_configs.items():
        data = module_data.get(module_id, {"error": "No data"})
        
        if data.get("error"):
            status = "unavailable"
            kpi = None
        else:
            status = _determine_module_status(module_id, data)
            kpi = _extract_module_kpi(module_id, data)
        
        updated_at = None
        if isinstance(data, dict):
            updated_at = data.get("timestamp") or data.get("snapshot_at") or data.get("generated_at")
            if updated_at is not None and hasattr(updated_at, "isoformat"):
                updated_at = updated_at.isoformat()
        
        modules.append(ModuleSummary(
            id=module_id,
            name=config["name"],
            status=status,
            kpi=kpi,
            updated_at=updated_at,
            detail_route=config["detail_route"],
        ))
    
    # Fetch priority incidents
    incidents_tasks = [
        _fetch_traffic_incidents(),
        _fetch_fire_incidents(),
        _fetch_flood_alerts(),
    ]
    incidents_results = await asyncio.gather(*incidents_tasks, return_exceptions=True)
    all_incidents = []
    for result in incidents_results:
        if isinstance(result, list):
            all_incidents.extend(result)
    
    all_incidents.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    top_incidents = all_incidents[:5]
    
    # Generate AI brief
    ai_service = get_ai_service()
    ai_brief = None
    if ai_service.is_available():
        try:
            context = {"modules": module_data, "incidents": all_incidents}
            ai_brief = await _generate_ai_brief(ai_service, context, "city")
        except Exception as e:
            log.warning("AI city brief generation failed: %s", e)
    
    if ai_brief is None:
        module_summaries = [{"name": m.name, "status": m.status, "kpi": m.kpi.dict() if m.kpi else None} for m in modules]
        ai_brief = _generate_deterministic_city_brief(module_summaries, top_incidents)
    
    return CityOverviewResponse(
        generated_at=datetime.now(SG_OFFSET).isoformat(),
        modules=modules,
        alerts=[AlertItem(**inc) for inc in top_incidents],
        ai_brief=ai_brief,
    )


def _determine_module_status(module_id: str, data: Dict[str, Any]) -> str:
    """Determine module status from data."""
    if data.get("error"):
        return "unavailable"
    
    if module_id == "traffic":
        congestion = data.get("overall_congestion_level", "")
        if congestion in ("severe", "heavy"):
            return "critical"
        elif congestion in ("moderate",):
            return "elevated"
        elif congestion in ("free_flow",):
            return "normal"
        return "normal"
    
    elif module_id == "roads":
        active = data.get("road_works", {}).get("active", 0)
        if active > 100:
            return "elevated"
        elif active > 500:
            return "critical"
        return "normal"
    
    elif module_id == "transit":
        alerts = data.get("active_train_alerts", 0)
        if alerts > 10:
            return "elevated"
        return "normal"
    
    elif module_id == "pm25":
        regions = data.get("regions", {})
        if not regions:
            return "normal"
        high = any(isinstance(v, dict) and v.get("value", 0) > 100 for v in regions.values())
        if high:
            return "elevated"
        return "normal"
    
    elif module_id == "weather":
        if data.get("error") == "rate_limited":
            return "unavailable"
        general = data.get("general", {})
        forecast = general.get("forecast_code", "")
        if forecast in ("TS", "HR"):  # Thunderstorm, Heavy Rain
            return "elevated"
        return "normal"
    
    elif module_id == "flood":
        risk = data.get("risk_level", "").lower()
        if risk == "high":
            return "critical"
        elif risk == "moderate":
            return "elevated"
        return "normal"
    
    elif module_id == "fire":
        active = data.get("active_incident_count", 0)
        if active and active > 5:
            return "critical"
        elif active and active > 0:
            return "elevated"
        return "normal"
    
    return "normal"


def _extract_module_kpi(module_id: str, data: Dict[str, Any]) -> Optional[ModuleKPI]:
    """Extract a single meaningful KPI from module data."""
    if data.get("error"):
        return None
    
    if module_id == "traffic":
        speed = data.get("overall_average_speed")
        if speed is not None:
            return ModuleKPI(label="Average Speed", value=round(speed, 1), unit="km/h")
        congestion = data.get("overall_congestion_level")
        if congestion:
            return ModuleKPI(label="Congestion", value=congestion.replace("_", " ").title(), unit="")
    
    elif module_id == "roads":
        active = data.get("road_works", {}).get("active")
        if active is not None:
            return ModuleKPI(label="Active Road Works", value=active, unit="")
    
    elif module_id == "transit":
        alerts = data.get("active_train_alerts")
        if alerts is not None:
            return ModuleKPI(label="Train Alerts", value=alerts, unit="")
    
    elif module_id == "pm25":
        regions = data.get("regions", {})
        if regions:
            values = [v.get("value") for v in regions.values() if isinstance(v, dict) and v.get("value") is not None]
            if values:
                avg = sum(values) / len(values)
                return ModuleKPI(label="Current PM2.5", value=round(avg, 1), unit="µg/m³")
    
    elif module_id == "weather":
        general = data.get("general", {})
        temp = general.get("temperature_c")
        if temp is not None:
            return ModuleKPI(label="Temperature", value=temp, unit="°C")
    
    elif module_id == "flood":
        risk = data.get("risk_level")
        if risk:
            return ModuleKPI(label="Flood Risk", value=risk, unit="")
    
    elif module_id == "fire":
        active = data.get("active_incident_count")
        if active is not None:
            return ModuleKPI(label="Active Incidents", value=active, unit="")
    
    return None


@router.get("/module/{module_id}", response_model=ModuleDetailResponse)
async def get_overview_module(
    request: Request,
    module_id: str = Path(..., description="Module ID"),
) -> ModuleDetailResponse:
    """
    Get detailed overview for a specific module using direct service calls.
    """
    fetch_functions = {
        "traffic": _fetch_traffic_overview,
        "roads": _fetch_roads_overview,
        "transit": _fetch_transit_overview,
        "pm25": _fetch_pm25_overview,
        "weather": _fetch_weather_overview,
        "flood": _fetch_flood_overview,
        "fire": _fetch_fire_overview,
    }
    
    module_configs = {
        "traffic": {"name": "Traffic", "detail_route": "/traffic"},
        "roads": {"name": "Roads", "detail_route": "/roads"},
        "transit": {"name": "Transit", "detail_route": "/transit"},
        "pm25": {"name": "Air Quality", "detail_route": "/pollution"},
        "weather": {"name": "Weather", "detail_route": "/weather"},
        "flood": {"name": "Flood & Rain", "detail_route": "/flood"},
        "fire": {"name": "Fire", "detail_route": "/safety/fire"},
    }
    
    if module_id not in fetch_functions:
        raise HTTPException(status_code=404, detail=f"Module '{module_id}' not found")
    
    config = module_configs[module_id]
    fetch_fn = fetch_functions[module_id]
    
    try:
        data = await fetch_fn(request.app.state)
    except Exception as e:
        log.warning("Failed to fetch module %s: %s", module_id, e)
        data = {"error": str(e)}
    
    if data.get("error"):
        status = "unavailable"
        kpi = None
    else:
        status = _determine_module_status(module_id, data)
        kpi = _extract_module_kpi(module_id, data)
    
    updated_at = data.get("timestamp") or data.get("snapshot_at") or data.get("generated_at")
    
    ai_service = get_ai_service()
    ai_brief = None
    if ai_service.is_available():
        try:
            ai_brief = await _generate_ai_brief(ai_service, {"module_id": module_id, "data": data}, "module")
        except Exception as e:
            log.warning("AI module brief generation failed: %s", e)
    
    if ai_brief is None:
        ai_brief = _generate_deterministic_module_brief(module_id, data)
    
    alerts = []
    if module_id == "traffic":
        alerts = await _fetch_traffic_incidents()
    elif module_id == "fire":
        alerts = await _fetch_fire_incidents()
    elif module_id == "flood":
        alerts = await _fetch_flood_alerts()
    
    config = {
        "traffic": {"name": "Traffic", "detail_route": "/traffic"},
        "roads": {"name": "Roads", "detail_route": "/roads"},
        "transit": {"name": "Transit", "detail_route": "/transit"},
        "pm25": {"name": "Air Quality", "detail_route": "/pollution"},
        "weather": {"name": "Weather", "detail_route": "/weather"},
        "flood": {"name": "Flood & Rain", "detail_route": "/flood"},
        "fire": {"name": "Fire", "detail_route": "/safety/fire"},
    }[module_id]
    
    return ModuleDetailResponse(
        module_id=module_id,
        module_name=config["name"],
        status=status,
        kpi=kpi,
        updated_at=data.get("timestamp") or data.get("snapshot_at") or data.get("generated_at"),
        summary=ai_brief,
        alerts=[AlertItem(**a) for a in alerts[:3]],
        cross_domain=[],
        detail_route=config["detail_route"],
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, chat_request: ChatRequest) -> ChatResponse:
    """
    Chat endpoint with bounded timeout and graceful fallback.
    """
    try:
        user_message = chat_request.message.strip()
        module_id = chat_request.module_id
        
        context = {}
        if module_id:
            fetch_functions = {
                "traffic": _fetch_traffic_overview,
                "roads": _fetch_roads_overview,
                "transit": _fetch_transit_overview,
                "pm25": _fetch_pm25_overview,
                "weather": _fetch_weather_overview,
                "flood": _fetch_flood_overview,
                "fire": _fetch_fire_overview,
            }
            if module_id in fetch_functions:
                try:
                    data = await fetch_functions[module_id](request.app.state)
                    context["module_data"] = data
                    context["module_id"] = module_id
                except Exception:
                    pass
        
        ai_service = get_ai_service()
        if ai_service.is_available():
            prompt = (
                f"You are UrbanOS, a city intelligence system for Singapore. "
                f"User: \"{chat_request.message}\". "
                f"Context: {context if context else 'None'}. "
                f"Provide a concise, data-grounded response. Do not invent data. Response:"
            )
            ai_brief = await asyncio.wait_for(
                asyncio.to_thread(ai_service._generate_with_openai, prompt, 200),
                timeout=15.0
            )
            response = ai_brief or "Failed to generate response."
        else:
            if context.get("module_data"):
                response = f"UrbanOS Intelligence not configured. {module_id.capitalize()} data is available. Ask about status, alerts, or KPIs."
            else:
                response = "UrbanOS Intelligence is not configured yet."
        
        return ChatResponse(response=response)
    except asyncio.TimeoutError:
        log.warning("Chat request timed out")
        return ChatResponse(response="Request timed out. Please try again.")
    except Exception as e:
        log.exception("Error in chat endpoint: %s", e)
        return ChatResponse(response="Internal error. Please try again.")


log.info("UrbanOS Overview API router initialized (direct service mode, no HTTP loopback).")