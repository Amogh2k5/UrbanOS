"""Waste Management domain models.

Design rules (mirrors the Water / Fire modules):
  * Every section says *what kind* of data it holds (``DataKind``): live, latest_available,
    historical, reference, forecast or unavailable.  Nothing in this module is ``live``:
    all official waste data is annual statistics or static location/licence listings.
  * Missing data is ``None`` / ``unavailable`` - never zero, never guessed.
  * Quantities keep the source unit (tonnes); rates are percent.
  * No ML output exists unless the data supports it (see ForecastSection).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# "reference" = infrastructure / licence listings that are not refreshed continuously.
DataKind = Literal["live", "latest_available", "historical", "reference", "forecast", "unavailable"]
AlertSeverity = Literal["LOW", "MODERATE"]


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
    status: Literal["ok", "stale_cache", "loading", "unavailable"] = "unavailable"
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
    change_abs: Optional[float] = None   # same unit as value (percentage points for rates)
    change_pct: Optional[float] = None   # only for quantities, never for rates
    published_value: Optional[float] = None  # the agency's own (rounded) figure, when it exists
    note: Optional[str] = None
    data_kind: DataKind = "latest_available"
    source_key: Optional[str] = None


class UnavailableMetric(BaseModel):
    """A metric the brief asks for that the verified sources cannot support."""

    key: str
    label: str
    reason: str


# ----------------------------------------------------------- generation
class GenerationSection(BaseModel):
    data_kind: DataKind = "unavailable"
    resolution: str = "annual"
    latest_year: Optional[int] = None
    first_year: Optional[int] = None
    generated: Optional[AnnualSeries] = None
    recycled: Optional[AnnualSeries] = None
    disposed: Optional[AnnualSeries] = None
    recycling_rate_published: Optional[AnnualSeries] = None   # % as published (rounded to a point)
    recycling_rate_computed: Optional[AnnualSeries] = None    # % recycled / generated from tonnes
    recycling_rate_excl_cd: Optional[AnnualSeries] = None     # % excluding construction & demolition
    peak_generated_year: Optional[int] = None
    peak_generated_tonnes: Optional[float] = None
    peak_recycling_rate_year: Optional[int] = None
    peak_recycling_rate_pct: Optional[float] = None
    generated_change_since_peak_pct: Optional[float] = None
    disposed_is_series_high: bool = False
    limitations: List[str] = Field(default_factory=list)


# ----------------------------------------------------------- categories
class CategoryRow(BaseModel):
    key: str
    label: str
    generated: Optional[float] = None
    recycled: Optional[float] = None
    disposed: Optional[float] = None
    recycling_rate_published: Optional[float] = None
    recycling_rate_computed: Optional[float] = None
    share_of_generated_pct: Optional[float] = None
    share_of_disposed_pct: Optional[float] = None
    previous_generated: Optional[float] = None
    generated_change_pct: Optional[float] = None


class CategorySeries(BaseModel):
    key: str
    label: str
    generated: AnnualSeries
    recycled: AnnualSeries
    disposed: AnnualSeries
    recycling_rate: AnnualSeries


class CategorySection(BaseModel):
    data_kind: DataKind = "unavailable"
    latest_year: Optional[int] = None
    rows: List[CategoryRow] = Field(default_factory=list)          # sorted by tonnes generated, desc
    top_disposed: List[str] = Field(default_factory=list)          # keys, largest tonnes disposed first
    series: List[CategorySeries] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


# ----------------------------------------------------------- food waste
class FoodSection(BaseModel):
    data_kind: DataKind = "unavailable"
    latest_year: Optional[int] = None
    generated: Optional[Indicator] = None
    recycled: Optional[Indicator] = None
    disposed: Optional[Indicator] = None
    recycling_rate: Optional[Indicator] = None
    share_of_total_generated_pct: Optional[float] = None
    share_of_total_disposed_pct: Optional[float] = None
    series_generated: Optional[AnnualSeries] = None
    series_recycled: Optional[AnnualSeries] = None
    series_disposed: Optional[AnnualSeries] = None
    series_recycling_rate: Optional[AnnualSeries] = None
    limitations: List[str] = Field(default_factory=list)


# ----------------------------------------------------------- services
class ServiceClass(BaseModel):
    key: str                 # "A", "B", "B.1", "C"
    label: str
    description: str
    licensees: int = 0


class ServicesSection(BaseModel):
    """NEA-licensed general waste collectors. Counts only - contact details are not exposed."""

    data_kind: DataKind = "unavailable"
    licensee_count: Optional[int] = None
    duplicate_records_removed: int = 0
    classes: List[ServiceClass] = Field(default_factory=list)
    unrecognised_class_values: List[str] = Field(default_factory=list)
    class_combinations: Dict[str, int] = Field(default_factory=dict)
    dataset_period: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)


# ----------------------------------------------------------- infrastructure
class FacilityKindSummary(BaseModel):
    key: str                         # "recycling_bins" | "ewaste" | "lighting_waste"
    label: str
    count: int = 0
    invalid_records: int = 0
    duplicate_records_removed: int = 0
    by_name: Dict[str, int] = Field(default_factory=dict)
    record_date_min: Optional[str] = None   # ISO date of the oldest per-record update stamp
    record_date_max: Optional[str] = None   # ISO date of the newest per-record update stamp
    dataset_last_updated: Optional[str] = None
    data_kind: DataKind = "reference"
    status: Literal["ok", "stale_cache", "loading", "unavailable"] = "unavailable"
    note: str = ""


class InfrastructureSection(BaseModel):
    data_kind: DataKind = "unavailable"
    total_locations: int = 0
    kinds: List[FacilityKindSummary] = Field(default_factory=list)
    map_available: bool = False
    limitations: List[str] = Field(default_factory=list)


# ----------------------------------------------------------- forecast
class ForecastSection(BaseModel):
    available: bool = False
    data_kind: DataKind = "unavailable"
    reason: str = ""
    target: str = "Total waste generated (tonnes per year)"
    observations: int = 0
    frequency: str = "annual"
    minimum_observations_required: int = 0
    model: Optional[str] = None
    baseline: Optional[str] = None
    mae: Optional[float] = None
    rmse: Optional[float] = None


# ----------------------------------------------------------- data quality
class QualityCheck(BaseModel):
    key: str
    description: str
    passed: bool
    checked: int = 0
    failures: List[str] = Field(default_factory=list)


class DataQualitySection(BaseModel):
    checks: List[QualityCheck] = Field(default_factory=list)
    large_year_on_year_changes: List[str] = Field(default_factory=list)
    duplicate_series_rows: int = 0
    unparseable_cells: int = 0
    missing_cells: int = 0


# ----------------------------------------------------------- alerts / insights
class WasteAlert(BaseModel):
    id: str
    severity: AlertSeverity
    category: str
    message: str
    evidence: List[str] = Field(default_factory=list)
    data_kind: DataKind = "latest_available"


class WasteInsight(BaseModel):
    question: str
    answer: str
    data_kind: DataKind


# ----------------------------------------------------------- report
class WasteReport(BaseModel):
    generated_at: datetime
    domain: str = "infrastructure"
    subdomain: str = "waste"

    # Coordinator-facing roll-up. Waste has no live operational signal, so risk is always UNKNOWN
    # (never "LOW"); ``status`` only says whether official statistics could be loaded.
    status: Literal["STATISTICS_AVAILABLE", "PARTIAL", "UNAVAILABLE"] = "UNAVAILABLE"
    overall_risk: Literal["LOW", "MODERATE", "HIGH", "CRITICAL", "UNKNOWN"] = "UNKNOWN"
    summary: str = ""

    kpis: List[Indicator] = Field(default_factory=list)
    generation: GenerationSection = Field(default_factory=GenerationSection)
    categories: CategorySection = Field(default_factory=CategorySection)
    food: FoodSection = Field(default_factory=FoodSection)
    services: ServicesSection = Field(default_factory=ServicesSection)
    infrastructure: InfrastructureSection = Field(default_factory=InfrastructureSection)
    unavailable_metrics: List[UnavailableMetric] = Field(default_factory=list)
    forecast: ForecastSection = Field(default_factory=ForecastSection)
    data_quality: DataQualitySection = Field(default_factory=DataQualitySection)

    alerts: List[WasteAlert] = Field(default_factory=list)
    insights: List[WasteInsight] = Field(default_factory=list)
    sources: List[SourceInfo] = Field(default_factory=list)
    data_timestamps: Dict[str, Any] = Field(default_factory=dict)

    confidence: Literal["high", "medium", "low"] = "low"
    limitations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    is_ml_prediction: bool = False

    def model_dump_json_safe(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")
