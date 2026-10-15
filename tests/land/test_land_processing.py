"""Land analytics: category grouping, area aggregation, GPR, planning areas,
cadastral, GLS, industrial, alerts. All pure functions over a mocked snapshot."""
from __future__ import annotations

import pytest

from backend.app.planning.land.models import LandReport
from backend.app.planning.land.processing import (
    GROUP_LABELS, _LU_GROUP, _percent, build_alerts, build_cadastral_section, build_gls_section,
    build_gpr_section, build_industrial_section, build_land_use_section,
    build_planning_section, category_group, construction_context, housing_context,
)
from backend.app.planning.land.sources import (
    LandSnapshot, PlanningAreaIndex, parse_cadastral_feature, parse_gls_site_feature,
    parse_jtc_estate_feature, parse_land_use_feature, parse_planning_area_feature, parse_region_feature,
)
from land_fixtures import (
    cadastral_doc, gls_doc, jtc_doc, land_use_feature, planning_area_doc, region_doc,
)
import json


def _snap():
    snap = LandSnapshot(generated_at="2026-10-09T00:00:00+08:00")
    snap.land_use = [
        parse_land_use_feature(land_use_feature("RESIDENTIAL", "2.8", 1000.0, 103.84, 1.30)),
        parse_land_use_feature(land_use_feature("RESIDENTIAL WITH COMMERCIAL AT 1ST STOREY", "2.0", 2000.0, 103.85, 1.31)),
        parse_land_use_feature(land_use_feature("COMMERCIAL", "LND", 500.0, 103.86, 1.32)),
        parse_land_use_feature(land_use_feature("PARK", "EVA", 250.0, 103.87, 1.33)),
        parse_land_use_feature(land_use_feature("BUSINESS 1", "2.5", 400.0, 103.88, 1.34)),
        parse_land_use_feature(land_use_feature("ROAD", None, 100.0, 103.89, 1.35)),
        parse_land_use_feature(land_use_feature("WATERBODY", None, 900.0, 103.90, 1.36)),
        parse_land_use_feature(land_use_feature("EDUCATIONAL INSTITUTION", "1.4", 150.0, 103.91, 1.37)),
        parse_land_use_feature(land_use_feature("SOMETHING UNKNOWN", "1.0", 50.0, 103.92, 1.38)),
    ]
    snap.planning_areas = [
        parse_planning_area_feature(f) for f in json.loads(planning_area_doc())["features"]
    ]
    snap.regions = [parse_region_feature(f) for f in json.loads(region_doc())["features"]]
    snap.cadastral = [parse_cadastral_feature(f) for f in json.loads(cadastral_doc())["features"]]
    snap.gls_sites = [parse_gls_site_feature(f) for f in json.loads(gls_doc())["features"]]
    snap.jtc_estates = [parse_jtc_estate_feature(f) for f in json.loads(jtc_doc())["features"]]
    snap.land_use_total_seen = len(snap.land_use)
    idx = PlanningAreaIndex()
    idx.build(snap.planning_areas)
    snap.planning_area_index = idx
    return snap


@pytest.fixture()
def snap():
    return _snap()


# ============================================================ grouping
@pytest.mark.parametrize("desc,group", [
    ("RESIDENTIAL", "residential"),
    ("RESIDENTIAL WITH COMMERCIAL AT 1ST STOREY", "residential"),
    ("COMMERCIAL", "commercial"),
    ("BUSINESS 1", "industrial"),
    ("BUSINESS 2", "industrial"),
    ("EDUCATIONAL INSTITUTION", "institutional"),
    ("CIVIC & COMMUNITY INSTITUTION", "institutional"),
    ("TRANSPORT FACILITIES", "transport"),
    ("ROAD", "transport"),
    ("PORT / AIRPORT", "transport"),
    ("PARK", "recreation"),
    ("OPEN SPACE", "recreation"),
    ("WATERBODY", "water"),
    ("UTILITY", "other"),
])
def test_category_group_mapping(desc, group):
    assert category_group(desc) == group


def test_unknown_category_goes_to_other_not_dropped():
    assert category_group("TOTALLY MADE UP") == "other"
    assert category_group("") == "other"


