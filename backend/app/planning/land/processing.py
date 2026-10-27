"""Deterministic Land analytics.

Everything here is a pure function of the acquired official records. There is no
ML model and no invented score: every derived number below is either a count, a
sum of a source-published area attribute, or a percentage of such a sum, and
each carries its unit and formula in the code that produces it.

Category grouping
-----------------
URA publishes ~40 free-text ``LU_DESC`` designations. Analytics need a small,
stable set of groups, so designations are mapped explicitly by exact string.
Anything not matched is grouped as ``other`` and still reported individually -
it is never dropped and never merged into a group it does not belong to.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.app.planning.land.models import (
    AnnualMedianRecord, CadastralSection, ForecastMethodResult, GlsPriceForecastEvaluation,
    GlsPriceForecastSection, GprValue, GlsSection, GlsSite, GrossPlotRatioSection,
    IndustrialSection, LandAlert, LandUseCategory, LandUseSection, PlanningArea,
    PlanningSection,
)
from backend.app.planning.land.sources import LandSnapshot

# ---------------------------------------------------------------- grouping
# Exact-match mapping from URA LU_DESC to an analytical group. Derived only from
# designations observed in G_MP25_LANDUSE_PL.
_LU_GROUP: Dict[str, str] = {
    # Residential
    "RESIDENTIAL": "residential",
    "RESIDENTIAL WITH COMMERCIAL AT 1ST STOREY": "residential",
    "COMMERCIAL & RESIDENTIAL": "residential",
    "RESIDENTIAL / INSTITUTION": "residential",
    "RESIDENTIAL / COMMERCIAL": "residential",
    # Commercial
    "COMMERCIAL": "commercial",
    "COMMERCIAL 2": "commercial",
    "BUSINESS 1": "industrial",
    "BUSINESS 2": "industrial",
    # 'Business Park' and its '- White' variant are the same URA business-zone
    # family, so they must land in the same group as BUSINESS 1 / BUSINESS 2.
    "BUSINESS PARK": "industrial",
    "BUSINESS PARK - WHITE": "industrial",
    "BUSINESS 1 - WHITE": "industrial",
    "BUSINESS 2 - WHITE": "industrial",
    "WHITE": "commercial",
    "SHOPPING": "commercial",
    "HOTEL": "commercial",
    "RECREATIONAL": "commercial",
    "ENTERTAINMENT": "commercial",
    # Institutional
    "EDUCATIONAL INSTITUTION": "institutional",
    "CIVIC & COMMUNITY INSTITUTION": "institutional",
    "HEALTH & MEDICAL CARE": "institutional",
    "PLACE OF WORSHIP": "institutional",
    "CEMETERY": "institutional",
    "RELIGIOUS": "institutional",
    "INSTITUTIONAL": "institutional",
    "COMMERCIAL / INSTITUTION": "institutional",
    # Transport / infrastructure
    "TRANSPORT FACILITIES": "transport",
    "PORT / AIRPORT": "transport",
    "ROAD": "transport",
    "RAILWAY": "transport",
    # Rail corridors are transport land use; they were previously falling through
    # to 'other' while ROAD and TRANSPORT FACILITIES were mapped here.
    "MASS RAPID TRANSIT": "transport",
    "LIGHT RAPID TRANSIT": "transport",
    # Recreation / open space
    "PARK": "recreation",
    "OPEN SPACE": "recreation",
    "SPORTS & RECREATION": "recreation",
    "BEACH AREA": "recreation",
    "NATURAL": "recreation",
    "GREEN": "recreation",
    # Water
    "WATERBODY": "water",
    # Other official designations
    "UTILITY": "other",
    "RESERVE SITE": "other",
    "SPECIAL USE": "other",
    "MISCELLANEOUS": "other",
    "DEVELOPMENT": "other",
    # URA publishes this designation with no counterpart in the eight groups;
    # listed explicitly so the audit can prove nothing reaches the fallback.
    "AGRICULTURE": "other",
}

GROUP_LABELS = {
    "residential": "Residential",
    "commercial": "Commercial",
    "industrial": "Industrial",
    "institutional": "Institutional",
    "transport": "Transport",
    "recreation": "Parks / Recreation",
    "water": "Water",
    "other": "Other",
}

# Official, non-numeric GPR codes seen in the layer. Reported as codes.
GPR_SPECIAL_CODES = ("LND", "EVA", "SDP")


def category_group(lu_desc: str) -> str:
    """Group one official designation. Unmatched -> 'other' (still reported)."""
    return _LU_GROUP.get(str(lu_desc or "").strip().upper(), "other")


def _slug(lu_desc: str) -> str:
    return "_".join(str(lu_desc or "").strip().upper().replace("&", "AND").split())


def _percent(part: Optional[float], whole: Optional[float]) -> Optional[float]:
    if part is None or whole in (None, 0):
        return None
    return round(part / whole * 100.0, 2)


# ---------------------------------------------------------------- land use
def build_land_use_section(snap: LandSnapshot) -> LandUseSection:
    """Aggregate Master Plan land-use zones by designation and by group."""
    sec = LandUseSection()
    records = snap.land_use or []
    sec.zones_inspected = snap.land_use_total_seen or len(records)
    sec.invalid_zones = snap.land_use_invalid
    sec.limitations.append(
        "Areas are the sum of the source's own SHAPE.AREA attribute for each "
        "Master Plan land-use zone, in square metres. They describe statutory "
        "PLANNED land-use zoning, not current physical use."
    )
    if not records:
        sec.limitations.append("No usable Master Plan land-use zones were acquired.")
        return sec

    by_code_area: Dict[str, float] = {}
    by_code_count: Dict[str, int] = {}
    total_area = 0.0
    area_counted = 0
    for rec in records:
        desc = rec["lu_desc"]
        by_code_count[desc] = by_code_count.get(desc, 0) + 1
        area = rec.get("area_sqm")
        if area is not None and area >= 0:
            by_code_area[desc] = by_code_area.get(desc, 0.0) + area
            total_area += area
            area_counted += 1

    sec.total_zones = len(records)
    sec.total_area_sqm = round(total_area, 1) if area_counted else None
    sec.total_area_km2 = round(total_area / 1e6, 2) if area_counted else None
    sec.distinct_categories = len(by_code_count)

    categories: List[LandUseCategory] = []
    group_area: Dict[str, float] = {}
    # Group and total sums are accumulated from the RAW per-zone areas, never
    # from the rounded per-designation values, so the displayed categories sum
    # exactly to the displayed total (rounding is applied once, at output).
    for desc, cnt in by_code_count.items():
        grp = category_group(desc)
        raw = by_code_area.get(desc)
        if raw is not None:
            group_area[grp] = group_area.get(grp, 0.0) + raw
        categories.append(
            LandUseCategory(
                code=_slug(desc),
                label=desc.title(),
                group=grp,
                area_sqm=round(raw, 1) if raw is not None else None,
                area_pct=_percent(raw, total_area) if (raw is not None and total_area) else None,
                zone_count=cnt,
            )
        )
    categories.sort(key=lambda c: (-(c.area_sqm or 0.0), c.label))
    sec.categories = categories
    sec.by_group = {
        grp: (round(group_area.get(grp, 0.0), 1) if grp in group_area else None)
        for grp in GROUP_LABELS
    }
    sec.data_kind = "latest_available"
    return sec


def build_gpr_section(snap: LandSnapshot, land_use: LandUseSection) -> GrossPlotRatioSection:
    """Master Plan gross plot ratio distribution over zones that declare one."""
    sec = GrossPlotRatioSection()
    sec.limitations.append(
        "GPR is the statutory plot-ratio control attached to a land-use zone. A "
        "GPR value is a permission, not existing built floor area and not a "
        "measure of land that will be developed."
    )
    numeric: List[float] = []
    special: Dict[str, int] = {}
    for rec in snap.land_use or []:
        raw = rec.get("gpr")
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        try:
            value = float(text)
        except ValueError:
            if text.upper() in GPR_SPECIAL_CODES:
                special[text.upper()] = special.get(text.upper(), 0) + 1
            continue
        if value > 0:
            numeric.append(value)

    sec.special_codes = {code: special.get(code, 0) for code in GPR_SPECIAL_CODES if code in special}
    if numeric:
        numeric_sorted = sorted(numeric)
        sec.data_kind = "latest_available"
        sec.reported_numeric = GprValue(value=len(numeric), zone_count=len(numeric))
        sec.median = round(statistics.median(numeric_sorted), 3)
        sec.p25 = round(statistics.quantiles(numeric_sorted, n=4)[0], 3) if len(numeric_sorted) > 3 else None
        sec.p75 = round(statistics.quantiles(numeric_sorted, n=4)[2], 3) if len(numeric_sorted) > 3 else None
        sec.max = round(max(numeric_sorted), 3)
    return sec


# ---------------------------------------------------------- planning areas
def build_planning_section(snap: LandSnapshot) -> PlanningSection:
    """Attach land-use composition to each planning area via the grid index.

    Attribution method: each land-use zone is resolved to a planning area by
    testing its centroid against a ~280 m lon/lat grid rasterised from the
    Master Plan planning-area polygons. Zones whose centroid lands outside every
    planning area (sea, or a sliver at an edge) are counted as unassigned and
    never silently attributed to a neighbour.
    """
    sec = PlanningSection()
    areas = snap.planning_areas or []
    sec.regions = [
        {"name": r["name"], "code": r.get("code"), "area_sqm": r.get("area_sqm")}
        for r in (snap.regions or [])
    ]
    sec.region_count = len(sec.regions)
    sec.invalid_features = snap.planning_area_invalid
    sec.method = (
        "Land-use zones are attributed to a Master Plan 2025 planning area by "
        "centroid against a 0.0025 deg (~280 m) lon/lat grid built from the "
        "planning-area polygons."
    )
    sec.limitations.append(
        "Planning areas are Master Plan 2025 land-only boundaries; sea and "
        "marine areas are excluded by the source layer."
    )
    if not areas:
        sec.limitations.append("Planning-area boundaries unavailable.")
        return sec

    index = snap.planning_area_index
    # zone area + count per (planning area code, lu group)
    # zone area per (planning area, land-use group) and zone counts per designation
    pa_area: Dict[str, Dict[str, float]] = {}
    pa_codes: Dict[str, int] = {}
    pa_total: Dict[str, float] = {}
    pa_dom_counts: Dict[str, Tuple[int, str]] = {}

    for rec in snap.land_use or []:
        pa_code = None
        if index is not None and index.built:
            pa_code = index.lookup(rec["centroid_lon"], rec["centroid_lat"])
        key = pa_code or "__unassigned__"
        area = rec.get("area_sqm")
        pa_codes[key] = pa_codes.get(key, 0) + 1
        if area is not None:
            pa_area.setdefault(key, {})
            pa_area[key][category_group(rec["lu_desc"])] = (
                pa_area[key].get(category_group(rec["lu_desc"]), 0.0) + area
            )
            pa_total[key] = pa_total.get(key, 0.0) + area
        desc = rec["lu_desc"]
        cnt, best_desc = pa_dom_counts.get(key, (0, desc))
        pa_dom_counts[key] = (cnt + 1, best_desc)

    sec.planning_area_count = len(areas)
    out: List[PlanningArea] = []
    for pa in areas:
        key = str(pa.get("code") or pa.get("name"))
        total = pa_total.get(key)
        groups = pa_area.get(key, {})
        dom_count, dom_desc = pa_dom_counts.get(key, (0, None))
        dom_pct = _percent(float(dom_count), float(pa_codes.get(key, 0) or 0)) if pa_codes.get(key) else None
        out.append(
            PlanningArea(
                name=pa["name"],
                code=pa.get("code"),
                region=pa.get("region"),
                region_code=pa.get("region_code"),
                area_sqm=pa.get("area_sqm"),
                land_use_area_sqm=round(total, 1) if total is not None else None,
                land_use_coverage_pct=_percent(total, pa.get("area_sqm")),
                dominant_category=dom_desc.title() if dom_desc else None,
                dominant_category_pct=dom_pct,
                zone_count=pa_codes.get(key, 0),
                group_area_sqm={g: (round(v, 1) if v is not None else None) for g, v in groups.items()},
                unassigned_zone_count=0,
                outer_ring=pa.get("_outer_ring"),
            )
        )
    out.sort(key=lambda p: -(p.land_use_area_sqm or 0.0))
    sec.planning_areas = out

    unassigned_total = pa_codes.get("__unassigned__", 0)
    if unassigned_total:
        sec.limitations.append(
            f"{unassigned_total} land-use zones could not be attributed to a planning "
            "area by centroid and are excluded from the per-planning-area table."
        )
    sec.data_kind = "latest_available"
    return sec


# --------------------------------------------------------------- cadastral
def build_cadastral_section(snap: LandSnapshot) -> CadastralSection:
    sec = CadastralSection()
    records = snap.cadastral or []
    sec.features_inspected = snap.cadastral_total_seen or len(records)
    sec.invalid_features = snap.cadastral_invalid
    sec.duplicate_lot_keys = snap.duplicate_lot_keys
    sec.limitations.append(
        "A cadastral parcel is a surveyed legal boundary. Parcel count and area "
        "describe the cadastre only - they do NOT indicate developable or "
        "available land."
    )
    if not records:
        sec.limitations.append("Cadastral land parcel layer unavailable.")
        return sec

    areas = [r["area_sqm"] for r in records if r.get("area_sqm") is not None]
    sec.parcel_count = len(records)
    if areas:
        sec.total_area_sqm = round(sum(areas), 1)
        sec.median_area_sqm = round(statistics.median(areas), 1)
    sec.data_kind = "latest_available"
    return sec


# --------------------------------------------------------------------- GLS
def build_gls_section(snap: LandSnapshot) -> GlsSection:
    """URA Sale Sites: the machine-readable GLS programme record.

    These are AWARDED sites from 1967 onward. Nothing here is presented as a
    currently available site.
    """
    sec = GlsSection()
    records = snap.gls_sites or []
    sec.invalid_features = snap.gls_invalid
    sec.limitations.append(
        "Sites are recorded at the time of tender award. A site appearing here "
        "has been awarded and is not necessarily built out."
    )
    sec.limitations.append(sec.current_program_note)
    if not records:
        sec.data_kind = "unavailable"
        sec.limitations.append("URA Sale Sites layer unavailable.")
        return sec

    years = [r["award_year"] for r in records if r.get("award_year")]
    by_year: Dict[str, int] = {}
    for y in years:
        by_year[str(y)] = by_year.get(str(y), 0) + 1
    by_code: Dict[str, int] = {}
    for r in records:
        code = (r.get("devt_code") or "Unspecified").strip() or "Unspecified"
        by_code[code] = by_code.get(code, 0) + 1

    site_areas = [r["site_area_sqm"] for r in records if r.get("site_area_sqm") is not None]
    units = [r["housing_units"] for r in records if r.get("housing_units")]

    sec.site_count = len(records)
    sec.total_site_area_sqm = round(sum(site_areas), 1) if site_areas else None
    sec.by_development_code = dict(sorted(by_code.items(), key=lambda kv: -kv[1]))
    sec.by_year = dict(sorted(by_year.items()))
    sec.award_year_min = min(years) if years else None
    sec.award_year_max = max(years) if years else None
    sec.total_housing_units = sum(units) if units else None

    latest = sorted(
        [r for r in records if r.get("award_year")],
        key=lambda r: (r["award_year"], r.get("award_date") or ""),
        reverse=True,
    )[:40]
    sec.latest_sites = [
        GlsSite(
            location=r.get("location"),
            development_code=r.get("devt_code"),
            development_allowed=r.get("devt_allowed"),
            planning_area=r.get("planning_area"),
            site_area_sqm=r.get("site_area_sqm"),
            gross_plot_ratio=r.get("gpr"),
            gross_floor_area_sqm=r.get("gfa_sqm"),
            housing_units=r.get("housing_units"),
            award_year=r.get("award_year"),
            award_date=r.get("award_date"),
            successful_tenderer=r.get("successful_tenderer"),
            successful_price=r.get("successful_price"),
            no_of_bids=r.get("no_of_bids"),
            longitude=r.get("centroid_lon"),
            latitude=r.get("centroid_lat"),
        )
        for r in latest
    ]
    sec.data_kind = "historical"
    return sec


# ------------------------------------------- GLS price baseline estimate
SG_TZ = timezone(timedelta(hours=8))

# Verified during the Land ML feasibility audit: the only GLS development
# category with enough positive-GFA awarded sites to support a narrow
# baseline. Do not pool categories into this target.
PRICE_FORECAST_DEVELOPMENT_CODE = "Residential (Non-Landed)"

# Years supported by fewer eligible sites than this are flagged low-sample
# (the audit found 2021 has a single eligible site).
LOW_SAMPLE_SITE_THRESHOLD = 3

# A persistence forecast needs at least this many completed award years; with
# one year there is no evidence of any continuity to carry forward.
MIN_COMPLETED_YEARS_FOR_FORECAST = 2

# Walk-forward burn-in: the first 3 completed years seed every method, so all
# methods score an identical set of later years.
EVAL_BURN_IN_YEARS = 3

# The recent-period walk-forward comparison runs over the most recent
# RECENT_EVAL_YEARS completed award years, alongside the full-history window.
RECENT_EVAL_YEARS = 10

EVAL_METHODS = ("persistence", "expanding_median", "rolling_median_3")


def _finite_positive(value: Any) -> bool:
    """True only for a real, finite, strictly positive number - booleans and
    strings never qualify, so a sentinel can never become a fake observation."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _eligible_price_forecast_records(
    records: List[Dict[str, Any]], current_year: int
) -> Tuple[Dict[int, List[float]], Dict[str, int]]:
    """Waterfall filter from all GLS records down to eligible price-per-GFA
    observations, with an account of every exclusion so nothing is silently
    dropped.

    Eligibility, in order: exact development category match, valid award year,
    valid successful price (> 0), finite positive GFA. Records eligible but
    awarded in the still-in-progress current year (or later) are counted
    separately and excluded from training/evaluation.
    """
    counts: Dict[str, int] = {
        "sites_total": len(records),
        "sites_eligible": 0,
        "excluded_other_development_code": 0,
        "excluded_invalid_award_year": 0,
        "excluded_invalid_price": 0,
        "excluded_invalid_gfa": 0,
        "excluded_incomplete_or_future_year": 0,
    }
    by_year: Dict[int, List[float]] = {}
    for rec in records:
        if str(rec.get("devt_code") or "").strip() != PRICE_FORECAST_DEVELOPMENT_CODE:
            counts["excluded_other_development_code"] += 1
            continue
        year = rec.get("award_year")
        if not isinstance(year, int) or isinstance(year, bool) or year <= 0:
            counts["excluded_invalid_award_year"] += 1
            continue
        price = rec.get("successful_price")
        if not _finite_positive(price):
            counts["excluded_invalid_price"] += 1
            continue
        gfa = rec.get("gfa_sqm")
        if not _finite_positive(gfa):
            counts["excluded_invalid_gfa"] += 1
            continue
        counts["sites_eligible"] += 1
        if year >= current_year:
            counts["excluded_incomplete_or_future_year"] += 1
            continue
        by_year.setdefault(year, []).append(float(price) / float(gfa))
    return by_year, counts


