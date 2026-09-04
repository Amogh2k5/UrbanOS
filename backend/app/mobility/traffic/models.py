"""Traffic Report Pydantic models."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class ZoneReport(BaseModel):
    """Zone-level traffic summary."""
    zone_id: str
    zone_name: str
    is_demo_zone: bool = True
    current_average_speed: Optional[float] = None
    predicted_average_speed: Optional[float] = None
    speed_change: Optional[float] = None
    speed_change_percent: Optional[float] = None
    congestion_level: Literal["free_flow", "moderate", "heavy", "severe", "unknown"] = "unknown"
    segment_count: int = 0
    incident_count: int = 0


class IncidentReport(BaseModel):
    """Live traffic incident."""
    type: str
    message: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None


class TrafficReport(BaseModel):
    """Structured traffic report combining ML predictions and live incidents."""
    generated_at: datetime
    prediction_horizon_minutes: int = 10
    overall_status: Literal["normal", "elevated", "disrupted", "unknown"] = "unknown"
    overall_average_speed: Optional[float] = None
    overall_predicted_speed: Optional[float] = None
    overall_speed_change_percent: Optional[float] = None
    overall_congestion_level: Literal["free_flow", "moderate", "heavy", "severe", "unknown"] = "unknown"
    zones: List[ZoneReport] = Field(default_factory=list)
    incidents: List[IncidentReport] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)