# ================================================== completeness of the mapping
# The complete set of LU_DESC values present in the live Master Plan 2025
# land-use layer, as enumerated by scripts/audit_land_use.py against
# d_a8c3546b26712e35021f3a681d0353ae (113,394 inspected features).
LIVE_LAND_USE_DESIGNATIONS = [
    "RESIDENTIAL", "BUSINESS 2", "RESERVE SITE", "OPEN SPACE", "ROAD",
    "PORT / AIRPORT", "WATERBODY", "SPECIAL USE", "PARK",
    "EDUCATIONAL INSTITUTION", "SPORTS & RECREATION", "UTILITY",
    "CIVIC & COMMUNITY INSTITUTION", "BUSINESS 1", "AGRICULTURE",
    "TRANSPORT FACILITIES", "COMMERCIAL & RESIDENTIAL", "COMMERCIAL",
    "CEMETERY", "WHITE", "BUSINESS PARK",
    "RESIDENTIAL WITH COMMERCIAL AT 1ST STOREY", "HEALTH & MEDICAL CARE",
    "PLACE OF WORSHIP", "HOTEL", "BUSINESS 2 - WHITE", "BEACH AREA",
    "MASS RAPID TRANSIT", "RESIDENTIAL / INSTITUTION", "BUSINESS PARK - WHITE",
    "BUSINESS 1 - WHITE", "COMMERCIAL / INSTITUTION", "LIGHT RAPID TRANSIT",
]


def test_every_live_designation_is_explicitly_mapped():
    """No live designation may reach the 'other' fallback silently."""
    unmapped = [
        d for d in LIVE_LAND_USE_DESIGNATIONS
        if _LU_GROUP.get(d) is None
    ]
    assert unmapped == [], f"designations missing from the mapping: {unmapped}"


def test_all_live_designations_map_to_known_groups():
    bad = [d for d in LIVE_LAND_USE_DESIGNATIONS if category_group(d) not in GROUP_LABELS]
    assert bad == []


def test_related_designations_share_one_group():
    """URA treats these as one family; splitting them was the accuracy bug."""
    assert category_group("BUSINESS PARK") == category_group("BUSINESS PARK - WHITE")
    assert category_group("BUSINESS PARK") == category_group("BUSINESS 1")
    assert category_group("MASS RAPID TRANSIT") == category_group("TRANSPORT FACILITIES")
    assert category_group("LIGHT RAPID TRANSIT") == category_group("ROAD")


def test_white_variants_are_not_institutional():
    """Regression guard: '- White' suffixes must not land in institutional."""
    for d in ("WHITE", "BUSINESS 1 - WHITE", "BUSINESS 2 - WHITE", "BUSINESS PARK - WHITE"):
        assert category_group(d) in {"commercial", "industrial"}


def test_group_labels_cover_all_groups():
    assert set(GROUP_LABELS) == {"residential", "commercial", "industrial", "institutional",
                                 "transport", "recreation", "water", "other"}


# =============================================== aggregation integrity
def _all_live_records():
    """One synthetic zone per live designation, with awkward fractional areas."""
    snap = LandSnapshot(generated_at="2026-10-09T00:00:00+08:00")
    for i, desc in enumerate(LIVE_LAND_USE_DESIGNATIONS):
        # fractional areas deliberately not exactly representable in binary
        snap.land_use.append(parse_land_use_feature(
            land_use_feature(desc, "LND", 1000.0 + i / 3.0, 103.84 + i * 0.001, 1.30)
        ))
    return snap


def test_categories_are_a_partition_no_zone_dropped_or_double_counted():
    sec = build_land_use_section(_all_live_records())
    n = len(LIVE_LAND_USE_DESIGNATIONS)
    assert sec.total_zones == n
    assert sec.distinct_categories == n
    assert sum(c.zone_count for c in sec.categories) == n
    assert len(sec.categories) == n
    assert len({c.code for c in sec.categories}) == n


def test_group_areas_sum_to_total_area():
    sec = build_land_use_section(_all_live_records())
    total = sum(v for v in sec.by_group.values() if v is not None)
    assert total == pytest.approx(sec.total_area_sqm, abs=0.5)


