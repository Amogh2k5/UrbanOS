"""Deterministic Waste analytics, checked by hand against the real published figures."""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.app.infrastructure.waste import processing as P
from backend.app.infrastructure.waste.sources import WasteSnapshot, parse_waste_statistics
from waste_fixtures import mutate, waste_stat_records


@pytest.fixture()
def table():
    return parse_waste_statistics(waste_stat_records())


def kpi(kpis, key):
    return next(k for k in kpis if k.key == key)


# ------------------------------------------------------------------ period selection
def test_latest_complete_year(table):
    assert P.latest_complete_year(table) == 2025


def test_latest_year_skips_incomplete_year():
    recs = mutate(waste_stat_records(), "Total Disposed", 2, 2025, "na")
    t = parse_waste_statistics(recs)
    assert P.latest_complete_year(t) == 2024        # not 2025, and not a zero


# ------------------------------------------------------------------ KPIs
def test_kpis_use_exact_source_tonnes(table):
    k = P.build_kpis(table, 2025)
    assert kpi(k, "total_generated").value == 7015000 and kpi(k, "total_generated").unit == "tonnes"
    assert kpi(k, "total_recycled").value == 3657000
    assert kpi(k, "total_disposed").value == 3358000
    assert kpi(k, "food_waste_generated").value == 790000
    assert all(x.period == "2025" for x in k)


def test_yoy_change_uses_exactly_the_previous_year(table):
    g = kpi(P.build_kpis(table, 2025), "total_generated")
    assert g.previous_period == "2024" and g.previous_value == 6658000
    assert g.change_abs == 357000 and g.change_pct == 5.4                # (7015-6658)/6658


def test_previous_period_missing_gives_no_comparison_not_nearest_year():
    recs = mutate(waste_stat_records(), "Total Generated", 0, 2024, "na")
    t = parse_waste_statistics(recs)
    g = kpi(P.build_kpis(t, 2025), "total_generated")
    assert g.value == 7015000 and g.previous_value is None and g.change_pct is None and g.change_abs is None


def test_overall_rate_computed_from_tonnes_and_published_kept(table):
    r = kpi(P.build_kpis(table, 2025), "overall_recycling_rate")
    assert r.value == 52.1 and r.published_value == 52 and r.unit == "%"           # 3,657 / 7,015
    assert r.previous_value == 50.0 and r.change_abs == 2.1                          # 3,326 / 6,658 = 49.96
    assert r.change_pct is None                                                      # never a % change of a rate


def test_rate_excluding_cd_reproduces_the_nea_published_2023_figure(table):
    # NEA: "Excluding C&D waste, the overall recycling rate in 2023 was 45 per cent"
    assert P.rate_excluding_cd(table, 2023) == 45.2
    assert P.rate_excluding_cd(table, 2025) == 42.8
    assert P.rate_excluding_cd(table, 2024) == 44.0                                      # (3,326-706)/(6,658-708)
    assert kpi(P.build_kpis(table, 2025), "recycling_rate_excl_cd").change_abs == -1.2


def test_rate_excluding_cd_none_when_cd_missing():
    recs = mutate(waste_stat_records(), "Construction & Demolition", 1, 2025, "na")
    assert P.rate_excluding_cd(parse_waste_statistics(recs), 2025) is None


# ------------------------------------------------------------------ generation
def test_generation_section(table):
    g = P.build_generation_section(table, 2025)
    assert g.data_kind == "historical" and g.latest_year == 2025 and g.first_year == 2019
    assert [p.year for p in g.generated.points] == [2019, 2020, 2021, 2022, 2023, 2024, 2025]
    assert g.peak_generated_year == 2022 and g.peak_generated_tonnes == 7385000
    assert g.generated_change_since_peak_pct == -5.0
    assert g.peak_recycling_rate_year == 2019 and g.peak_recycling_rate_pct == 59
    assert g.disposed_is_series_high is True
    assert g.recycling_rate_computed.points[-1].value == 52.1


def test_generation_without_year_is_unavailable_not_zero():
    from backend.app.infrastructure.waste.sources import WasteTable
    g = P.build_generation_section(WasteTable(), None)
    assert g.data_kind == "unavailable" and g.generated is None and g.limitations