def _annual_medians(by_year: Dict[int, List[float]]) -> Dict[int, Tuple[float, int]]:
    """{completed year: (median price per GFA, eligible site count)}."""
    return {
        year: (statistics.median(values), len(values))
        for year, values in sorted(by_year.items())
    }


def _walk_forward_evaluation(
    annual: Dict[int, Tuple[float, int]],
    burn_in: int = EVAL_BURN_IN_YEARS,
    window: str = "all_completed_years",
    window_note: str = "all completed award years",
) -> GlsPriceForecastEvaluation:
    """One-year-ahead chronological walk-forward over completed award years.

    Each test year is predicted using only strictly earlier years; all three
    methods are scored on an identical set of test periods. 'rolling_median_3'
    uses the (up to) three most recent *observed* earlier years, so gap years
    shrink the window instead of breaking the comparison.
    """
    years = sorted(annual)
    if len(years) < burn_in + 1:
        return GlsPriceForecastEvaluation(
            status="insufficient_history",
            window=window,
            insufficient_reason=(
                f"Only {len(years)} completed award year(s) with an eligible median; "
                f"a walk-forward comparison needs at least {burn_in + 1}."
            ),
            note=(
                f"Window: {window_note}. No out-of-sample metrics are reported when "
                "history is this thin."
            ),
        )

    test_years = years[burn_in:]
    errors: Dict[str, List[float]] = {m: [] for m in EVAL_METHODS}
    for t in test_years:
        prior = [y for y in years if y < t]
        actual = annual[t][0]
        errors["persistence"].append(abs(actual - annual[prior[-1]][0]))
        errors["expanding_median"].append(
            abs(actual - statistics.median([annual[y][0] for y in prior]))
        )
        recent = prior[-3:]
        errors["rolling_median_3"].append(
            abs(actual - statistics.median([annual[y][0] for y in recent]))
        )

    return GlsPriceForecastEvaluation(
        status="ok",
        window=window,
        test_periods=len(test_years),
        window_start=test_years[0],
        window_end=test_years[-1],
        train_years_before_first_test=burn_in,
        methods=[
            ForecastMethodResult(
                method=m,
                mae=round(statistics.mean(errs), 2),
                test_periods=len(test_years),
            )
            for m, errs in errors.items()
        ],
        note=(
            f"One-year-ahead chronological walk-forward over {window_note}: "
            f"every method predicts {test_years[0]}-{test_years[-1]} using only strictly "
            "earlier years. persistence = previous completed year's median; "
            "expanding_median = median of all earlier completed years; "
            "rolling_median_3 = median of the (up to) three most recent earlier "
            "completed years. All methods are scored on the same test years, and "
            "the incomplete current year is excluded."
        ),
    )