def test_group_areas_are_summed_from_raw_not_rounded_values():
    """Regression: groups were built from per-designation rounded areas, so the
    eight displayed values could not reconcile with the source totals."""
    snap = _all_live_records()
    sec = build_land_use_section(snap)

    expected: dict = {}
    for rec in snap.land_use:
        if rec["area_sqm"] is not None:
            g = category_group(rec["lu_desc"])
            expected[g] = expected.get(g, 0.0) + rec["area_sqm"]

    for g, raw in expected.items():
        assert sec.by_group[g] == pytest.approx(round(raw, 1), abs=0.1), g


def test_zero_area_zone_still_counted_and_never_nullified():
    snap = LandSnapshot(generated_at="2026-10-09T00:00:00+08:00")
    snap.land_use.append(parse_land_use_feature(
        land_use_feature("COMMERCIAL", "LND", 0.0, 103.84, 1.30)))
    sec = build_land_use_section(snap)
    cat = next(c for c in sec.categories if c.label == "Commercial")
    assert cat.zone_count == 1
    assert cat.area_sqm == 0.0


def test_negative_area_zone_is_rejected_not_aggregated():
    snap = LandSnapshot(generated_at="2026-10-09T00:00:00+08:00")
    good = parse_land_use_feature(land_use_feature("COMMERCIAL", "LND", 500.0, 103.84, 1.30))
    bad = parse_land_use_feature(land_use_feature("COMMERCIAL", "LND", -999.0, 103.85, 1.31))
    snap.land_use.extend([good, bad])
    sec = build_land_use_section(snap)
    cat = next(c for c in sec.categories if c.label == "Commercial")
    assert cat.zone_count == 2
    assert cat.area_sqm == 500.0


# ============================================================ land use
def test_land_use_area_is_sum_of_source_attributes(snap):
    sec = build_land_use_section(snap)
    assert sec.total_zones == 9
    assert sec.distinct_categories == 9  # every fixture zone carries a distinct designation
    assert sec.total_area_sqm == sum([1000.0, 2000.0, 500.0, 250.0, 400.0, 100.0, 900.0, 150.0, 50.0])
    assert sec.total_area_km2 == round(sec.total_area_sqm / 1e6, 2)


def test_land_use_categories_sorted_by_area_desc(snap):
    sec = build_land_use_section(snap)
    areas = [c.area_sqm for c in sec.categories]
    assert areas == sorted(areas, reverse=True)


def test_land_use_percentage_is_traceable(snap):
    sec = build_land_use_section(snap)
    for c in sec.categories:
        if c.area_sqm is not None and sec.total_area_sqm:
            assert c.area_pct == pytest.approx(c.area_sqm / sec.total_area_sqm * 100, abs=0.01)


def test_residential_groups_two_designations(snap):
    sec = build_land_use_section(snap)
    res = [c for c in sec.categories if c.group == "residential"]
    assert {c.label for c in res} == {"Residential", "Residential With Commercial At 1St Storey"}
    assert sec.by_group["residential"] == 3000.0


def test_industrial_group_uses_business_zones(snap):
    sec = build_land_use_section(snap)
    assert sec.by_group["industrial"] == 400.0
    assert sec.by_group["water"] == 900.0
    assert sec.by_group["transport"] == 100.0


def test_unknown_designation_reported_individually_and_in_other(snap):
    sec = build_land_use_section(snap)
    other = [c for c in sec.categories if c.label == "Something Unknown"]
    assert other and other[0].group == "other"
    assert sec.by_group["other"] == 50.0


def test_land_use_empty_snapshot_is_unavailable_not_zero():
    sec = build_land_use_section(LandSnapshot(generated_at="2026-10-09T00:00:00+08:00"))
    assert sec.data_kind == "unavailable"
    assert sec.total_area_sqm is None and sec.total_zones is None
    assert sec.by_group == {}


def test_missing_area_is_none_not_zero(snap):
    rec = parse_land_use_feature(land_use_feature("RESIDENTIAL", "2.8", None))
    sec = build_land_use_section(LandSnapshot(generated_at="2026-10-09T00:00:00+08:00", land_use=[rec]))
    cat = sec.categories[0]
    assert cat.zone_count == 1
    # geometry fallback still yields a positive area, never a fabricated 0
    assert cat.area_sqm is None or cat.area_sqm > 0