def test_missing_values_stay_none_in_series():
    t = parse_waste_statistics(mutate(waste_stat_records(), "Total Recycled", 1, 2021, "na"))
    pts = {p.year: p.value for p in P.build_generation_section(t, 2025).recycled.points}
    assert pts[2021] is None and pts[2020] == 3040000
    comp = {p.year: p.value for p in P.build_generation_section(t, 2025).recycling_rate_computed.points}
    assert comp[2021] is None


# ------------------------------------------------------------------ categories
def test_category_rows_sorted_and_shares(table):
    c = P.build_category_section(table, 2025)
    assert c.rows[0].key == "ferrous_metal" or c.rows[0].generated == max(r.generated for r in c.rows)
    gens = [r.generated for r in c.rows]
    assert gens == sorted(gens, reverse=True) and len(c.rows) == 14
    plastic = next(r for r in c.rows if r.key == "plastic")
    assert plastic.label == "Plastics" and plastic.generated == 890000 and plastic.disposed == 856000
    assert plastic.recycling_rate_computed == 3.8 and plastic.recycling_rate_published == 4
    assert plastic.share_of_generated_pct == 12.7 and plastic.share_of_disposed_pct == 25.5
    assert plastic.previous_generated == 918000 and plastic.generated_change_pct == -3.1
    assert c.top_disposed[:3] == ["plastic", "paper_cardboard", "food"]


def test_others_rate_na_is_none_published_but_computed_from_tonnes(table):
    c = P.build_category_section(table, 2025)
    o = next(r for r in c.rows if r.key == "others")
    assert o.recycling_rate_published is None and o.recycling_rate_computed == 1.1
    assert any("Others" in l and "'na'" in l for l in c.limitations)


def test_category_series_cover_all_blocks(table):
    c = P.build_category_section(table, 2025)
    food = next(s for s in c.series if s.key == "food")
    assert [p.value for p in food.recycling_rate.points] == [18, 19, 19, 18, 18, 18, 18]
    assert food.disposed.points[-1].value == 649000


# ------------------------------------------------------------------ food
def test_food_section(table):
    f = P.build_food_section(table, 2025)
    assert f.generated.value == 790000 and f.recycled.value == 140000 and f.disposed.value == 649000
    assert f.recycling_rate.value == 18 and f.recycling_rate.change_abs == 0
    assert f.share_of_total_generated_pct == 11.3 and f.share_of_total_disposed_pct == 19.3


def test_food_series_break_is_flagged_from_data():
    t = parse_waste_statistics(waste_stat_records(with_early_food=True))
    f = P.build_food_section(t, 2025)
    assert any("-51%" in l and "2000" in l and "2001" in l for l in f.limitations)
    # ...and not flagged when there is no break
    assert not any("series break" in l for l in P.build_food_section(parse_waste_statistics(waste_stat_records()), 2025).limitations)


# ------------------------------------------------------------------ data quality
def test_real_data_passes_every_consistency_check(table):
    dq = P.build_data_quality(table)
    failed = {c.key: c.failures for c in dq.checks if not c.passed}
    assert failed == {} and len(dq.checks) == 5
    assert all(c.checked == 7 for c in dq.checks)
    assert dq.missing_cells == 4 and dq.unparseable_cells == 0


def test_identity_failure_is_detected():
    t = parse_waste_statistics(mutate(waste_stat_records(), "Total Recycled", 1, 2025, 3000000))
    dq = P.build_data_quality(t)
    bad = next(c for c in dq.checks if c.key == "generated_equals_recycled_plus_disposed")
    assert not bad.passed and "2025" in bad.failures[0]


def test_category_sum_failure_is_detected():
    t = parse_waste_statistics(mutate(waste_stat_records(), "Plastic", 0, 2025, 1000000))
    bad = next(c for c in P.build_data_quality(t).checks if c.key == "categories_sum_to_total_generated")
    assert not bad.passed and "2025" in bad.failures[0]


def test_published_rate_mismatch_is_detected():
    t = parse_waste_statistics(mutate(waste_stat_records(), "Recycling Rate", 3, 2025, 80))
    bad = next(c for c in P.build_data_quality(t).checks if c.key == "published_rate_matches_computed")
    assert not bad.passed and "published 80%" in bad.failures[0]