def _recent_walk_forward_evaluation(
    annual: Dict[int, Tuple[float, int]], recent_years: int = RECENT_EVAL_YEARS
) -> GlsPriceForecastEvaluation:
    """Same methodology restricted to the most recent ``recent_years``
    completed award years, so a recent-period MAE sits alongside the
    full-history MAE. All methods still use identical test periods."""
    years = sorted(annual)
    recent = {y: annual[y] for y in years[-recent_years:]}
    if recent:
        n = len(recent)
        window_note = (
            f"the {n} most recent completed award years "
            f"({years[-n]}-{years[-1]})"
        )
    else:
        window_note = "the most recent completed award years"
    return _walk_forward_evaluation(
        recent, window="recent_years", window_note=window_note
    )


def build_gls_price_forecast_section(
    snap: LandSnapshot, now: Optional[datetime] = None
) -> GlsPriceForecastSection:
    """Baseline estimate for the NEXT CALENDAR YEAR of the annual median
    successful tender price per GFA unit for awarded GLS sites in one
    verified category.

    Three years stay distinct: ``latest_award_year`` is the most recent
    COMPLETED award year and the persistence source; ``current_year_excluded``
    is the still-in-progress Asia/Singapore year, never used for training and
    never the forecast target; ``forecast_year`` is the calendar year after
    the in-progress one (next year). The estimate is the latest completed
    year's median. This is not an ML prediction; no evaluation output feeds
    the live forecast.
    """
    sec = GlsPriceForecastSection()
    records = snap.gls_sites or []
    now = now or datetime.now(SG_TZ)
    current_year = now.year
    sec.current_year_excluded = current_year
    sec.limitations.extend([
        "Prices are NOMINAL successful tender prices as published; no inflation "
        "adjustment is applied because no reliable local inflation series is "
        "available offline. Values from different years are not inflation-comparable.",
        "This is a persistence baseline (the next calendar year repeats the latest "
        "completed year's median), not an ML prediction, not a guaranteed price, "
        "and not a real-time market quote or government prediction.",
        "The estimate targets the next calendar year after the in-progress year; "
        f"the in-progress year {current_year} is never used as training data and is "
        "never presented as the forecast target.",
        "The estimate covers awarded GLS sites in the 'Residential (Non-Landed)' "
        "development category only; it does not represent all Singapore land prices.",
        "The source publishes GFA without a unit label (unlike SA_SQM, which names "
        "square metres), and no local documentation states GFA units; values are "
        "therefore reported as tender price per GFA unit without assuming an area unit.",
        "Annual medians built from very few sites are fragile; per-year site counts "
        "are retained so the UI can disclose the evidence behind each median.",
    ])

    by_year, counts = _eligible_price_forecast_records(records, current_year)
    sec.eligibility = counts
    if counts["sites_total"] == 0:
        sec.limitations.append(
            "URA Sale Sites layer unavailable; no baseline estimate can be produced."
        )
        sec.evaluation = _walk_forward_evaluation({})
        sec.evaluation_recent = _recent_walk_forward_evaluation({})
        return sec

    annual = _annual_medians(by_year)
    completed_years = sorted(annual)
    sec.annual_medians = [
        AnnualMedianRecord(
            award_year=y,
            median_price_per_gfa=annual[y][0],
            site_count=annual[y][1],
            low_sample=annual[y][1] < LOW_SAMPLE_SITE_THRESHOLD,
        )
        for y in completed_years
    ]

    # Both walk-forward windows are computed (or honestly refused) on every
    # path, so the evaluation never silently defaults.
    sec.evaluation = _walk_forward_evaluation(annual)
    sec.evaluation_recent = _recent_walk_forward_evaluation(annual)

    if len(completed_years) < MIN_COMPLETED_YEARS_FOR_FORECAST:
        sec.limitations.append(
            f"Insufficient history for a baseline estimate: {len(completed_years)} "
            f"completed award year(s) with eligible sites; at least "
            f"{MIN_COMPLETED_YEARS_FOR_FORECAST} required."
        )
        return sec

    latest = completed_years[-1]
    sec.latest_award_year = latest
    sec.latest_median_price_per_gfa = annual[latest][0]
    sec.latest_site_count = annual[latest][1]
    sec.latest_year_low_sample = annual[latest][1] < LOW_SAMPLE_SITE_THRESHOLD
    if sec.latest_year_low_sample:
        sec.warnings.append(
            f"The latest completed award year {latest} is based on only "
            f"{annual[latest][1]} eligible site(s); the baseline estimate is fragile."
        )
    # Forecast target: the next calendar year AFTER the in-progress year. The
    # current incomplete year is never the target and never training data, so
    # latest observed, current, and forecast years stay distinct (e.g. 2025 /
    # 2026 / 2027).
    sec.forecast_year = current_year + 1
    sec.forecast_value = annual[latest][0]
    sec.data_kind = "forecast"

    if counts["excluded_incomplete_or_future_year"]:
        sec.warnings.append(
            f"{counts['excluded_incomplete_or_future_year']} eligible site(s) awarded in "
            f"{current_year} or later were excluded: the year is still in progress."
        )
    return sec