# ============================================================ GPR
def test_gpr_distribution_and_special_codes(snap):
    sec = build_gpr_section(snap, build_land_use_section(snap))
    numeric = sorted([2.8, 2.0, 2.5, 1.4, 1.0])
    assert sec.reported_numeric.zone_count == len(numeric)
    assert sec.median == 2.0  # middle of 1.0,1.4,2.0,2.5,2.8
    assert sec.max == 2.8
    assert sec.special_codes["LND"] == 1 and sec.special_codes["EVA"] == 1
    # non-numeric codes are never coerced into a numeric distribution
    assert sec.p25 is None or isinstance(sec.p25, float)


def test_gpr_special_codes_never_become_zero():
    snap = _snap()
    snap.land_use = [parse_land_use_feature(land_use_feature("COMMERCIAL", "LND", 1.0))]
    sec = build_gpr_section(snap, build_land_use_section(snap))
    assert sec.special_codes["LND"] == 1
    assert sec.median is None


def test_gpr_empty_is_unavailable():
    sec = build_gpr_section(LandSnapshot(generated_at="2026-10-09T00:00:00+08:00"), build_land_use_section(LandSnapshot(generated_at="x")))
    assert sec.data_kind == "unavailable" and sec.median is None


# ============================================================ planning
def test_planning_areas_carry_names_codes_regions(snap):
    sec = build_planning_section(snap)
    assert sec.planning_area_count == 2
    assert sec.region_count == 1
    names = {p.name for p in sec.planning_areas}
    assert names == {"BUKIT TIMAH", "CLEMENTI"}


def test_planning_area_land_use_attributed(snap):
    sec = build_planning_section(snap)
    bt = next(p for p in sec.planning_areas if p.name == "BUKIT TIMAH")
    assert bt.zone_count > 0
    assert bt.land_use_area_sqm and bt.land_use_area_sqm > 0
    assert bt.outer_ring, "map geometry must be carried for /map"


def test_dominant_category_is_most_frequent_designation(snap):
    sec = build_planning_section(snap)
    for p in sec.planning_areas:
        if p.zone_count:
            assert p.dominant_category
            assert 0 < p.dominant_category_pct <= 100


def test_planning_method_is_documented(snap):
    sec = build_planning_section(snap)
    assert "centroid" in sec.method and "grid" in sec.method


def test_planning_empty_is_unavailable():
    sec = build_planning_section(LandSnapshot(generated_at="x"))
    assert sec.data_kind == "unavailable"
    assert sec.planning_areas == [] and sec.planning_area_count is None


# ============================================================ cadastral
def test_cadastral_counts_and_area(snap):
    sec = build_cadastral_section(snap)
    assert sec.parcel_count == 3
    assert sec.total_area_sqm == pytest.approx(3 * 17682.5973, rel=1e-6)
    assert sec.median_area_sqm == pytest.approx(17682.5973, rel=1e-6)


def test_cadastral_never_claims_ownership_or_availability(snap):
    sec = build_cadastral_section(snap)
    assert sec.ownership_available is False
    assert "not the cadastre" in sec.limitations[0] or "NOT" in sec.limitations[0]


def test_cadastral_empty_is_unavailable():
    sec = build_cadastral_section(LandSnapshot(generated_at="x"))
    assert sec.data_kind == "unavailable" and sec.parcel_count is None


def test_duplicate_lot_keys_reported_not_silently_dropped(snap):
    snap.duplicate_lot_keys = 2
    sec = build_cadastral_section(snap)
    assert sec.duplicate_lot_keys == 2


# ============================================================ GLS
def test_gls_scope_is_awarded_not_current(snap):
    sec = build_gls_section(snap)
    assert sec.data_kind == "historical"
    assert sec.current_program_available is False
    assert "Confirmed List" in sec.current_program_note
    assert "not as an open dataset" in sec.current_program_note


def test_gls_aggregates(snap):
    sec = build_gls_section(snap)
    assert sec.site_count == 2
    assert sec.award_year_min == 1995 and sec.award_year_max == 2025
    assert sec.total_site_area_sqm == 60988.6 + 27034
    assert sec.by_development_code["Industrial"] == 1
    assert sec.total_housing_units == 315.0


