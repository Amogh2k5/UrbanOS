"""City Coordinator Agent - LangGraph workflow for orchestrating domain agents."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from langgraph.graph import END, StateGraph

# Domain report imports
from backend.app.environment.result import EnvironmentReport
from backend.app.mobility.traffic.data import TrafficReport
from backend.app.environment.flood.models import FloodReport

# Coordinator report imports
from coordinator.city_report import (
    CitySituationReport,
    DomainStatus,
    CrossDomainImpact,
    PriorityIncident,
)

# Domain agent runners
from backend.app.environment.environment_module import EnvironmentModule
from backend.app.mobility.traffic.agent import run_traffic_agent
from backend.app.environment.flood.agent import run_flood_agent_v3
from backend.app.environment.flood.models import FloodRiskLevel

log = logging.getLogger(__name__)


@dataclass
class CityCoordinatorState:
    """LangGraph state for City Coordinator."""
    # Domain reports
    environment_report: Optional[EnvironmentReport] = None
    traffic_report: Optional[TrafficReport] = None
    flood_report: Optional[FloodReport] = None
    
    # Normalized domain status
    domain_status: Dict[str, Any] = field(default_factory=dict)
    
    # Cross-domain analysis
    cross_domain_impacts: List[Dict[str, Any]] = field(default_factory=list)
    priority_incidents: List[Dict[str, Any]] = field(default_factory=list)
    
    # Final outputs
    overall_city_status: str = "UNKNOWN"
    overall_risk_level: str = "UNKNOWN"
    city_level_recommendations: List[str] = field(default_factory=list)
    affected_zones: List[str] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    confidence: str = "medium"
    limitations: List[str] = field(default_factory=list)
    
    # Source reports for provenance
    source_reports: Dict[str, Any] = field(default_factory=dict)
    
    # Error tracking
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # Final report
    report: Optional[Any] = None


# ============================================================
# NODE 1: COLLECT_REPORTS
# ============================================================
def collect_reports(state: CityCoordinatorState) -> CityCoordinatorState:
    """Collect reports from all three domain agents."""
    log.info("Collecting domain reports...")
    
    # Environment Report
    try:
        log.info("Running Environment Agent...")
        env_module = EnvironmentModule()
        env_report = env_module.run()
        state.environment_report = env_report
        state.source_reports["environment"] = env_report.to_dict()
        log.info("Environment Report collected successfully")
    except Exception as e:
        log.exception("Environment Agent failed")
        state.errors.append(f"Environment Agent: {str(e)}")
        state.warnings.append("Environment report unavailable")
    
    # Traffic Report
    try:
        log.info("Running Traffic Agent...")
        traffic_report = run_traffic_agent(offline=False)
        state.traffic_report = traffic_report
        state.source_reports["traffic"] = traffic_report.model_dump()
        log.info("Traffic Report collected successfully")
    except Exception as e:
        log.exception("Traffic Agent failed")
        state.errors.append(f"Traffic Agent: {str(e)}")
        state.warnings.append("Traffic report unavailable")
    
    # Flood Report
    try:
        log.info("Running Flood Agent V3...")
        flood_report = run_flood_agent_v3(offline=True)
        state.flood_report = flood_report
        state.source_reports["flood"] = flood_report.model_dump()
        log.info("Flood Report V3 collected successfully")
    except Exception as e:
        log.exception("Flood Agent V3 failed")
        state.errors.append(f"Flood Agent V3: {str(e)}")
        state.warnings.append("Flood report unavailable")
    
    return state


# ============================================================
# NODE 2: NORMALIZE_STATE
# ============================================================
def normalize_state(state: CityCoordinatorState) -> CityCoordinatorState:
    """Normalize domain reports into unified domain_status structure."""
    log.info("Normalizing domain reports...")
    
    domain_status = {}
    
    # Environment
    if state.environment_report:
        er = state.environment_report
        # Determine overall status from PM2.5 predictions
        max_pm25 = 0
        ml_regions = 0
        for r in er.regions:
            if r.pm25_next_day_max:
                max_pm25 = max(max_pm25, r.pm25_next_day_max)
            if r.is_ml_model:
                ml_regions += 1
        
        if max_pm25 >= 55:  # Unhealthy per NEA
            env_status = "DISRUPTED"
            env_risk = "HIGH"
        elif max_pm25 >= 35:  # Moderate
            env_status = "ELEVATED"
            env_risk = "MODERATE"
        else:
            env_status = "NORMAL"
            env_risk = "LOW"
        
        domain_status["environment"] = {
            "domain": "environment",
            "available": True,
            "overall_status": env_status,
            "overall_risk": env_risk,
            "risk_level": env_risk,
            "key_metrics": {
                "max_pm25_next_day_max": max_pm25,
                "ml_regions": ml_regions,
                "total_regions": len(er.regions),
                "weather_forecast_available": er.weather_forecast is not None,
            },
            "active_alert_count": 0,
            "affected_zones": [],
            "primary_risk_factors": er.data_quality_flags,
            "confidence": "high" if ml_regions > 0 else "medium",
            "limitations": er.data_quality_flags,
            "is_ml_prediction": ml_regions > 0,
            "generated_at": er.generated_at.isoformat() if er.generated_at else None,
        }
    else:
        domain_status["environment"] = {
            "domain": "environment",
            "available": False,
            "error": "Environment report not available",
        }
    
    # Traffic
    if state.traffic_report:
        tr = state.traffic_report
        domain_status["traffic"] = {
            "domain": "traffic",
            "available": True,
            "overall_status": tr.overall_status,
            "overall_risk": "HIGH" if tr.overall_status == "disrupted" else ("MODERATE" if tr.overall_status == "elevated" else "LOW"),
            "risk_level": "HIGH" if tr.overall_status == "disrupted" else ("MODERATE" if tr.overall_status == "elevated" else "LOW"),
            "key_metrics": {
                "overall_average_speed": tr.overall_average_speed,
                "overall_predicted_speed": tr.overall_predicted_speed,
                "overall_congestion_level": tr.overall_congestion_level,
                "total_incidents": len(tr.incidents),
                "total_zones": len(tr.zones),
            },
            "active_alert_count": len(tr.incidents),
            "affected_zones": [i.zone_name for i in tr.incidents if i.zone_name],
            "primary_risk_factors": [z.congestion_level for z in tr.zones if z.congestion_level in ["heavy", "severe"]],
            "confidence": "medium",
            "limitations": tr.limitations,
            "is_ml_prediction": any(z.is_demo_zone for z in tr.zones),
            "generated_at": tr.generated_at.isoformat() if tr.generated_at else None,
        }
    else:
        domain_status["traffic"] = {
            "domain": "traffic",
            "available": False,
            "error": "Traffic report not available",
        }
    
    # Flood
    if state.flood_report:
        fr = state.flood_report
        # NEW FloodReport V3 uses risk_level (FloodRiskLevel enum) and risk_score
        # Map enum to string for compatibility
        flood_risk_str = fr.risk_level.value if isinstance(fr.risk_level, FloodRiskLevel) else str(fr.risk_level)
        
        domain_status["flood"] = {
            "domain": "flood",
            "available": True,
            "overall_status": "CRITICAL" if flood_risk_str == "CRITICAL" else ("ELEVATED" if flood_risk_str in ["HIGH", "MODERATE"] else "NORMAL"),
            "overall_risk": flood_risk_str,
            "risk_level": flood_risk_str,
            "key_metrics": {
                "active_alert_count": fr.active_alert_count,
                "historical_context_count": len(fr.past_flood_events),
                "risk_score": fr.risk_score,
            },
            "active_alert_count": fr.active_alert_count,
            "affected_zones": fr.affected_zones,
            "primary_risk_factors": fr.primary_risk_factors,
            "confidence": fr.confidence,
            "limitations": fr.limitations,
            "is_ml_prediction": fr.is_ml_prediction,
            "generated_at": fr.generated_at.isoformat() if fr.generated_at else None,
        }
    else:
        domain_status["flood"] = {
            "domain": "flood",
            "available": False,
            "error": "Flood report not available",
        }
    
    state.domain_status = domain_status
    
    # Collect all affected zones
    all_zones = set()
    for domain_name, status in domain_status.items():
        if status.get("affected_zones"):
            all_zones.update(status["affected_zones"])
    state.affected_zones = list(all_zones)
    
    return state


# ============================================================
# NODE 3: ANALYZE_CROSS_DOMAIN_IMPACTS
# ============================================================
def analyze_cross_domain_impacts(state: CityCoordinatorState) -> CityCoordinatorState:
    """Detect cross-domain relationships and impacts."""
    log.info("Analyzing cross-domain impacts...")
    
    impacts = []
    priority_incidents = []
    incident_id = 0
    
    ds = state.domain_status
    env = ds.get("environment", {})
    traffic = ds.get("traffic", {})
    flood = ds.get("flood", {})
    
    # 1. Flood + Traffic congestion
    if flood.get("available") and traffic.get("available"):
        flood_risk = flood.get("overall_risk", "LOW")
        traffic_status = traffic.get("overall_status", "unknown")
        
        if flood_risk in ["HIGH", "MODERATE"] and traffic_status in ["disrupted", "elevated"]:
            # Find overlapping zones
            flood_zones = set(flood.get("affected_zones", []))
            traffic_incident_zones = set(traffic.get("affected_zones", []))
            overlap = flood_zones & traffic_incident_zones
            
            severity = "HIGH" if flood_risk == "HIGH" else "MODERATE"
            impacts.append({
                "type": "flood_traffic",
                "description": f"Flood risk ({flood_risk}) overlaps with traffic disruption in affected zones",
                "severity": severity,
                "affected_zones": list(overlap) if overlap else list(flood_zones | traffic_incident_zones),
                "domains_involved": ["flood", "traffic"],
                "evidence": [
                    f"Flood risk: {flood_risk} ({flood.get('active_alert_count', 0)} active alerts)",
                    f"Traffic status: {traffic_status} ({traffic.get('key_metrics', {}).get('total_incidents', 0)} incidents)",
                ],
            })
            
            if overlap:
                incident_id += 1
                priority_incidents.append({
                    "id": f"INC_{incident_id:03d}",
                    "type": "flood_traffic_overlap",
                    "domain": "flood_traffic",
                    "severity": severity,
                    "description": f"Flood alerts and traffic incidents both affecting {', '.join(overlap)}",
                    "affected_zones": list(overlap),
                    "source_report": "flood + traffic",
                    "related_domains": ["flood", "traffic"],
                    "cascading_risk": "Road diversions and evacuation route disruption possible",
                })
    
    # 2. Weather (from Environment) + Flood risk
    if env.get("available") and flood.get("available"):
        weather_available = env.get("key_metrics", {}).get("weather_forecast_available", False)
        flood_risk = flood.get("overall_risk", "LOW")
        
        if weather_available and flood_risk in ["HIGH", "MODERATE"]:
            weather_forecast = None
            if state.environment_report and state.environment_report.weather_forecast:
                wf = state.environment_report.weather_forecast
                weather_forecast = wf.national_forecast_text or wf.national_forecast_code
            
            impacts.append({
                "type": "weather_flood",
                "description": f"Weather forecast available with active flood risk ({flood_risk})",
                "severity": "HIGH" if flood_risk == "HIGH" else "MODERATE",
                "affected_zones": flood.get("affected_zones", []),
                "domains_involved": ["environment", "flood"],
                "evidence": [
                    f"Weather forecast: {weather_forecast or 'Available'}",
                    f"Flood risk: {flood_risk} with {flood.get('active_alert_count', 0)} active alerts",
                ],
            })
    
    # 3. Poor air quality (Environment) + Weather conditions
    if env.get("available"):
        max_pm25 = env.get("key_metrics", {}).get("max_pm25_next_day_max", 0)
        weather_available = env.get("key_metrics", {}).get("weather_forecast_available", False)
        
        if max_pm25 >= 55 and weather_available:  # Unhealthy PM2.5
            impacts.append({
                "type": "air_quality_weather",
                "description": f"Elevated PM2.5 ({max_pm25:.1f} µg/m³) with weather conditions that may affect dispersion",
                "severity": "HIGH" if max_pm25 >= 100 else "MODERATE",
                "affected_zones": [],
                "domains_involved": ["environment"],
                "evidence": [
                    f"Max predicted PM2.5: {max_pm25:.1f} µg/m³ (next-day max)",
                    "Weather forecast available for dispersion analysis",
                ],
            })
    
    # 4. Multiple simultaneous HIGH risks (3 or more domains)
    high_risks = []
    for domain_name, status in ds.items():
        if status.get("overall_risk") == "HIGH" or status.get("risk_level") == "HIGH":
            high_risks.append(domain_name)
    
    # Only escalate to CRITICAL if 3+ domains at HIGH risk
    # For 2 domains, the cross-domain impacts already capture the relationship
    if len(high_risks) >= 3:
        impacts.append({
            "type": "multi_domain_high_risk",
            "description": f"Multiple domains at HIGH risk simultaneously: {', '.join(high_risks)}",
            "severity": "CRITICAL",
            "affected_zones": state.affected_zones,
            "domains_involved": high_risks,
            "evidence": [f"{d}: {ds[d].get('overall_risk', 'HIGH')} risk" for d in high_risks],
        })
    elif len(high_risks) == 2:
        # For 2 domains, add a HIGH severity multi-domain impact
        impacts.append({
            "type": "multi_domain_high_risk",
            "description": f"Multiple domains at HIGH risk simultaneously: {', '.join(high_risks)}",
            "severity": "HIGH",
            "affected_zones": state.affected_zones,
            "domains_involved": high_risks,
            "evidence": [f"{d}: {ds[d].get('overall_risk', 'HIGH')} risk" for d in high_risks],
        })
    
    # Sort impacts by severity (highest first)
    severity_order = {"CRITICAL": 4, "HIGH": 3, "MODERATE": 2, "LOW": 1, "UNKNOWN": 0}
    impacts.sort(key=lambda x: severity_order.get(x.get("severity", "UNKNOWN"), 0), reverse=True)
    
    state.cross_domain_impacts = impacts
    state.priority_incidents = priority_incidents
    
    return state


# ============================================================
# NODE 4: PRIORITIZE_RISKS
# ============================================================
def prioritize_risks(state: CityCoordinatorState) -> CityCoordinatorState:
    """Prioritize risks and determine overall city status."""
    log.info("Prioritizing risks...")
    
    # Collect all incidents and impacts for prioritization
    all_items = []
    
    # Add priority incidents
    for inc in state.priority_incidents:
        all_items.append({
            "type": "incident",
            "severity": inc["severity"],
            "description": inc["description"],
        })
    
    # Add cross-domain impacts
    for imp in state.cross_domain_impacts:
        all_items.append({
            "type": "impact",
            "severity": imp["severity"],
            "description": imp["description"],
        })
    
    # Add domain-level high risks
    for domain_name, status in state.domain_status.items():
        if status.get("overall_risk") in ["HIGH", "CRITICAL"]:
            all_items.append({
                "type": "domain_risk",
                "severity": status.get("overall_risk", "HIGH"),
                "description": f"{domain_name} domain at {status.get('overall_risk')} risk",
            })
    
    # Determine overall city status based on highest severity
    severity_order = {"CRITICAL": 4, "HIGH": 3, "MODERATE": 2, "LOW": 1, "UNKNOWN": 0}
    max_severity = "UNKNOWN"
    
    for item in all_items:
        sev = item.get("severity", "UNKNOWN")
        if severity_order.get(sev, 0) > severity_order.get(max_severity, 0):
            max_severity = sev
    
    # Map to city status
    status_map = {
        "CRITICAL": "CRITICAL",
        "HIGH": "DISRUPTED",
        "MODERATE": "ELEVATED",
        "LOW": "NORMAL",
        "UNKNOWN": "UNKNOWN",
    }
    
    # If max_severity is UNKNOWN but we have domain risks, check for LOW risks
    if max_severity == "UNKNOWN":
        # Check if any domain has LOW risk
        has_low_risk = any(
            s.get("overall_risk") == "LOW" or s.get("risk_level") == "LOW"
            for s in state.domain_status.values()
        )
        if has_low_risk:
            max_severity = "LOW"
    
    state.overall_city_status = status_map.get(max_severity, "UNKNOWN")
    state.overall_risk_level = max_severity
    
    # Confidence based on data availability
    available_domains = sum(1 for s in state.domain_status.values() if s.get("available", True))
    if available_domains == 3:
        state.confidence = "high"
    elif available_domains == 2:
        state.confidence = "medium"
    else:
        state.confidence = "low"
    
    # Add errors to limitations
    state.limitations.extend(state.errors)
    state.limitations.extend(state.warnings)
    
    # Add standard limitations
    state.limitations.extend([
        "City Coordinator uses rule-based reasoning; not an ML predictor for cross-domain prediction",
        "Domain reports use offline fixtures for live data in MVP",
        "Zone mapping precision limited by available geographic data",
        "Cross-domain relationships based on spatial/temporal overlap heuristics",
    ])
    
    return state


# ============================================================
# NODE 5: GENERATE_RECOMMENDATIONS
# ============================================================
def generate_recommendations(state: CityCoordinatorState) -> CityCoordinatorState:
    """Generate city-level recommendations based on prioritized risks."""
    log.info("Generating recommendations...")
    
    recommendations = []
    
    ds = state.domain_status
    env = ds.get("environment", {})
    traffic = ds.get("traffic", {})
    flood = ds.get("flood", {})
    
    # Flood + Traffic overlap
    flood_traffic_impacts = [i for i in state.cross_domain_impacts if i["type"] == "flood_traffic"]
    if flood_traffic_impacts:
        affected = set()
        for imp in flood_traffic_impacts:
            affected.update(imp.get("affected_zones", []))
        if affected:
            recommendations.append(
                f"FLOOD+TRAFFIC: Monitor/avoid affected roads in {', '.join(sorted(affected))}. "
                f"Evaluate alternate routes for evacuation and emergency access. "
                f"Coordinate with LTA for traffic diversions around flooded areas."
            )
        else:
            recommendations.append(
                "FLOOD+TRAFFIC: Flood alerts and traffic disruption in different zones. "
                "Monitor for convergence. Pre-position traffic management resources near flood-prone areas."
            )
    
    # Weather + Flood
    weather_flood_impacts = [i for i in state.cross_domain_impacts if i["type"] == "weather_flood"]
    if weather_flood_impacts:
        recommendations.append(
            "WEATHER+FLOOD: Active flood risk with weather forecast available. "
            "Monitor NEA 24h forecast for rainfall intensity updates. "
            "Issue public advisory for flood-prone areas per PUB guidelines."
        )
    
    # Air Quality + Weather
    air_quality_impacts = [i for i in state.cross_domain_impacts if i["type"] == "air_quality_weather"]
    if air_quality_impacts:
        recommendations.append(
            "AIR QUALITY: Elevated PM2.5 predicted. "
            "Advise sensitive groups to limit outdoor activities. "
            "Monitor NEA PM2.5 readings and weather dispersion conditions."
        )
    
    # Multi-domain HIGH risk
    multi_high = [i for i in state.cross_domain_impacts if i["type"] == "multi_domain_high_risk"]
    if multi_high:
        domains = multi_high[0].get("domains_involved", [])
        recommendations.append(
            f"MULTI-DOMAIN CRITICAL: Simultaneous HIGH risk in {', '.join(domains)}. "
            "Activate cross-agency coordination (NEA, PUB, LTA). "
            "Issue unified public advisory. Prioritize resources to most affected zones."
        )
    
    # Single domain recommendations
    if flood.get("overall_risk") == "HIGH":
        recommendations.append(
            "FLOOD: HIGH risk with active alerts. "
            "Public to avoid affected zones. Monitor PUB Telegram and official channels. "
            "Do not drive through flooded roads."
        )
    elif flood.get("overall_risk") == "MODERATE":
        recommendations.append(
            "FLOOD: MODERATE risk. Exercise caution in historically flood-prone areas. "
            "Monitor weather forecasts and PUB advisories."
        )
    
    if traffic.get("overall_status") == "disrupted":
        recommendations.append(
            "TRAFFIC: Disrupted conditions with active incidents. "
            "Use alternate routes. Check LTA traffic news for real-time updates."
        )
    elif traffic.get("overall_status") == "elevated":
        recommendations.append(
            "TRAFFIC: Elevated congestion. Plan for longer journey times. "
            "Check traffic incidents before departure."
        )
    
    if env.get("key_metrics", {}).get("max_pm25_next_day_max", 0) >= 55:
        recommendations.append(
            "ENVIRONMENT: Unhealthy PM2.5 levels predicted. "
            "Sensitive groups should limit prolonged outdoor exertion. "
            "Monitor NEA air quality readings."
        )
    
    # Default if no specific recommendations
    if not recommendations:
        recommendations.append(
            "No immediate cross-domain risks detected. "
            "Continue routine monitoring via domain dashboards."
        )
    
    state.city_level_recommendations = recommendations
    
    # Build evidence
    state.evidence = [
        {"source": "environment", "ref": state.source_reports.get("environment", {}).get("provenance", {}), "kind": "environment_report"},
        {"source": "traffic", "ref": state.source_reports.get("traffic", {}).get("limitations", []), "kind": "traffic_report"},
        {"source": "flood", "ref": state.source_reports.get("flood", {}).get("limitations", []), "kind": "flood_report"},
    ]
    
    return state


# ============================================================
# NODE 6: BUILD_REPORT
# ============================================================
def build_report(state: CityCoordinatorState) -> CityCoordinatorState:
    """Build the final CitySituationReport."""
    from coordinator.city_report import CitySituationReport, DomainStatus
    log.info("Building City Situation Report...")
    
    try:
        # Convert domain_status to DomainStatus objects
        domain_status_objs = {}
        for domain_name, status in state.domain_status.items():
            domain_status_objs[domain_name] = DomainStatus(
                domain=domain_name,
                available=status.get("available", False),
                overall_status=status.get("overall_status"),
                overall_risk=status.get("overall_risk"),
                risk_level=status.get("risk_level"),
                key_metrics=status.get("key_metrics", {}),
                active_alert_count=status.get("active_alert_count"),
                affected_zones=status.get("affected_zones", []),
                primary_risk_factors=status.get("primary_risk_factors", []),
                confidence=status.get("confidence"),
                limitations=status.get("limitations", []),
                is_ml_prediction=status.get("is_ml_prediction"),
                generated_at=status.get("generated_at"),
                error=status.get("error"),
            )
        
        # Convert cross_domain_impacts
        cross_domain_impacts = []
        for imp in state.cross_domain_impacts:
            cross_domain_impacts.append(CrossDomainImpact(**imp))
        
        # Convert priority_incidents
        priority_incidents = []
        for inc in state.priority_incidents:
            priority_incidents.append(PriorityIncident(**inc))
        
        # Build report using the model
        from coordinator.city_report import CitySituationReport, DomainStatus
        
        report = CitySituationReport(
            generated_at=datetime.now(),
            overall_city_status=state.overall_city_status,
            overall_risk_level=state.overall_risk_level,
            domain_status=domain_status_objs,
            priority_incidents=priority_incidents,
            cross_domain_impacts=cross_domain_impacts,
            city_level_recommendations=state.city_level_recommendations,
            affected_zones=state.affected_zones,
            evidence=state.evidence,
            confidence=state.confidence,
            limitations=state.limitations,
            source_reports=state.source_reports,
            is_ml_prediction=False,
        )
        
        state.report = report
        log.info("City Situation Report built successfully")
        
    except Exception as e:
        log.exception("Error building report")
        state.errors.append(f"Build report failed: {str(e)}")
    
    return state


# Import models for build_report
from coordinator.city_report import CitySituationReport, DomainStatus, CrossDomainImpact, PriorityIncident


# ============================================================
# BUILD LANGGRAPH WORKFLOW
# ============================================================
def create_city_coordinator() -> StateGraph:
    """Create the City Coordinator LangGraph workflow."""
    
    workflow = StateGraph(CityCoordinatorState)
    
    # Add nodes
    workflow.add_node("COLLECT_REPORTS", collect_reports)
    workflow.add_node("NORMALIZE_STATE", normalize_state)
    workflow.add_node("ANALYZE_CROSS_DOMAIN_IMPACTS", analyze_cross_domain_impacts)
    workflow.add_node("PRIORITIZE_RISKS", prioritize_risks)
    workflow.add_node("GENERATE_RECOMMENDATIONS", generate_recommendations)
    workflow.add_node("BUILD_REPORT", build_report)
    
    # Add edges
    workflow.set_entry_point("COLLECT_REPORTS")
    workflow.add_edge("COLLECT_REPORTS", "NORMALIZE_STATE")
    workflow.add_edge("NORMALIZE_STATE", "ANALYZE_CROSS_DOMAIN_IMPACTS")
    workflow.add_edge("ANALYZE_CROSS_DOMAIN_IMPACTS", "PRIORITIZE_RISKS")
    workflow.add_edge("PRIORITIZE_RISKS", "GENERATE_RECOMMENDATIONS")
    workflow.add_edge("GENERATE_RECOMMENDATIONS", "BUILD_REPORT")
    workflow.add_edge("BUILD_REPORT", END)
    
    return workflow.compile()


# Global compiled graph
_city_coordinator_graph = None


def get_city_coordinator():
    """Get or create the compiled City Coordinator graph."""
    global _city_coordinator_graph
    if _city_coordinator_graph is None:
        _city_coordinator_graph = create_city_coordinator()
    return _city_coordinator_graph


def run_city_coordinator() -> CitySituationReport:
    """Run the City Coordinator and return a CitySituationReport."""
    graph = get_city_coordinator()
    initial_state = CityCoordinatorState()
    result = graph.invoke(initial_state)
    
    if result.get("report") is None:
        raise RuntimeError("City Coordinator failed to produce report: " + "; ".join(result.get("errors", ["Unknown error"])))
    
    return result["report"]