# -------------------------------------------------------------- industrial
def build_industrial_section(snap: LandSnapshot, land_use: LandUseSection) -> IndustrialSection:
    sec = IndustrialSection()
    estates = snap.jtc_estates or []
    sec.limitations.append(
        "JTC estate boundaries are indicative estate extents published by JTC, "
        "not a complete register of industrial land in Singapore."
    )
    sec.limitations.append(sec.industrial_land_use_note)
    if estates:
        areas = [e["area_sqm"] for e in estates if e.get("area_sqm") is not None]
        sec.estate_count = len(estates)
        if areas:
            sec.total_estate_area_sqm = round(sum(areas), 1)
            sec.total_estate_area_km2 = round(sum(areas) / 1e6, 2)
        top = sorted([e for e in estates if e.get("area_sqm") is not None], key=lambda e: -e["area_sqm"])[:20]
        sec.largest_estates = [
            {
                "estate_name": e["estate_name"],
                "area_sqm": round(e["area_sqm"], 1),
                "area_km2": round(e["area_sqm"] / 1e6, 2),
                "updated": e.get("updated"),
            }
            for e in top
        ]
        dates = [e.get("updated") for e in estates if e.get("updated")]
        sec.source_data_date = max(dates) if dates else None
        sec.data_kind = "latest_available"

    ind_area = land_use.by_group.get("industrial") if land_use else None
    sec.industrial_land_use_area_sqm = ind_area
    if sec.estate_count is None and ind_area is not None:
        sec.data_kind = "partial"
    elif sec.estate_count is None:
        sec.data_kind = "unavailable"
    return sec


