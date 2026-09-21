"""Flood Agent V3 — Live Regional API + Manual Rules.

Core Principle:
LIVE WEATHER OBSERVATIONS (Singapore, Malaysia/Johor, Sumatra) → CURRENT FLOOD RISK

Historical data is used OFFLINE only to derive manual risk thresholds.
Live inference uses ONLY current API observations.

Architecture:
1. Fetch live Singapore rainfall (NEA 5-min API)
2. Fetch live Malaysia/Johor rainfall (MetMalaysia API)
3. Fetch live Sumatra rainfall (BMKG API)
4. Fetch PUB flood alerts
5. Fetch NEA 24h forecast for regional weather systems
6. Apply manual risk rules (flood/config/risk_rules.py)
7. Produce FloodReport with clear provenance
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from langgraph.graph import END, StateGraph

from backend.app.environment.flood.models import (
    FloodReport, PastFloodEvent, ActiveFloodAlert,
    SingaporeRainfallEvidence, MalaysiaRainfallEvidence, SumatraRainfallEvidence,
    RegionalWeatherStatus, FloodRiskLevel
)
from backend.app.environment.flood.api import FloodAlertsApiClient, FloodAlertsSnapshot
from backend.app.mobility.traffic.geo_zones import get_all_zones
from backend.app.environment.flood.rainfall_clients import (
    RainfallApiClient, RainfallSnapshot,
    MalaysiaRainfallApiClient, MalaysiaRainfallSnapshot, get_malaysia_rainfall_evidence,
    SumatraForecastApiClient, SumatraForecastSnapshot, get_sumatra_forecast_evidence,
)
from backend.app.environment.weather.api import WeatherApiClient, WeatherLiveSnapshot
from backend.app.environment.flood.config.risk_rules import (
    RISK_THRESHOLDS, SINGAPORE_RAINFALL_RULES, REGIONAL_RULES, PUB_ALERT_RULES,
    CALIBRATION_METADATA, SINGAPORE_1H_MODERATE, SINGAPORE_1H_HEAVY, SINGAPORE_1H_EXTREME,
    SINGAPORE_3H_HEAVY, SINGAPORE_6H_HEAVY, SINGAPORE_24H_HEAVY,
    SINGAPORE_15M_MODERATE, SINGAPORE_15M_HEAVY, SINGAPORE_15M_EXTREME,
    SINGAPORE_5M_MODERATE, SINGAPORE_5M_HEAVY, SINGAPORE_5M_EXTREME,
    SINGAPORE_STATIONS_WIDESPREAD, SINGAPORE_STATIONS_EXTENSIVE,
    MALAYSIA_WEIGHT, SUMATRA_WEIGHT, SUMATRA_SQUALL_WEIGHT, MONSOON_SURGE_WEIGHT,
    PUB_ALERT_HIGH_WEIGHT, PUB_ALERT_MODERATE_WEIGHT, PUB_MULTIPLE_ALERTS_BONUS,
)

log = logging.getLogger(__name__)

# Historical flood catalogue path (for reference only)
_CATALOGUE_PATH = Path("flood/data/processed/flood_events_curated_v0.5.csv")

SG_OFFSET = timezone(timedelta(hours=8))


@dataclass
class FloodAgentState:
    """LangGraph state for Flood Agent V3."""
    # Live data
    singapore_rainfall: Optional[RainfallSnapshot] = None
    singapore_rainfall_error: Optional[str] = None
    
    malaysia_rainfall: Optional[MalaysiaRainfallSnapshot] = None
    malaysia_rainfall_error: Optional[str] = None
    
    sumatra_rainfall: Optional[SumatraForecastSnapshot] = None
    sumatra_rainfall_error: Optional[str] = None
    
    pub_alerts: List[Dict[str, Any]] = field(default_factory=list)
    pub_alerts_error: Optional[str] = None
    
    nea_weather: Optional[WeatherLiveSnapshot] = None
    nea_weather_error: Optional[str] = None
    
    # Past flood events (reference only)
    past_flood_events: List[Dict[str, Any]] = field(default_factory=list)
    
    # Analysis
    risk_level: FloodRiskLevel = FloodRiskLevel.UNKNOWN
    risk_score: float = 0.0
    primary_risk_factors: List[str] = field(default_factory=list)
    affected_zones: List[str] = field(default_factory=list)
    
    # Evidence breakdown
    singapore_evidence: Optional[Dict[str, Any]] = None
    malaysia_evidence: Optional[Dict[str, Any]] = None
    sumatra_evidence: Optional[Dict[str, Any]] = None
    regional_weather_status: Optional[Dict[str, Any]] = None
    
    # Data sources tracking
    data_sources: List[str] = field(default_factory=list)
    
    # Final report
    report: Optional[FloodReport] = None
    
    # Error tracking
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ============================================================
# NODE 1: LOAD_PAST_FLOOD_EVENTS (REFERENCE ONLY)
# ============================================================
def load_past_flood_events(state: FloodAgentState) -> FloodAgentState:
    """Load historical flood catalogue for reference only."""
    log.info("Loading past flood events (reference)...")
    
    try:
        if not _CATALOGUE_PATH.exists():
            state.warnings.append(f"Catalogue file not found: {_CATALOGUE_PATH}")
            return state
        
        df = pd.read_csv(_CATALOGUE_PATH)
        state.data_sources.append("historical_catalogue:flood_events_curated_v0.5")
        
        # Convert for reference use only
        df["date_start_dt"] = pd.to_datetime(df["date_start"], errors="coerce")
        valid_dates = df["date_start_dt"].dropna()
        
        # Store full catalogue for reference queries
        state.past_flood_events = df.to_dict("records")
        
        log.info(f"Loaded {len(df)} past flood events (reference only)")
        
    except Exception as e:
        state.errors.append(f"Failed to load past flood events: {e}")
        log.exception("Error loading past flood events")
    
    return state


# ============================================================
# NODE 2: FETCH_SINGAPORE_RAINFALL
# ============================================================
def fetch_singapore_rainfall(state: FloodAgentState) -> FloodAgentState:
    """Fetch live Singapore rainfall from NEA 5-min API."""
    log.info("Fetching live Singapore rainfall...")
    
    try:
        offline = os.getenv("URBANOS_API_OFFLINE", "0") == "1"
        client = RainfallApiClient(offline=offline)
        snapshot = client.fetch()
        
        state.singapore_rainfall = snapshot
        state.data_sources.append(f"singapore_rainfall:{snapshot.source}")
        
        if snapshot.is_live:
            log.info(f"Live Singapore rainfall: {len(snapshot.readings)} stations")
        else:
            log.info(f"Offline Singapore rainfall fixture: {len(snapshot.readings)} stations")
        
    except Exception as e:
        state.singapore_rainfall_error = f"Singapore rainfall fetch failed: {e}"
        state.errors.append(state.singapore_rainfall_error)
        log.exception("Error fetching Singapore rainfall")
    
    return state


# ============================================================
# NODE 3: FETCH_MALAYSIA_RAINFALL
# ============================================================
def fetch_malaysia_rainfall(state: FloodAgentState) -> FloodAgentState:
    """Fetch live Malaysia/Johor rainfall from MetMalaysia API."""
    log.info("Fetching live Malaysia/Johor rainfall...")
    
    try:
        offline = os.getenv("URBANOS_API_OFFLINE", "0") == "1"
        client = MalaysiaRainfallApiClient(offline=offline)
        evidence = get_malaysia_rainfall_evidence(client)
        
        state.malaysia_evidence = evidence
        state.data_sources.append(f"malaysia_rainfall:{evidence.get('source', 'unknown')}")
        
        if evidence.get("available"):
            log.info(f"Live Malaysia rainfall: {len(evidence['stations'])} stations, max_1h={evidence['max_1h_mm']:.1f}mm")
        else:
            log.info(f"Malaysia rainfall unavailable: {evidence.get('error')}")
        
    except Exception as e:
        state.malaysia_rainfall_error = f"Malaysia rainfall fetch failed: {e}"
        state.errors.append(state.malaysia_rainfall_error)
        log.exception("Error fetching Malaysia rainfall")
    
    return state


# ============================================================
# NODE 4: FETCH_SUMATRA_FORECAST
# ============================================================
def fetch_sumatra_forecast(state: FloodAgentState) -> FloodAgentState:
    """Fetch live Sumatra weather forecast from BMKG API."""
    log.info("Fetching live Sumatra weather forecast...")
    
    try:
        offline = os.getenv("URBANOS_API_OFFLINE", "0") == "1"
        client = SumatraForecastApiClient(offline=offline)
        snapshot = client.fetch()
        
        state.sumatra_rainfall = snapshot
        state.data_sources.append(f"sumatra_forecast:{snapshot.source}")
        
        if snapshot.is_live:
            total_locs = sum(g.locations_reporting for g in snapshot.groups.values())
            log.info(f"Live Sumatra forecast: {total_locs} locations reporting")
        else:
            log.info(f"Sumatra forecast unavailable: {snapshot.error}")
        
    except Exception as e:
        state.sumatra_rainfall_error = f"Sumatra forecast fetch failed: {e}"
        state.errors.append(state.sumatra_rainfall_error)
        log.exception("Error fetching Sumatra forecast")
    
    return state


# ============================================================
# NODE 5: FETCH_PUB_ALERTS
# ============================================================
def fetch_pub_alerts(state: FloodAgentState) -> FloodAgentState:
    """Fetch live PUB flood alerts."""
    log.info("Fetching live PUB flood alerts...")
    
    try:
        offline = os.getenv("URBANOS_API_OFFLINE", "0") == "1"
        # Don't silently fall back to fixture - let the adapter return unavailable state
        client = FloodAlertsApiClient(offline=offline, allow_fallback_fixture=False)
        snapshot = client.fetch()
        
        state.pub_alerts = snapshot.to_dict()["alerts"]
        state.data_sources.append(f"pub_alerts:{snapshot.source}")
        
        log.info(f"Loaded {len(state.pub_alerts)} PUB alerts (is_live={snapshot.is_live})")
        
    except Exception as e:
        state.pub_alerts_error = f"PUB alerts fetch failed: {e}"
        state.errors.append(state.pub_alerts_error)
        log.exception("Error fetching PUB alerts")
    
    return state


# ============================================================
# NODE 6: FETCH_NEA_WEATHER
# ============================================================
def fetch_nea_weather(state: FloodAgentState) -> FloodAgentState:
    """Fetch NEA 24h weather forecast for regional weather systems."""
    log.info("Fetching NEA 24h weather forecast...")
    
    try:
        offline = os.getenv("URBANOS_API_OFFLINE", "0") == "1"
        client = WeatherApiClient(offline=offline)
        snapshot = client.fetch()
        
        state.nea_weather = snapshot
        state.data_sources.append(f"nea_weather:{snapshot.source}")
        
        log.info(f"NEA weather: {snapshot.general.forecast_text}, systems={snapshot.general.forecast_code}")
        
    except Exception as e:
        state.nea_weather_error = f"NEA weather fetch failed: {e}"
        state.errors.append(state.nea_weather_error)
        log.exception("Error fetching NEA weather")
    
    return state


# ============================================================
# NODE 7: ASSESS_RISK (CORE RISK ENGINE)
# ============================================================
def assess_risk(state: FloodAgentState) -> FloodAgentState:
    """Assess flood risk using ONLY live evidence + manual rules.

    Risk scoring:
    - Singapore rainfall = PRIMARY signal (weight 1.0)
    - Malaysia/Johor rainfall = SUPPORTING (weight 0.3)
    - Sumatra rainfall = SUPPORTING (weight 0.3)
    - Regional weather systems = SUPPORTING (weight 0.3-0.4)
    - PUB alerts = CONFIRMATION (weight 0.5-1.0)
    """
    log.info("Assessing flood risk from live evidence...")
    
    try:
        risk_score = 0.0
        risk_factors: List[str] = []
        affected_zones: List[str] = []
        
        # Track evidence availability
        sg_available = state.singapore_rainfall is not None and state.singapore_rainfall.is_live
        my_available = state.malaysia_evidence and state.malaysia_evidence.get("available")
        su_available = state.sumatra_rainfall is not None and state.sumatra_rainfall.is_live
        pub_available = len(state.pub_alerts) > 0
        nea_available = state.nea_weather is not None and state.nea_weather.is_live
        
        # --- SINGAPORE RAINFALL (PRIMARY SIGNAL) ---
        sg_evidence = _analyze_singapore_rainfall(state.singapore_rainfall)
        state.singapore_evidence = sg_evidence
        
        if sg_available:
            # Apply Singapore rainfall rules using 5-min live readings
            max_5m = sg_evidence.get("peak_5m_mm", 0)
            stations_rain = sg_evidence.get("stations_with_rain", 0)
            stations_total = sg_evidence.get("stations_reporting", 0)
            
            # 5-minute intensity thresholds (direct from live API)
            if max_5m >= SINGAPORE_5M_EXTREME:
                risk_score += 0.75
                risk_factors.append(f"Extreme 5-min intensity: {max_5m:.1f}mm/5min (threshold: {SINGAPORE_5M_EXTREME}mm)")
            elif max_5m >= SINGAPORE_5M_HEAVY:
                risk_score += 0.5
                risk_factors.append(f"Heavy 5-min intensity: {max_5m:.1f}mm/5min (threshold: {SINGAPORE_5M_HEAVY}mm)")
            elif max_5m >= SINGAPORE_5M_MODERATE:
                risk_score += 0.25
                risk_factors.append(f"Moderate 5-min intensity: {max_5m:.1f}mm/5min (threshold: {SINGAPORE_5M_MODERATE}mm)")
            
            # Spatial coverage
            if stations_rain >= SINGAPORE_STATIONS_EXTENSIVE:
                risk_score += 0.2
                risk_factors.append(f"Extensive spatial coverage: {stations_rain}/{stations_total} stations with rain")
            elif stations_rain >= SINGAPORE_STATIONS_WIDESPREAD:
                risk_score += 0.1
                risk_factors.append(f"Widespread rainfall: {stations_rain}/{stations_total} stations with rain")
            
            risk_factors.append(f"Singapore: peak_5m={max_5m:.1f}mm, stations_wet={stations_rain}/{stations_total}")
        else:
            risk_factors.append("Singapore rainfall: UNAVAILABLE (offline or API error)")
        
        # --- MALAYSIA/JOHOR RAINFALL (SUPPORTING) ---
        my_evidence = state.malaysia_evidence or {}
        if my_available:
            max_1h = my_evidence.get("max_1h_mm", 0)
            if max_1h >= 50:
                risk_score += MALAYSIA_WEIGHT * 0.5
                risk_factors.append(f"Johor heavy rainfall: {max_1h:.1f}mm (weight: {MALAYSIA_WEIGHT})")
            elif max_1h >= 30:
                risk_score += MALAYSIA_WEIGHT * 0.2
                risk_factors.append(f"Johor moderate rainfall: {max_1h:.1f}mm")
        else:
            risk_factors.append(f"Malaysia/Johor rainfall: UNAVAILABLE ({my_evidence.get('error', 'no data')})")
        
        # --- SUMATRA FORECAST (SUPPORTING) ---
        su_snapshot = state.sumatra_rainfall
        if su_available:
            # Aggregate across all groups
            max_rain = 0.0
            has_rain_any = False
            for group in su_snapshot.groups.values():
                if group.has_rain:
                    has_rain_any = True
                if group.max_rainfall_mm > max_rain:
                    max_rain = group.max_rainfall_mm
            
            if max_rain >= 50:
                risk_score += SUMATRA_WEIGHT * 0.5
                risk_factors.append(f"Sumatra heavy rainfall: {max_rain:.1f}mm (weight: {SUMATRA_WEIGHT})")
            elif max_rain >= 30:
                risk_score += SUMATRA_WEIGHT * 0.2
                risk_factors.append(f"Sumatra moderate rainfall: {max_rain:.1f}mm")
            
            # Check for squall signature
            squall_groups = 0
            for group_key, group in su_snapshot.groups.items():
                if group.has_rain and group.max_rainfall_mm > 10:
                    squall_groups += 1
            
            if squall_groups >= 2:
                risk_score += SUMATRA_SQUALL_WEIGHT * 0.3
                risk_factors.append(f"Sumatra squall signature: {squall_groups} groups with rain (weight: {SUMATRA_SQUALL_WEIGHT})")
            
            risk_factors.append(f"Sumatra: max_rain={max_rain:.1f}mm, rain_groups={sum(1 for g in su_snapshot.groups.values() if g.has_rain)}")
        else:
            su_snapshot = state.sumatra_rainfall
            err_msg = getattr(su_snapshot, 'error', 'no data') if su_snapshot else 'no data'
            risk_factors.append(f"Sumatra forecast: UNAVAILABLE ({err_msg})")
        
        # --- REGIONAL WEATHER SYSTEMS (NEA 24h FORECAST) ---
        nea_evidence = _analyze_nea_weather(state.nea_weather)
        state.regional_weather_status = nea_evidence
        
        if nea_available:
            forecast_code = nea_evidence.get("forecast_code")
            wind_dir = nea_evidence.get("wind_direction")
            
            if forecast_code == "SQ":  # Sumatra Squall
                risk_score += SUMATRA_SQUALL_WEIGHT
                risk_factors.append(f"NEA forecast: Sumatra Squall (weight: {SUMATRA_SQUALL_WEIGHT})")
            elif forecast_code in ["TS", "TL", "TRW"]:  # Thunderstorms
                risk_score += 0.2
                risk_factors.append(f"NEA forecast: Thunderstorms ({forecast_code})")
            
            if wind_dir and wind_dir in ["SW", "WSW", "SSW"]:
                risk_score += 0.15
                risk_factors.append(f"SW wind direction: {wind_dir} (favors Sumatra squall approach)")
            
            # Monsoon surge detection (simplified)
            if forecast_code in ["MS", "MNS"] or "monsoon" in str(forecast_code).lower():
                risk_score += MONSOON_SURGE_WEIGHT
                risk_factors.append(f"Monsoon surge conditions (weight: {MONSOON_SURGE_WEIGHT})")
        else:
            risk_factors.append("Regional weather systems: UNAVAILABLE")
        
        # --- PUB ALERTS (CONFIRMATION) ---
        high_alerts = sum(1 for a in state.pub_alerts if a.get("severity", "").lower() == "high")
        moderate_alerts = sum(1 for a in state.pub_alerts if a.get("severity", "").lower() == "moderate")
        total_alerts = len(state.pub_alerts)
        
        if pub_available:
            for alert in state.pub_alerts:
                zone_name = alert.get("zone_name")
                if zone_name and zone_name != "unknown":
                    affected_zones.append(zone_name)
            
            if high_alerts > 0:
                risk_score += PUB_ALERT_HIGH_WEIGHT
                risk_factors.append(f"PUB HIGH alert(s): {high_alerts} (weight: {PUB_ALERT_HIGH_WEIGHT})")
            elif moderate_alerts > 0:
                risk_score += PUB_ALERT_MODERATE_WEIGHT
                risk_factors.append(f"PUB MODERATE alert(s): {moderate_alerts} (weight: {PUB_ALERT_MODERATE_WEIGHT})")
            elif total_alerts > 0:
                risk_score += PUB_ALERT_LOW_WEIGHT
                risk_factors.append(f"PUB alert(s): {total_alerts} (weight: {PUB_ALERT_LOW_WEIGHT})")
            
            if total_alerts >= 2:
                risk_score += PUB_MULTIPLE_ALERTS_BONUS * (total_alerts - 1)
                risk_factors.append(f"Multiple PUB alerts: +{PUB_MULTIPLE_ALERTS_BONUS * (total_alerts - 1):.2f} bonus")
        else:
            risk_factors.append("PUB alerts: None active")
        
        # --- MAP SCORE TO RISK LEVEL ---
        if risk_score >= RISK_THRESHOLDS["CRITICAL"]:
            risk_level = FloodRiskLevel.CRITICAL
        elif risk_score >= RISK_THRESHOLDS["HIGH"]:
            risk_level = FloodRiskLevel.HIGH
        elif risk_score >= RISK_THRESHOLDS["MODERATE"]:
            risk_level = FloodRiskLevel.MODERATE
        elif risk_score >= RISK_THRESHOLDS["LOW"]:
            risk_level = FloodRiskLevel.LOW
        else:
            risk_level = FloodRiskLevel.LOW
        
        # API unavailable handling
        if not sg_available and not my_available and not su_available and not pub_available:
            risk_level = FloodRiskLevel.UNKNOWN
            risk_factors.append("All primary data sources unavailable")
        
        state.risk_level = risk_level
        state.risk_score = min(risk_score, 2.0)  # Cap at 2.0
        state.primary_risk_factors = list(dict.fromkeys(risk_factors))  # Dedupe
        state.affected_zones = list(dict.fromkeys(affected_zones))
        
        log.info(f"Risk assessment: {risk_level.value} (score={risk_score:.2f})")
        for f in state.primary_risk_factors:
            log.debug(f"  Factor: {f}")
        
    except Exception as e:
        state.errors.append(f"Risk assessment failed: {e}")
        log.exception("Error assessing risk")
    
    return state


def _analyze_singapore_rainfall(snapshot: Optional[RainfallSnapshot]) -> Dict[str, Any]:
    """Analyze Singapore rainfall snapshot for risk evidence.
    
    NOTE: Live API provides only current 5-min readings.
    Rolling window aggregation requires historical data not available from live endpoint.
    For MVP, we use the current 5-min reading as a proxy for intensity.
    """
    if not snapshot or not snapshot.readings:
        return {
            "available": False,
            "max_1h_mm": 0.0,
            "max_3h_mm": 0.0,
            "max_6h_mm": 0.0,
            "max_24h_mm": 0.0,
            "max_15m_mm": 0.0,
            "peak_5m_mm": 0.0,
            "stations_reporting": 0,
            "stations_with_rain": 0,
        }
    
    # Current snapshot only gives instantaneous 5-min readings
    # For rolling windows, we'd need historical aggregation (not in live API)
    # Use current 5-min reading as intensity indicator only
    
    readings = list(snapshot.readings.values())
    values = [r.value_mm for r in readings]
    max_5m = max(values) if values else 0.0
    
    # Use 5-min reading directly for intensity assessment
    # Do NOT extrapolate to 1h/3h/6h/24h - those require historical data
    # Instead, use the 5-min intensity thresholds from risk_rules
    
    return {
        "available": True,
        "source": snapshot.source,
        "max_1h_mm": max_5m,        # Use 5-min reading directly (not extrapolated)
        "max_3h_mm": max_5m,        # Use 5-min reading directly
        "max_6h_mm": max_5m,
        "max_24h_mm": max_5m,
        "max_15m_mm": max_5m,
        "peak_5m_mm": max_5m,
        "stations_reporting": len(readings),
        "stations_with_rain": sum(1 for v in values if v > 0),
    }


def _analyze_nea_weather(snapshot: Optional[WeatherLiveSnapshot]) -> Dict[str, Any]:
    """Analyze NEA weather for regional system evidence."""
    if not snapshot:
        return {"available": False}
    
    return {
        "available": True,
        "source": snapshot.source,
        "forecast_code": snapshot.general.forecast_code,
        "forecast_text": snapshot.general.forecast_text,
        "wind_direction": snapshot.general.wind_direction,
        "temperature_high": snapshot.general.temperature_high_c,
        "temperature_low": snapshot.general.temperature_low_c,
    }


# ============================================================
# NODE 8: BUILD_REPORT
# ============================================================
def build_report(state: FloodAgentState) -> FloodAgentState:
    """Build the final FloodReport V3."""
    log.info("Building FloodReport V3...")
    
    try:
        # Build active alerts
        active_alerts: List[ActiveFloodAlert] = []
        for alert in state.pub_alerts:
            issued_at = _parse_timestamp_safely(alert.get("issued_at"))
            active_alerts.append(ActiveFloodAlert(
                alert_id=alert.get("alert_id", ""),
                location=alert.get("location", ""),
                zone_id=alert.get("zone_id"),
                zone_name=alert.get("zone_name"),
                alert_type=alert.get("type", "Flash Flood"),
                severity=alert.get("severity", "Moderate"),
                message=alert.get("message", ""),
                issued_at=issued_at,
                latitude=alert.get("latitude"),
                longitude=alert.get("longitude"),
                source=alert.get("source", "live_api:PUB_flood_alerts"),
            ))
        
        # Build past flood events (reference only)
        past_events: List[PastFloodEvent] = []
        for event in state.past_flood_events[:10]:  # Limit to 10 most recent for report
            flood_depth = event.get("flood_depth_mm")
            if flood_depth is not None and not isinstance(flood_depth, str):
                flood_depth = str(flood_depth)
            
            # Handle NaN deaths/injuries
            deaths = event.get("deaths")
            if deaths is not None and isinstance(deaths, float) and deaths != deaths:  # NaN check
                deaths = None
            injuries = event.get("injuries")
            if injuries is not None and isinstance(injuries, float) and injuries != injuries:  # NaN check
                injuries = None
            
            past_events.append(PastFloodEvent(
                event_id=event["event_id"],
                date_start=event["date_start"],
                date_end=event["date_end"],
                location=event["location"],
                region=event["region"],
                flood_type=event["flood_type"],
                primary_cause=event["primary_cause"],
                rainfall_mm=event.get("rainfall_mm"),
                flood_depth_mm=flood_depth,
                damage=event.get("damage"),
                deaths=deaths,
                injuries=injuries,
                notes=event.get("notes"),
                source=event.get("source"),
                confidence=event.get("confidence", "medium"),
            ))
        
        # Build Singapore rainfall evidence
        sg_evidence = None
        if state.singapore_evidence:
            se = state.singapore_evidence
            sg_evidence = SingaporeRainfallEvidence(
                available=se.get("available", False),
                source=se.get("source", ""),
                max_1h_mm=se.get("max_1h_mm", 0),
                max_3h_mm=se.get("max_3h_mm", 0),
                max_6h_mm=se.get("max_6h_mm", 0),
                max_24h_mm=se.get("max_24h_mm", 0),
                max_15m_mm=se.get("max_15m_mm", 0),
                peak_5m_mm=se.get("peak_5m_mm", 0),
                stations_reporting=se.get("stations_reporting", 0),
                stations_with_rain=se.get("stations_with_rain", 0),
            )
        
        # Build Malaysia evidence
        my_evidence = None
        if state.malaysia_evidence and state.malaysia_evidence.get("available"):
            me = state.malaysia_evidence
            my_evidence = MalaysiaRainfallEvidence(
                available=True,
                source=me.get("source", ""),
                max_1h_mm=me.get("max_1h_mm", 0),
                stations_reporting=len(me.get("stations", {})),
                weather_systems=me.get("weather_systems", []),
            )
        else:
            my_evidence = MalaysiaRainfallEvidence(
                available=False,
                source=state.malaysia_evidence.get("source", "") if state.malaysia_evidence else "unavailable",
                max_1h_mm=0.0,
                stations_reporting=0,
                weather_systems=[],
            )
        
        # Build Sumatra evidence
        su_evidence = None
        if state.sumatra_rainfall and state.sumatra_rainfall.is_live:
            su_snapshot = state.sumatra_rainfall
            su_evidence = SumatraRainfallEvidence(
                available=True,
                source=su_snapshot.source,
                max_1h_mm=max((g.max_rainfall_mm for g in su_snapshot.groups.values()), default=0.0),
                stations_reporting=sum(g.locations_reporting for g in su_snapshot.groups.values()),
                weather_systems=[],  # Will be populated from groups
            )
            # Add group-level details
            su_evidence.groups = {
                k: {
                    "group_name": v.group_name,
                    "locations_reporting": v.locations_reporting,
                    "locations_total": v.locations_total,
                    "max_rainfall_mm": v.max_rainfall_mm,
                    "has_rain": v.has_rain,
                    "representative_weather": v.representative_weather,
                    "dominant_wind_direction": v.dominant_wind_direction,
                    "avg_wind_speed_ms": v.avg_wind_speed_ms,
                    "max_cloud_cover_pct": v.max_cloud_cover_pct,
                    "latest_forecast_time": v.latest_forecast_time,
                    "locations": v.locations,
                }
                for k, v in state.sumatra_rainfall.groups.items()
            }
        else:
            su_snapshot = state.sumatra_rainfall
            su_evidence = SumatraRainfallEvidence(
                available=False,
                source=su_snapshot.source if su_snapshot else "unavailable",
                max_1h_mm=0.0,
                stations_reporting=0,
                weather_systems=[],
            )
        
        # Build regional weather status
        rws = None
        if state.regional_weather_status:
            rws_data = state.regional_weather_status
            rws = RegionalWeatherStatus(
                singapore_forecast_code=rws_data.get("forecast_code"),
                singapore_forecast_text=rws_data.get("forecast_text"),
                singapore_wind_direction=rws_data.get("wind_direction"),
                singapore_temperature_high=rws_data.get("temperature_high"),
                singapore_temperature_low=rws_data.get("temperature_low"),
                malaysia_available=state.malaysia_evidence.get("available") if state.malaysia_evidence else False,
                sumatra_available=state.sumatra_rainfall.is_live if state.sumatra_rainfall else False,
                regional_systems=state.malaysia_evidence.get("weather_systems", []) if state.malaysia_evidence else [],
            )
        
        # Generate recommendations
        recommendations = _generate_recommendations(state.risk_level, state.primary_risk_factors)
        
        # Compile limitations
        limitations = list(state.warnings)
        limitations.extend([
            "Past flood events are REFERENCE ONLY — never increase current risk",
            "Singapore rainfall extrapolation: live API provides 5-min readings; rolling windows are approximated",
            "Malaysia/Johor and Sumatra APIs may be unavailable (require credentials)",
            "Sumatra forecast from official BMKG API (27 locations, 5 regional groups)",
            "Regional weather systems from NEA 24h forecast (not live radar)",
            "PUB alerts from offline fixture in MVP (live API needs DATA_GOV_SG_API_KEY)",
            "Risk rules are operational approximations — derived from limited historical sample (37 events)",
            "No ML model used — pure rule-based inference",
        ])
        for err in state.errors:
            limitations.append(f"Error: {err}")
        
        # Determine confidence
        if state.errors:
            confidence = "low"
        elif state.singapore_evidence and state.singapore_evidence.get("available"):
            confidence = "high"
        elif state.singapore_evidence:
            confidence = "medium"
        else:
            confidence = "low"
        
        report = FloodReport(
            generated_at=datetime.now(SG_OFFSET),
            risk_level=state.risk_level,
            risk_score=state.risk_score,
            active_alert_count=len(active_alerts),
            active_alerts=active_alerts,
            affected_zones=state.affected_zones,
            primary_risk_factors=state.primary_risk_factors,
            singapore_rainfall=sg_evidence,
            malaysia_rainfall=my_evidence,
            sumatra_rainfall=su_evidence,
            regional_weather=rws,
            past_flood_events=past_events,
            data_sources=list(dict.fromkeys(state.data_sources)),
            recommendations=recommendations,
            confidence=confidence,
            limitations=limitations,
            is_ml_prediction=False,
            errors=state.errors,
        )
        
        state.report = report
        log.info(f"FloodReport V3 built: {state.risk_level.value} (score={state.risk_score:.2f})")
        
    except Exception as e:
        state.errors.append(f"Failed to build report: {e}")
        log.exception("Error building report")
    
    return state


def _generate_recommendations(risk_level: FloodRiskLevel, factors: List[str]) -> List[str]:
    """Generate recommendations based on risk level."""
    if risk_level == FloodRiskLevel.CRITICAL:
        return [
            "IMMEDIATE ACTION REQUIRED: Confirmed flooding in multiple areas",
            "Avoid ALL affected areas; seek higher ground immediately",
            "Monitor PUB Telegram and official channels continuously",
            "Do NOT drive through flooded roads — turn around",
            "Activate emergency plans if in flood-prone zone",
        ]
    elif risk_level == FloodRiskLevel.HIGH:
        return [
            "High flood risk — avoid affected areas and low-lying zones",
            "Monitor PUB Telegram and official sources for updates",
            "Do not attempt to drive through flooded roads",
            "Prepare for rapid deterioration if rainfall persists",
        ]
    elif risk_level == FloodRiskLevel.MODERATE:
        return [
            "Elevated flood risk — exercise caution in flood-prone areas",
            "Monitor weather forecasts and PUB advisories",
            "Avoid low-lying areas during heavy rain",
            "Stay informed via official channels",
        ]
    elif risk_level == FloodRiskLevel.UNKNOWN:
        return [
            "Data sources unavailable — cannot assess current flood risk",
            "Check PUB Telegram and official sources directly",
            "Exercise standard precautions in flood-prone areas",
        ]
    else:  # LOW
        return [
            "No significant flood risk detected from current observations",
            "Stay informed via PUB channels during monsoon seasons",
        ]


def _parse_timestamp_safely(ts_str: Optional[str]) -> Optional[datetime]:
    """Parse timestamp safely, returning None if invalid."""
    if not ts_str:
        return None
    try:
        s = ts_str.strip()
        if s.endswith("Z"):
            return datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc).astimezone(SG_OFFSET)
        if "+" in s[10:] or s[10:].count("-") > 0:
            return datetime.fromisoformat(s).astimezone(SG_OFFSET)
        return datetime.fromisoformat(s).replace(tzinfo=SG_OFFSET)
    except Exception:
        log.warning(f"Failed to parse timestamp: {ts_str}")
        return None


# ============================================================
# BUILD LANGGRAPH WORKFLOW
# ============================================================
def create_flood_agent_v3() -> StateGraph:
    """Create the Flood Agent V3 LangGraph workflow."""
    workflow = StateGraph(FloodAgentState)
    
    # Add nodes
    workflow.add_node("LOAD_PAST_EVENTS", load_past_flood_events)
    workflow.add_node("FETCH_SG_RAINFALL", fetch_singapore_rainfall)
    workflow.add_node("FETCH_MY_RAINFALL", fetch_malaysia_rainfall)
    workflow.add_node("FETCH_SU_FORECAST", fetch_sumatra_forecast)
    workflow.add_node("FETCH_PUB_ALERTS", fetch_pub_alerts)
    workflow.add_node("FETCH_NEA_WEATHER", fetch_nea_weather)
    workflow.add_node("ASSESS_RISK", assess_risk)
    workflow.add_node("BUILD_REPORT", build_report)
    
    # Add edges - parallel fetch then assess
    workflow.set_entry_point("LOAD_PAST_EVENTS")
    workflow.add_edge("LOAD_PAST_EVENTS", "FETCH_SG_RAINFALL")
    workflow.add_edge("FETCH_SG_RAINFALL", "FETCH_MY_RAINFALL")
    workflow.add_edge("FETCH_MY_RAINFALL", "FETCH_SU_FORECAST")
    workflow.add_edge("FETCH_SU_FORECAST", "FETCH_PUB_ALERTS")
    workflow.add_edge("FETCH_PUB_ALERTS", "FETCH_NEA_WEATHER")
    workflow.add_edge("FETCH_NEA_WEATHER", "ASSESS_RISK")
    workflow.add_edge("ASSESS_RISK", "BUILD_REPORT")
    workflow.add_edge("BUILD_REPORT", END)
    
    return workflow.compile()


# Global compiled graph
_flood_agent_v3_graph = None


def get_flood_agent_v3():
    """Get or create the compiled Flood Agent V3 graph."""
    global _flood_agent_v3_graph
    if _flood_agent_v3_graph is None:
        _flood_agent_v3_graph = create_flood_agent_v3()
    return _flood_agent_v3_graph


def run_flood_agent_v3(offline: bool = True) -> FloodReport:
    """Run the Flood Agent V3 and return a FloodReport."""
    prev_offline = os.getenv("FLOOD_AGENT_OFFLINE")
    os.environ["FLOOD_AGENT_OFFLINE"] = "true" if offline else "false"
    
    try:
        graph = get_flood_agent_v3()
        initial_state = FloodAgentState()
        result = graph.invoke(initial_state)
        
        if result.get("report") is None:
            raise RuntimeError("Flood Agent V3 failed: " + "; ".join(result.get("errors", ["Unknown error"])))
        
        return result["report"]
    finally:
        if prev_offline is not None:
            os.environ["FLOOD_AGENT_OFFLINE"] = prev_offline
        else:
            os.environ.pop("FLOOD_AGENT_OFFLINE", None)