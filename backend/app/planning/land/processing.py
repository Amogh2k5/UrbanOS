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

import statistics
from typing import Any, Dict, List, Optional, Tuple

from backend.app.planning.land.models import (
    CadastralSection, GprValue, GlsSection, GlsSite, GrossPlotRatioSection,
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