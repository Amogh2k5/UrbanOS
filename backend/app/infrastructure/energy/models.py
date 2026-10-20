"""Structured schemas for official Singapore energy statistics."""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class EnergySource(BaseModel):
    name: str
    organization: str = "Energy Market Authority (EMA)"
    dataset_id: str
    url: str
    frequency: str
    coverage: str
    unit: str
    status: str = "unavailable"
    latest_period: Optional[str] = None
    records: int = 0
    error: Optional[str] = None


class EnergyPoint(BaseModel):
    period: str
    value: Optional[float] = None


class EnergyReport(BaseModel):
    generated_at: datetime
    domain: str = "infrastructure"
    subdomain: str = "energy"
    status: str = "PARTIAL"
    summary: str
    key_metrics: dict[str, Any] = Field(default_factory=dict)
    peak_demand: list[dict[str, Any]] = Field(default_factory=list)
    consumption: list[dict[str, Any]] = Field(default_factory=list)
    solar_by_region: list[dict[str, Any]] = Field(default_factory=list)
    solar_capacity: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[EnergySource] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    forecast: dict[str, Any] = Field(default_factory=lambda: {
        "available": False,
        "reason": "A verified, accessible half-hourly system-demand time series was not established; no forecast is generated."
    })
    confidence: str = "low"
    data_timestamps: dict[str, Any] = Field(default_factory=dict)
    is_ml_prediction: bool = False