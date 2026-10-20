"""HousingReport schema; source semantics and availability remain explicit."""
from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class HousingSource(BaseModel):
    key: str
    name: str
    agency: str
    url: str
    status: str
    retrieved_at: datetime | None = None
    error: str | None = None
    record_count: int = 0
    fields: list[str] = Field(default_factory=list)


class HousingInsight(BaseModel):
    question: str
    answer: str
    data_kind: str


# --- Forecast models ---
class ForecastPoint(BaseModel):
    """Single forecast point for a town/flat-type combination."""
    town: str
    flat_type: str
    forecast_period: str
    predicted_price: float
    unit: str = "SGD"
    method: str
    baseline_comparison: dict[str, Any] = Field(default_factory=dict)


class HousingForecast(BaseModel):
    """Next-quarter resale price forecast report."""
    generated_at: datetime
    domain: str = "planning"
    subdomain: str = "housing"
    target_period: str
    forecast_horizon: str = "1_quarter"
    forecasts: list[ForecastPoint]
    method: str
    evaluation: dict[str, Any] = Field(default_factory=dict)
    model_version: str
    data_freshness: str
    limitations: list[str] = Field(default_factory=list)
    is_ml_prediction: bool = False


class HousingReport(BaseModel):
    generated_at: datetime
    domain: str = "planning"
    subdomain: str = "housing"
    status: str = "PARTIAL"
    kpis: dict[str, Any] = Field(default_factory=dict)
    resale_trend: list[dict[str, Any]] = Field(default_factory=list)
    town_prices: list[dict[str, Any]] = Field(default_factory=list)
    resale_by_flat_type: list[dict[str, Any]] = Field(default_factory=list)
    housing_stock: dict[str, Any] = Field(default_factory=dict)
    rental_market: dict[str, Any] = Field(default_factory=dict)
    private_residential: dict[str, Any] = Field(default_factory=dict)
    supply_pipeline: dict[str, Any] = Field(default_factory=dict)
    household_context: dict[str, Any] = Field(default_factory=dict)
    map_data: dict[str, Any] = Field(default_factory=dict)
    sources: list[HousingSource] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    insights: list[HousingInsight] = Field(default_factory=list)
    confidence: str = "low"
    data_timestamps: dict[str, Any] = Field(default_factory=dict)
    is_ml_prediction: bool = False