# ------------------------------------------------------------------ alerts
def build_alerts(
    land_use: LandUseSection,
    planning: PlanningSection,
    gls: GlsSection,
    industrial: IndustrialSection,
    snap: LandSnapshot,
) -> List[LandAlert]:
    """Data-quality / coverage alerts only.

    Land is a static planning dataset with no live operational feed, so this
    deliberately produces NO live-condition alerts. It reports coverage gaps and
    validation rejections instead of inventing urgency.
    """
    alerts: List[LandAlert] = []

    for key, rejected, inspected in [
        ("Master Plan 2025 land use", land_use.invalid_zones, land_use.zones_inspected),
        ("SLA cadastral land parcel", snap.cadastral_invalid, snap.cadastral_total_seen),
        ("Master Plan planning areas", planning.invalid_features, None),
        ("URA sale sites", gls.invalid_features, None),
    ]:
        if rejected:
            evidence = [f"{rejected} features rejected"]
            if inspected:
                evidence.append(f"{inspected} features inspected")
            evidence.append(f"rejection rate {_percent(rejected, inspected)}% of inspected features")
            alerts.append(
                LandAlert(
                    id=f"quality-{key.split()[-1]}",
                    severity="LOW",
                    category="data_quality",
                    message=f"{key}: {rejected} feature(s) rejected by geometry/attribute validation",
                    evidence=evidence,
                )
            )

    if snap.duplicate_lot_keys:
        alerts.append(
            LandAlert(
                id="quality-cadastral-duplicates",
                severity="LOW",
                category="data_quality",
                message=f"Cadastral: {snap.duplicate_lot_keys} duplicate LOT_KEY record(s) ignored",
                evidence=["first occurrence of each LOT_KEY retained"],
            )
        )

    for source in snap.sources:
        if source.status == "unavailable":
            alerts.append(
                LandAlert(
                    id=f"source-{source.key}",
                    severity="LOW",
                    category="source_availability",
                    message=f"{source.name} is unavailable; this part of the module is not represented",
                    evidence=[source.error or "no error detail recorded"],
                )
            )
    return alerts