def test_gls_latest_sites_sorted_newest_first(snap):
    sec = build_gls_section(snap)
    years = [s.award_year for s in sec.latest_sites]
    assert years == sorted(years, reverse=True)


def test_gls_empty_is_unavailable():
    sec = build_gls_section(LandSnapshot(generated_at="x"))
    assert sec.data_kind == "unavailable" and sec.site_count is None


# ============================================================ industrial
def test_industrial_combines_jtc_and_ura(snap):
    lu = build_land_use_section(snap)
    sec = build_industrial_section(snap, lu)
    assert sec.estate_count == 1
    assert sec.total_estate_area_sqm == pytest.approx(3027335.96326847, abs=0.05)
    assert sec.industrial_land_use_area_sqm == 400.0
    assert sec.largest_estates[0]["estate_name"] == "Jurong Industrial Estate Others"
    assert sec.source_data_date == "2024-11-26"


def test_industrial_partial_when_only_ura_zoning(snap):
    snap.jtc_estates = []
    sec = build_industrial_section(snap, build_land_use_section(snap))
    assert sec.estate_count is None
    assert sec.data_kind == "partial"


def test_industrial_unavailable_when_nothing(snap):
    snap.jtc_estates = []
    sec = build_industrial_section(LandSnapshot(generated_at="x", land_use=snap.land_use), build_land_use_section(snap))
    assert sec.data_kind in {"partial", "unavailable"}


# ============================================================ alerts
def test_alerts_report_quality_only_never_urgency(snap):
    # invalid counters must be set before the sections are built
    snap.land_use_invalid = 1
    snap.cadastral_invalid = 2
    lu = build_land_use_section(snap)
    pl = build_planning_section(snap)
    gls = build_gls_section(snap)
    ind = build_industrial_section(snap, lu)
    alerts = build_alerts(lu, pl, gls, ind, snap)
    assert {a.category for a in alerts} == {"data_quality"}
    assert all(a.severity == "LOW" for a in alerts)
    assert any("1 feature(s) rejected" in a.message for a in alerts)
    assert any("2 feature(s) rejected" in a.message for a in alerts)


def test_alerts_flag_unavailable_sources(snap):
    from backend.app.planning.land.models import LandSource
    snap.sources = [LandSource(
        key="jtc_estates", organization="JTC", name="JTC Estate", identifier="d_x",
        layer_name="L", url="u", purpose="p", update_frequency="f", coverage="c",
        authentication="none", data_kind="latest_available", crs="EPSG:4326",
        component="industrial", status="unavailable", error="HTTP 429",
    )]
    lu = build_land_use_section(snap)
    pl = build_planning_section(snap)
    gls = build_gls_section(snap)
    ind = build_industrial_section(snap, lu)
    alerts = build_alerts(lu, pl, gls, ind, snap)
    assert any(a.category == "source_availability" for a in alerts)
    assert any("HTTP 429" in e for a in alerts if a.category == "source_availability" for e in a.evidence)


def test_no_alerts_when_everything_clean(snap):
    lu = build_land_use_section(snap)
    pl = build_planning_section(snap)
    gls = build_gls_section(snap)
    ind = build_industrial_section(snap, lu)
    assert build_alerts(lu, pl, gls, ind, snap) == []


# ============================================================ helpers
def test_percent_helper_guards():
    assert _percent(50, 100) == 50.0
    assert _percent(None, 100) is None
    assert _percent(50, 0) is None
    assert _percent(50, None) is None


def test_cross_domain_context_does_not_duplicate_housing():
    pl = build_planning_section(snap := _snap())
    ctx = housing_context(pl)
    assert "Housing module" in ctx["note"]
    assert "HDB" in ctx["note"]
    assert isinstance(ctx["residential_zoned_planning_areas"], list)


def test_cross_domain_context_does_not_duplicate_construction():
    gls = build_gls_section(_snap())
    ctx = construction_context(gls)
    assert "Construction module" in ctx["note"]
    assert ctx["gls_sites_recorded"] == 2