def test_small_category_rounding_does_not_trip_the_rate_tolerance():
    # Scrap tyres 2025: 33,000 / 34,000 = 97.1% vs published 96% (source rounds tonnes to 1,000)
    assert P._rate_tolerance_pp(34000, 33000) > 1.1


def test_large_year_on_year_changes_listed(table):
    t = parse_waste_statistics(waste_stat_records(with_early_food=True))
    jumps = P.build_data_quality(t).large_year_on_year_changes
    assert any("Food generated 2000->2001: -51%" in j for j in jumps)
    assert any("Construction & Demolition generated 2024->2025: +62%" in j for j in jumps)


def test_empty_checks_do_not_pass_vacuously():
    from backend.app.infrastructure.waste.sources import WasteTable
    assert all(not c.passed for c in P.build_data_quality(WasteTable()).checks)


# ------------------------------------------------------------------ forecast
def test_forecast_is_never_available_for_annual_data(table):
    f = P.build_forecast_section(table)
    assert f.available is False and f.model is None and f.mae is None
    assert f.observations == 7 and f.minimum_observations_required == 48 and "annual" in f.reason
    assert P.build_forecast_section(None).observations == 0


# ------------------------------------------------------------------ alerts
def _alerts(table, snap=None):
    snap = snap or WasteSnapshot(generated_at=datetime.now())
    y = P.latest_complete_year(table)
    g, c, dq = P.build_generation_section(table, y), P.build_category_section(table, y), P.build_data_quality(table)
    return {a.id: a for a in P.build_alerts(snap, g, c, dq, datetime(2026, 10, 12))}


def test_alerts_from_real_data(table):
    a = _alerts(table)
    assert set(a) == {"disposed_series_high", "recycling_rate_below_peak", "large_streams_low_recycling"}
    assert a["recycling_rate_below_peak"].severity == "MODERATE"
    assert "7 percentage points below its peak" in a["recycling_rate_below_peak"].message
    msg = a["large_streams_low_recycling"].message
    assert "Plastics (3.8%)" in msg and "Food (17.7%)" in msg and "Paper/Cardboard (31%)" in msg
    assert "Wood" not in msg                                     # 428,000 t < 500,000 t threshold
    assert all(x.severity in ("LOW", "MODERATE") for x in a.values())   # statistics never raise HIGH


def test_data_consistency_alert_and_freshness_alert():
    t = parse_waste_statistics(mutate(waste_stat_records(), "Total Recycled", 1, 2025, 3000000))
    assert "data_consistency" in _alerts(t)
    from backend.app.infrastructure.waste.sources import SourceInfo
    t2 = parse_waste_statistics(waste_stat_records())
    y = P.latest_complete_year(t2)
    out = P.build_alerts(WasteSnapshot(generated_at=datetime.now()), P.build_generation_section(t2, y),
                         P.build_category_section(t2, y), P.build_data_quality(t2), datetime(2030, 1, 1))
    assert any(x.id == "statistics_out_of_date" for x in out)


def test_degraded_source_alert(table):
    from backend.app.infrastructure.waste.sources import _source
    s = _source("recycling_bins"); s.status = "unavailable"
    snap = WasteSnapshot(generated_at=datetime.now(), sources=[s])
    assert "source_degraded" in _alerts(table, snap)


# ------------------------------------------------------------------ unavailable metrics
def test_unavailable_metrics_are_declared():
    keys = {m.key for m in P.build_unavailable_metrics()}
    assert {"domestic_vs_non_domestic", "domestic_waste_per_capita", "landfill_capacity", "collection_activity", "bin_fill_levels", "forecast"} <= keys
    assert "disposal_sites" not in keys                       # a verified (reference) dataset exists


def test_rate_check_tolerates_the_real_2013_rounding_boundary_but_not_gross_mismatches():
    # Live data, 2013: published 62 % vs 61.5 % recomputed from tonnes rounded to 1,000 (gap ~0.51 pp)
    assert P._rate_tolerance_pp(7851000, 4827000) > abs(62 - 4827000 / 7851000 * 100)
    assert P._rate_tolerance_pp(7015000, 3657000) < 1.0              # still tight enough to catch 80 vs 52