# ------------------------------------------------- cross-domain land bridge
def housing_context(planning: PlanningSection) -> Dict[str, Any]:
    """Land-side context for Housing. Housing owns stock/supply; Land only
    reports how much land is zoned residential in the largest areas."""
    ranked = [p for p in planning.planning_areas if (p.group_area_sqm or {}).get("residential")]
    top = sorted(ranked, key=lambda p: -(p.group_area_sqm or {}).get("residential", 0.0))[:5]
    return {
        "residential_zoned_planning_areas": [
            {
                "planning_area": p.name,
                "residential_zoned_km2": round((p.group_area_sqm or {})["residential"] / 1e6, 2),
            }
            for p in top
        ],
        "note": (
            "Planned residential zoning only. Housing stock, HDB/private "
            "residential counts, vacancy and transactions are owned by the "
            "Housing module and are not duplicated here."
        ),
    }


def construction_context(gls: GlsSection) -> Dict[str, Any]:
    """Land-side context for Construction."""
    return {
        "gls_sites_recorded": gls.site_count,
        "gls_site_area_km2": (
            round(gls.total_site_area_sqm / 1e6, 2) if gls.total_site_area_sqm else None
        ),
        "note": (
            "Awarded Government Land Sales sites only. Construction projects, "
            "construction activity and the development pipeline are owned by "
            "the Construction module and are not duplicated here."
        ),
    }