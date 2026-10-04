"""Normalized City Context for UrbanOS Overview.

Reusable structure consumed by:
- Overview API endpoints (city, module, chat)
- AI Service (brief generation)
- Frontend (via API responses)

Contains only information useful to both UI and AI.
Does not duplicate entire raw module datasets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from backend.app.overview.schemas import ModuleKPI, AlertItem

SG_OFFSET = timezone(timedelta(hours=8))


@dataclass
class ModuleContext:
    """Normalized module context for UI and AI."""
    id: str
    name: str
    status: str  # "normal" | "elevated" | "critical" | "unavailable"
    kpi: Optional[ModuleKPI] = None
    updated_at: Optional[str] = None
    summary: str = ""
    alerts: List[AlertItem] = field(default_factory=list)
    detail_route: str = ""


@dataclass
class CrossDomainImpact:
    """Cross-domain impact from City Coordinator."""
    type: str
    description: str
    severity: str  # "LOW" | "MODERATE" | "HIGH" | "CRITICAL"
    affected_zones: List[str] = field(default_factory=list)
    domains_involved: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)


@dataclass
class PriorityIncident:
    """Priority incident from City Coordinator."""
    id: str
    type: str
    domain: str
    severity: str
    description: str
    affected_zones: List[str] = field(default_factory=list)
    source_report: str = ""
    related_domains: List[str] = field(default_factory=list)
    cascading_risk: str = ""


@dataclass
class CityContext:
    """Normalized city-wide context for Overview and AI."""
    generated_at: str
    modules: List[ModuleContext] = field(default_factory=list)
    alerts: List[AlertItem] = field(default_factory=list)
    cross_domain_impacts: List[CrossDomainImpact] = field(default_factory=list)
    priority_incidents: List[PriorityIncident] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    affected_zones: List[str] = field(default_factory=list)

    def to_ai_context(self) -> Dict[str, Any]:
        """Compact representation for LLM prompting."""
        return {
            "generated_at": self.generated_at,
            "modules": [
                {
                    "id": m.id,
                    "name": m.name,
                    "status": m.status,
                    "kpi": {"label": m.kpi.label, "value": m.kpi.value, "unit": m.kpi.unit} if m.kpi else None,
                    "summary": m.summary,
                    "alert_count": len(m.alerts),
                }
                for m in self.modules
            ],
            "alerts": [
                {
                    "domain": a.domain,
                    "severity": a.severity,
                    "title": a.title,
                    "description": a.description,
                    "timestamp": a.timestamp,
                    "affected_zones": a.affected_zones,
                }
                for a in self.alerts[:10]  # Limit for token budget
            ],
            "cross_domain_impacts": [
                {
                    "type": c.type,
                    "description": c.description,
                    "severity": c.severity,
                    "affected_zones": c.affected_zones,
                    "domains_involved": c.domains_involved,
                }
                for c in self.cross_domain_impacts[:5]
            ],
            "priority_incidents": [
                {
                    "id": p.id,
                    "type": p.type,
                    "severity": p.severity,
                    "description": p.description,
                    "affected_zones": p.affected_zones,
                }
                for p in self.priority_incidents[:5]
            ],
            "recommendations": self.recommendations[:5],
            "affected_zones": self.affected_zones,
        }


def build_city_context(
    module_data: Dict[str, Dict[str, Any]],
    module_configs: Dict[str, Dict[str, str]],
    all_incidents: List[Dict[str, Any]],
    coordinator_report: Optional[Dict[str, Any]] = None,
) -> CityContext:
    """Build CityContext from raw module data and optional Coordinator report.

    Args:
        module_data: Raw data from each module fetcher (keyed by module_id)
        module_configs: Module name/route config
        all_incidents: Aggregated alerts from all sources
        coordinator_report: Optional CitySituationReport from City Coordinator

    Returns:
        CityContext with normalized data
    """
    modules = []
    for module_id, config in module_configs.items():
        data = module_data.get(module_id, {"error": "No data"})

        if data.get("error"):
            status = "unavailable"
            kpi = None
            summary = f"{config['name']} module: data currently unavailable."
        else:
            status = _determine_module_status(module_id, data)
            kpi = _extract_module_kpi(module_id, data)
            summary = _generate_deterministic_module_brief(module_id, data)

        updated_at = None
        if isinstance(data, dict):
            updated_at = data.get("timestamp") or data.get("snapshot_at") or data.get("generated_at")
            if updated_at is not None and hasattr(updated_at, "isoformat"):
                updated_at = updated_at.isoformat()

        # Get module-specific alerts
        module_alerts = [AlertItem(**inc) for inc in all_incidents if inc.get("domain") == module_id]

        modules.append(ModuleContext(
            id=module_id,
            name=config["name"],
            status=status,
            kpi=kpi,
            updated_at=updated_at,
            summary=summary,
            alerts=module_alerts,
            detail_route=config["detail_route"],
        ))

    # All alerts
    alerts = [AlertItem(**inc) for inc in all_incidents]

    # Cross-domain from Coordinator
    cross_domain = []
    priority_incidents = []
    recommendations = []
    affected_zones = []

    if coordinator_report:
        for imp in coordinator_report.get("cross_domain_impacts", []):
            cross_domain.append(CrossDomainImpact(**imp))
        for inc in coordinator_report.get("priority_incidents", []):
            priority_incidents.append(PriorityIncident(**inc))
        recommendations = coordinator_report.get("city_level_recommendations", [])
        affected_zones = coordinator_report.get("affected_zones", [])

    return CityContext(
        generated_at=datetime.now(SG_OFFSET).isoformat(),
        modules=modules,
        alerts=alerts,
        cross_domain_impacts=cross_domain,
        priority_incidents=priority_incidents,
        recommendations=recommendations,
        affected_zones=affected_zones,
    )


# Reuse existing logic from overview/api.py (imported to avoid duplication)
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
        if active > 500:
            return "critical"
        elif active > 100:
            return "elevated"
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
        if forecast in ("TS", "HR"):
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