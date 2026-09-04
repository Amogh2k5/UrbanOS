"""Flood Report V3 Pydantic models — Live Regional API + Manual Rules."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class FloodRiskLevel(str, Enum):
    """Flood risk levels for current conditions."""
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class PastFloodEvent(BaseModel):
    """Past flood event — REFERENCE ONLY, never increases current risk."""
    event_id: str
    date_start: str
    date_end: str
    location: str
    region: str
    flood_type: str
    primary_cause: str
    rainfall_mm: Optional[float] = None
    flood_depth_mm: Optional[str] = None
    damage: Optional[str] = None
    deaths: Optional[int] = None
    injuries: Optional[int] = None
    notes: Optional[str] = None
    source: Optional[str] = None
    confidence: str


class ActiveFloodAlert(BaseModel):
    """Live flood alert from official PUB API."""
    alert_id: str
    location: str
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None
    alert_type: str
    severity: str
    message: str
    issued_at: Optional[datetime] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source: str = "live_api:PUB_flood_alerts"


class SingaporeRainfallEvidence(BaseModel):
    """Current Singapore rainfall evidence from NEA 5-min API."""
    available: bool = False
    source: str = ""
    max_1h_mm: float = 0.0
    max_3h_mm: float = 0.0
    max_6h_mm: float = 0.0
    max_24h_mm: float = 0.0
    max_15m_mm: float = 0.0
    peak_5m_mm: float = 0.0
    stations_reporting: int = 0
    stations_with_rain: int = 0


class MalaysiaRainfallEvidence(BaseModel):
    """Current Malaysia/Johor rainfall evidence from MetMalaysia API."""
    available: bool = False
    source: str = ""
    max_1h_mm: float = 0.0
    stations_reporting: int = 0
    weather_systems: List[str] = Field(default_factory=list)


class SumatraRainfallEvidence(BaseModel):
    """Current Sumatra rainfall evidence from BMKG API."""
    available: bool = False
    source: str = ""
    max_1h_mm: float = 0.0
    stations_reporting: int = 0
    weather_systems: List[str] = Field(default_factory=list)
    groups: Dict[str, Any] = Field(default_factory=dict)


class RegionalWeatherStatus(BaseModel):
    """Regional weather system status from NEA 24h forecast + regional APIs."""
    singapore_forecast_code: Optional[str] = None
    singapore_forecast_text: Optional[str] = None
    singapore_wind_direction: Optional[str] = None
    singapore_temperature_high: Optional[float] = None
    singapore_temperature_low: Optional[float] = None
    malaysia_available: bool = False
    sumatra_available: bool = False
    regional_systems: List[str] = Field(default_factory=list)


class FloodReport(BaseModel):
    """Flood Report V3 — Live Regional API + Manual Rules.
    
    CURRENT conditions → CURRENT flood risk
    PAST events → REFERENCE ONLY
    """
    generated_at: datetime
    risk_level: FloodRiskLevel = FloodRiskLevel.UNKNOWN
    risk_score: float = 0.0
    active_alert_count: int = 0
    active_alerts: List[ActiveFloodAlert] = Field(default_factory=list)
    affected_zones: List[str] = Field(default_factory=list)
    primary_risk_factors: List[str] = Field(default_factory=list)
    
    # Live evidence (current conditions only)
    singapore_rainfall: Optional[SingaporeRainfallEvidence] = None
    malaysia_rainfall: Optional[MalaysiaRainfallEvidence] = None
    sumatra_rainfall: Optional[SumatraRainfallEvidence] = None
    regional_weather: Optional[RegionalWeatherStatus] = None
    
    # Reference only
    past_flood_events: List[PastFloodEvent] = Field(default_factory=list)
    
    # Provenance
    data_sources: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    limitations: List[str] = Field(default_factory=list)
    is_ml_prediction: bool = False
    errors: List[str] = Field(default_factory=list)


# Rebuild models to resolve forward references
SumatraRainfallEvidence.model_rebuild()