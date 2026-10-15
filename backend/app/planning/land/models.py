"""Land domain models.

Design rules (mirrors the Water and Fire modules):
  * Every section says *what kind* of data it holds (``DataKind``).
  * Missing data is ``None`` / ``UNAVAILABLE`` - never zero, never guessed.
  * No ML output exists; this module is deterministic official-data reporting.

Vocabulary that must not be blurred (see docs/PLANNING_LAND_MODULE.md):
  * a **cadastral parcel** is a surveyed boundary, NOT available land;
  * **planned land use** is the statutory zoning designation, NOT current
    physical use;
  * a **GLS site** is one specific government land sale, NOT the whole
    developable land stock.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

DataKind = Literal["live", "latest_available", "historical", "forecast", "unavailable"]


class LandSource(BaseModel):
    """Provenance + runtime status for one official dataset actually used."""

    key: str
    organization: str
    name: str
    identifier: str
    layer_name: str
    url: str
    purpose: str
    update_frequency: str
    coverage: str
    authentication: str
    data_kind: DataKind
    crs: str
    component: str
    # Runtime status
    status: Literal["ok", "stale_cache", "unavailable"] = "unavailable"
    last_fetched_at: Optional[datetime] = None
    record_count: Optional[int] = None
    source_data_date: Optional[str] = None
    error: Optional[str] = None


# ------------------------------------------------------------------ land use
class LandUseCategory(BaseModel):
    """One official URA land-use designation aggregated across the island.

    ``area_sqm`` comes from the source's own SHAPE.AREA attribute (summed); it
    is not re-derived from geometry.
    """

    code: str
    label: str
    group: str  # residential | commercial | industrial | institutional | transport | recreation | water | other
    area_sqm: Optional[float] = None
    area_pct: Optional[float] = None
    zone_count: Optional[int] = None
    data_kind: DataKind = "latest_available"


class LandUseSection(BaseModel):
    data_kind: DataKind = "unavailable"
    source_layer: str = "G_MP25_LANDUSE_PL"
    total_zones: Optional[int] = None
    total_area_sqm: Optional[float] = None
    total_area_km2: Optional[float] = None
    distinct_categories: Optional[int] = None
    categories: List[LandUseCategory] = Field(default_factory=list)
    by_group: Dict[str, Optional[float]] = Field(default_factory=dict)
    invalid_zones: int = 0
    zones_inspected: int = 0
    gpr: GrossPlotRatioSection = Field(default_factory=lambda: GrossPlotRatioSection())
    limitations: List[str] = Field(default_factory=list)


class GprValue(BaseModel):
    value: Optional[float] = None
    zone_count: Optional[int] = None


class GrossPlotRatioSection(BaseModel):
    """Master Plan GPR. 'LND'/'EVA'/'SDP' are non-numeric official codes and
    are reported as codes, never coerced to 0."""

    data_kind: DataKind = "unavailable"
    reported_numeric: Optional[GprValue] = None
    special_codes: Dict[str, Optional[int]] = Field(default_factory=dict)
    median: Optional[float] = None
    p25: Optional[float] = None
    p75: Optional[float] = None
    max: Optional[float] = None
    limitations: List[str] = Field(default_factory=list)


# ------------------------------------------------------------ planning areas
class PlanningArea(BaseModel):
    name: str
    code: Optional[str] = None
    region: Optional[str] = None
    region_code: Optional[str] = None
    area_sqm: Optional[float] = None
    land_use_area_sqm: Optional[float] = None
    land_use_coverage_pct: Optional[float] = None
    dominant_category: Optional[str] = None
    dominant_category_pct: Optional[float] = None
    zone_count: Optional[int] = None
    group_area_sqm: Dict[str, Optional[float]] = Field(default_factory=dict)
    unassigned_zone_count: int = 0
    # Exterior ring (WGS84 lon/lat) carried so /map can serve planning-area
    # geometry without the report re-reading the source.
    outer_ring: Optional[List[List[float]]] = None


class PlanningSection(BaseModel):
    data_kind: DataKind = "unavailable"
    planning_area_count: Optional[int] = None
    region_count: Optional[int] = None
    regions: List[Dict[str, Any]] = Field(default_factory=list)
    planning_areas: List[PlanningArea] = Field(default_factory=list)
    invalid_features: int = 0
    method: str = ""
    limitations: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------- cadastral
class CadastralSection(BaseModel):
    data_kind: DataKind = "unavailable"
    source_layer: str = "CADASTRAL_LAND_LOT"
    parcel_count: Optional[int] = None
    total_area_sqm: Optional[float] = None
    median_area_sqm: Optional[float] = None
    invalid_features: int = 0
    features_inspected: int = 0
    duplicate_lot_keys: int = 0
    ownership_available: bool = False
    ownership_note: str = (
        "This dataset publishes surveyed boundaries and lot numbers only. Land "
        "ownership is not part of the open cadastral layer and is not inferred here."
    )
    limitations: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------- GLS
class GlsSite(BaseModel):
    location: Optional[str] = None
    development_code: Optional[str] = None
    development_allowed: Optional[str] = None
    planning_area: Optional[str] = None
    site_area_sqm: Optional[float] = None
    gross_plot_ratio: Optional[float] = None
    gross_floor_area_sqm: Optional[float] = None
    housing_units: Optional[float] = None
    award_year: Optional[int] = None
    award_date: Optional[str] = None
    successful_tenderer: Optional[str] = None
    successful_price: Optional[float] = None
    no_of_bids: Optional[float] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None


class GlsSection(BaseModel):
    data_kind: DataKind = "latest_available"
    source_layer: str = "URA_SALE_SITE_PL"
    scope: str = "Awarded/completed Government Land Sales sites recorded by URA (from 1967)."
    current_program_available: bool = False
    current_program_note: str = (
        "The current Confirmed List / Reserve List is published by URA as a web "
        "page and press-release PDF, not as an open dataset, so it is not "
        "represented here. Nothing in this section implies a site is currently "
        "available for sale."
    )
    site_count: Optional[int] = None
    total_site_area_sqm: Optional[float] = None
    by_development_code: Dict[str, Optional[int]] = Field(default_factory=dict)
    by_year: Dict[str, Optional[int]] = Field(default_factory=dict)
    award_year_min: Optional[int] = None
    award_year_max: Optional[int] = None
    total_housing_units: Optional[float] = None
    latest_sites: List[GlsSite] = Field(default_factory=list)
    invalid_features: int = 0
    limitations: List[str] = Field(default_factory=list)


# -------------------------------------------------------------- industrial
class IndustrialSection(BaseModel):
    data_kind: DataKind = "unavailable"
    source_layer: str = "JTC_ESTATE_NAME"
    estate_count: Optional[int] = None
    total_estate_area_sqm: Optional[float] = None
    total_estate_area_km2: Optional[float] = None
    largest_estates: List[Dict[str, Any]] = Field(default_factory=list)
    industrial_land_use_area_sqm: Optional[float] = None
    industrial_land_use_note: str = (
        "Industrial land-use area is summed from Master Plan land-use zones "
        "designated BUSINESS 1 / BUSINESS 2 (URA). JTC estate boundaries are "
        "indicative estate extents, not the full industrial land stock."
    )
    source_data_date: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)


# ------------------------------------------------------- alerts / insights
class LandAlert(BaseModel):
    id: str
    severity: Literal["LOW", "MODERATE", "HIGH"]
    category: str
    message: str
    evidence: List[str] = Field(default_factory=list)
    data_kind: DataKind = "latest_available"


class LandInsight(BaseModel):
    question: str
    answer: str
    data_kind: DataKind


# ------------------------------------------------------------------ report
class LandReport(BaseModel):
    generated_at: datetime
    domain: str = "planning"
    subdomain: str = "land"

    source_status: Literal["available", "partial", "unavailable"] = "unavailable"

    land_use: LandUseSection = Field(default_factory=LandUseSection)
    planning: PlanningSection = Field(default_factory=PlanningSection)
    cadastral: CadastralSection = Field(default_factory=CadastralSection)
    gls: GlsSection = Field(default_factory=GlsSection)
    industrial: IndustrialSection = Field(default_factory=IndustrialSection)

    alerts: List[LandAlert] = Field(default_factory=list)
    insights: List[LandInsight] = Field(default_factory=list)
    sources: List[LandSource] = Field(default_factory=list)
    data_timestamps: Dict[str, Any] = Field(default_factory=dict)

    confidence: Literal["high", "medium", "low"] = "low"
    limitations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    is_ml_prediction: bool = False

    def model_dump_json_safe(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")