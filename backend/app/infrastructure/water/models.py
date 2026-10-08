"""Water domain models.

Design rules (mirrors the Fire module):
  * Every section says *what kind* of data it holds (``DataKind``): live,
    latest_available, historical, forecast or unavailable.
  * Missing data is ``None`` / ``UNAVAILABLE`` - never zero, never guessed.
  * No ML output exists unless the data supports it (see ForecastSection).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

DataKind = Literal["live", "latest_available", "historical", "forecast", "unavailable"]
DrainCondition = Literal["NORMAL", "ELEVATED", "HIGH", "CRITICAL", "UNAVAILABLE"]
AlertSeverity = Literal["LOW", "MODERATE", "HIGH"]
Trend = Literal["rising", "falling", "stable", "unknown"]


class SourceInfo(BaseModel):
    """Provenance for one official source actually used by the module."""

    key: str
    organization: str
    name: str
    identifier: str
    url: str
    purpose: str
    update_frequency: str
    coverage: str
    authentication: str
    data_kind: DataKind
    component: str
    # Runtime status
    status: Literal["ok", "stale_cache", "unavailable"] = "unavailable"
    last_fetched_at: Optional[datetime] = None
    latest_data_period: Optional[str] = None
    record_count: Optional[int] = None
    error: Optional[str] = None


class AnnualPoint(BaseModel):
    year: int
    value: Optional[float] = None  # None = source reported "na"/missing


class AnnualSeries(BaseModel):
    key: str
    label: str
    unit: str
    points: List[AnnualPoint] = Field(default_factory=list)
    data_kind: DataKind = "historical"
    source_key: Optional[str] = None


class Indicator(BaseModel):
    key: str
    label: str
    value: Optional[float] = None
    unit: str = ""
    period: Optional[str] = None  # e.g. "2025"
    previous_value: Optional[float] = None
    previous_period: Optional[str] = None
    change_abs: Optional[float] = None
    change_pct: Optional[float] = None
    data_kind: DataKind = "latest_available"
    source_key: Optional[str] = None


# ------------------------------------------------------------------ supply
class SupplySection(BaseModel):
    data_kind: DataKind = "latest_available"
    status: Literal["SALES_DATA_ONLY", "UNAVAILABLE"] = "UNAVAILABLE"
    period: Optional[str] = None
    # Reservoir storage has NO official open feed that we could find.
    reservoir_storage_available: bool = False
    reservoir_storage_note: str = (
        "No official open dataset or API for reservoir storage levels was found "
        "on data.gov.sg or PUB; none is shown."
    )
    indicators: List[Indicator] = Field(default_factory=list)
    newater_share_of_water_sales_pct: Optional[float] = None
    series: List[AnnualSeries] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


# ------------------------------------------------------------------- drain
class DrainSensor(BaseModel):
    id: str
    name: Optional[str] = None
    latitude: float
    longitude: float


class DrainReading(BaseModel):
    """One water-level observation. Only produced by a real reading provider."""

    sensor_id: str
    observed_at: datetime
    water_level_m: float
    reference_depth_m: float


class DrainSensorStatus(BaseModel):
    sensor: DrainSensor
    condition: DrainCondition = "UNAVAILABLE"
    water_level_m: Optional[float] = None
    reference_depth_m: Optional[float] = None
    percentage: Optional[float] = None
    observed_at: Optional[datetime] = None
    trend: Trend = "unknown"


class DrainSection(BaseModel):
    data_kind: DataKind = "unavailable"
    readings_available: bool = False
    sensor_locations_available: bool = False
    sensor_count: int = 0
    sensors_with_readings: int = 0
    condition_counts: Dict[str, int] = Field(default_factory=dict)
    thresholds: Dict[str, str] = Field(default_factory=dict)
    threshold_source: str = ""
    sensors: List[DrainSensorStatus] = Field(default_factory=list)
    latest_reading_at: Optional[datetime] = None
    locations_dataset_period: Optional[str] = None
    invalid_sensor_records: int = 0
    limitations: List[str] = Field(default_factory=list)


# ------------------------------------------------------------------- usage
class UsageSection(BaseModel):
    data_kind: DataKind = "latest_available"
    resolution: str = "annual"
    latest_year: Optional[int] = None
    potable_total: Optional[Indicator] = None
    domestic: Optional[Indicator] = None
    non_domestic: Optional[Indicator] = None
    domestic_share_pct: Optional[float] = None
    non_domestic_share_pct: Optional[float] = None
    cagr_pct_since_2015: Optional[float] = None
    series: List[AnnualSeries] = Field(default_factory=list)
    consistency_warnings: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class ForecastSection(BaseModel):
    available: bool = False
    data_kind: DataKind = "unavailable"
    reason: str = ""
    target: str = "Potable water sales (million m3 per year)"
    observations: int = 0
    frequency: str = "annual"
    minimum_observations_required: int = 0
    model: Optional[str] = None
    baseline: Optional[str] = None
    mae: Optional[float] = None
    rmse: Optional[float] = None
    horizon: Optional[str] = None
    training_period: Optional[str] = None
    validation_test_period: Optional[str] = None


# ----------------------------------------------------------------- newater
class NEWaterSection(BaseModel):
    data_kind: DataKind = "historical"
    latest: Optional[Indicator] = None
    share_of_water_sales_pct: Optional[float] = None
    cagr_pct_since_2015: Optional[float] = None
    series: List[AnnualSeries] = Field(default_factory=list)
    long_run_source_note: str = ""
    limitations: List[str] = Field(default_factory=list)


# ----------------------------------------------------------------- quality
class QualityParameter(BaseModel):
    key: str
    parameter: str
    unit: str
    average: Optional[str] = None
    average_value: Optional[float] = None
    range: Optional[str] = None
    range_min: Optional[float] = None
    range_max: Optional[float] = None
    regulatory_limit: Optional[str] = None
    compliance: Literal["WITHIN_LIMIT", "EXCEEDS_LIMIT", "NO_LIMIT_PUBLISHED", "UNKNOWN"] = "UNKNOWN"


class QualitySection(BaseModel):
    data_kind: DataKind = "latest_available"
    reporting_period: Optional[str] = None
    frequency: str = "annual (average and range over the calendar year)"
    parameters: List[QualityParameter] = Field(default_factory=list)
    other_parameter_count: int = 0
    limit_source: str = (
        "PUB 'Our Drinking Water Quality' table (Environmental Public Health "
        "(Water Suitable for Drinking) Regulations): pH 6.5-9.5, turbidity <=5 NTU, "
        "colour <=15 Hazen, E. coli <1 cfu/100mL"
    )
    limitations: List[str] = Field(default_factory=list)


# ------------------------------------------------------- alerts / insights
class WaterAlert(BaseModel):
    id: str
    severity: AlertSeverity
    category: str
    message: str
    evidence: List[str] = Field(default_factory=list)
    data_kind: DataKind = "latest_available"


class WaterInsight(BaseModel):
    question: str
    answer: str
    data_kind: DataKind


# ------------------------------------------------------------------ report
class WaterReport(BaseModel):
    generated_at: datetime
    domain: str = "infrastructure"
    subdomain: str = "water"

    # Coordinator-facing roll-up. UNKNOWN unless live drain readings exist.
    overall_status: Literal["NORMAL", "ELEVATED", "CRITICAL", "UNKNOWN"] = "UNKNOWN"
    overall_risk: Literal["LOW", "MODERATE", "HIGH", "CRITICAL", "UNKNOWN"] = "UNKNOWN"

    supply: SupplySection = Field(default_factory=SupplySection)
    drain: DrainSection = Field(default_factory=DrainSection)
    usage: UsageSection = Field(default_factory=UsageSection)
    forecast: ForecastSection = Field(default_factory=ForecastSection)
    newater: NEWaterSection = Field(default_factory=NEWaterSection)
    quality: QualitySection = Field(default_factory=QualitySection)

    alerts: List[WaterAlert] = Field(default_factory=list)
    insights: List[WaterInsight] = Field(default_factory=list)
    sources: List[SourceInfo] = Field(default_factory=list)
    data_timestamps: Dict[str, Any] = Field(default_factory=dict)

    confidence: Literal["high", "medium", "low"] = "low"
    limitations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    is_ml_prediction: bool = False

    def model_dump_json_safe(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")
