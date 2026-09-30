"""Fire/Safety domain models.

The Fire domain deliberately distinguishes verified incident data from unavailable
live feeds. It never treats an unavailable source as zero incidents.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

FireStatus = Literal["ACTIVE", "RESOLVED", "UNKNOWN"]
FireSeverity = Literal["CRITICAL", "HIGH", "MODERATE", "LOW", "UNKNOWN"]


class FireIncident(BaseModel):
    id: str
    title: str
    source: str
    source_url: Optional[str] = None
    reported_at: Optional[datetime] = None
    location: Optional[str] = None
    incident_type: Optional[str] = None
    severity: FireSeverity = "UNKNOWN"
    status: FireStatus = "UNKNOWN"
    affected_area: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    region: Optional[str] = None
    summary: Optional[str] = None
    data_quality_flags: List[str] = Field(default_factory=list)


class FireHistoryPoint(BaseModel):
    year: int
    fires: Optional[int] = None
    source: str


class FireReport(BaseModel):
    generated_at: datetime
    domain: str = "safety"
    subdomain: str = "fire"

    # Current published-incident intelligence.
    active_incidents: List[FireIncident] = Field(default_factory=list)
    recent_incidents: List[FireIncident] = Field(default_factory=list)

    # KPI values are nullable: null means the source cannot establish the value.
    active_incident_count: Optional[int] = None
    critical_incident_count: Optional[int] = None
    incidents_today: Optional[int] = None
    resolved_recent_count: Optional[int] = None

    regional_counts: Dict[str, Optional[int]] = Field(default_factory=dict)
    historical_fire_counts: List[FireHistoryPoint] = Field(default_factory=list)

    source_status: str = "unavailable"
    data_sources: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    is_ml_prediction: bool = False

    def model_dump_json_safe(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")
