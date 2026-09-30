"""City Coordinator Report Pydantic models."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field


class DomainStatus(BaseModel):
    """Status summary for a single domain."""
    domain: str
    available: bool
    overall_status: Optional[str] = None
    overall_risk: Optional[str] = None
    risk_level: Optional[str] = None
    key_metrics: Dict[str, Any] = Field(default_factory=dict)
    active_alert_count: Optional[int] = None
    affected_zones: List[str] = Field(default_factory=list)
    primary_risk_factors: List[str] = Field(default_factory=list)
    confidence: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)
    is_ml_prediction: Optional[bool] = None
    generated_at: Optional[datetime] = None
    error: Optional[str] = None


class CrossDomainImpact(BaseModel):
    """Identified cross-domain relationship."""
    type: str  # e.g., "flood_traffic", "weather_flood", "air_quality_weather"
    description: str
    severity: Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]
    affected_zones: List[str] = Field(default_factory=list)
    domains_involved: List[str]
    evidence: List[str] = Field(default_factory=list)


class PriorityIncident(BaseModel):
    """Prioritized city-level incident."""
    id: str
    type: str
    domain: str
    severity: Literal["LOW", "MODERATE", "HIGH"]
    description: str
    affected_zones: List[str] = Field(default_factory=list)
    source_report: str
    related_domains: List[str] = Field(default_factory=list)
    cascading_risk: Optional[str] = None


class CitySituationReport(BaseModel):
    """City-wide situation report combining all domain agents."""
    generated_at: datetime
    overall_city_status: Literal["NORMAL", "ELEVATED", "DISRUPTED", "CRITICAL", "UNKNOWN"] = "UNKNOWN"
    overall_risk_level: Literal["LOW", "MODERATE", "HIGH", "CRITICAL", "UNKNOWN"] = "UNKNOWN"
    
    domain_status: Dict[str, DomainStatus] = Field(default_factory=dict)
    
    priority_incidents: List[PriorityIncident] = Field(default_factory=list)
    cross_domain_impacts: List[CrossDomainImpact] = Field(default_factory=list)
    
    city_level_recommendations: List[str] = Field(default_factory=list)
    affected_zones: List[str] = Field(default_factory=list)
    
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    limitations: List[str] = Field(default_factory=list)
    
    source_reports: Dict[str, Any] = Field(default_factory=dict)
    
    is_ml_prediction: bool = False