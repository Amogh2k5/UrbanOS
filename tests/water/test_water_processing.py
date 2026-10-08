"""Supply, usage, NEWater, quality, drain classification and forecast-eligibility logic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.infrastructure.water.models import DrainReading, DrainSensor
from backend.app.infrastructure.water.processing import (
    build_alerts, build_drain_section, build_forecast_section, build_newater_section,
    build_quality_section, build_supply_section, build_usage_section, cagr_pct,
    classify_drain_condition, compute_percentage, compute_trend, overall_from_drain, pct_change,
)
from backend.app.infrastructure.water.sources import (
    WaterSnapshot, parse_newater_annual, parse_potable_annual, parse_water_quality,
    parse_water_sales_annual,
)
from water_fixtures import newater_records, potable_records, quality_records, water_sales_records

SG = timezone(timedelta(hours=8))
T0 = datetime(2026, 9, 30, 12, 0, tzinfo=SG)


@pytest.fixture()
def snap():
    return WaterSnapshot(
        generated_at=T0,
        sales=parse_water_sales_annual(water_sales_records()),
        potable=parse_potable_annual(potable_records()),
        newater_long=parse_newater_annual(newater_records()),
        quality=parse_water_quality(quality_records()),
    )


# ------------------------------------------------------------------ maths
def test_pct_change_and_cagr_guards():
    assert pct_change(110, 100) == pytest.approx(10.0)
    assert pct_change(1, 0) is None and pct_change(None, 5) is None
    assert cagr_pct(100, 121, 2) == pytest.approx(10.0)
    assert cagr_pct(0, 10, 2) is None and cagr_pct(10, 10, 0) is None


# ------------------------------------------------------------------ usage
def test_usage_latest_change_and_split(snap):
    u = build_usage_section(snap)
    assert u.latest_year == 2025 and u.resolution == "annual"
    assert u.potable_total.value == 515.5 and u.potable_total.previous_value == 517.6
    assert u.potable_total.change_pct == pytest.approx(-0.41, abs=0.01)
    assert u.domestic.value == 304.4 and u.non_domestic.value == 211.1
    assert u.domestic_share_pct == 59.0 and u.non_domestic_share_pct == 41.0
    assert u.cagr_pct_since_2015 == pytest.approx(0.02, abs=0.01)
    assert not u.consistency_warnings            # 304.4 + 211.1 == 515.5
    # history merges the longer PUB dataset (2008+) with the 2015+ sales table
    dom = next(s for s in u.series if s.key == "domestic")
    assert dom.points[0].year == 2008 and dom.points[-1].year == 2025
    assert any("annual" in l.lower() for l in u.limitations)


def test_usage_detects_inconsistent_components(snap):
    snap.sales["domestic"][2025] = 350.0
    u = build_usage_section(snap)
    assert any("2025" in w for w in u.consistency_warnings)
    assert any(a.category == "data_quality" for a in build_alerts(u, build_newater_section(snap), build_quality_section(snap), build_drain_section([])))


def test_usage_unavailable_when_no_data():
    u = build_usage_section(WaterSnapshot(generated_at=T0))
    assert u.data_kind == "unavailable" and u.potable_total is None and u.series == []


def test_usage_derives_total_only_when_missing(snap):
    snap.sales["potable_total"][2025] = None
    u = build_usage_section(snap)
    assert u.potable_total.value == 515.5 and u.potable_total.period == "2025"


# --------------------------------------------------------------- forecast
def test_forecast_not_justified_for_annual_data(snap):
    f = build_forecast_section(build_usage_section(snap))
    assert f.available is False and f.data_kind == "unavailable"
    assert f.observations == 16            # fixture: 11 sales-table years (2015-2025) + 5 derived (2008-2012)
    assert f.minimum_observations_required > f.observations
    assert "annual" in f.reason and f.mae is None and f.rmse is None and f.model is None


# ---------------------------------------------------------------- newater
def test_newater_latest_history_and_share(snap):
    n = build_newater_section(snap)
    assert n.latest.value == 153.8 and n.latest.previous_value == 148.3
    assert n.latest.change_pct == pytest.approx(3.71, abs=0.01)
    pts = n.series[0].points
    assert pts[0].year == 2007 and pts[0].value == 49.15 and pts[-1].year == 2025
    assert n.share_of_water_sales_pct == pytest.approx(23.0, abs=0.1)
    assert any("industrial" in l for l in n.limitations)   # 2025 industrial is 'na'
    assert any("not live" in l.lower() for l in n.limitations)


def test_newater_overlap_prefers_recent_sales_table(snap):
    snap.newater_long[2016] = 999.0
    n = build_newater_section(snap)
    assert next(p for p in n.series[0].points if p.year == 2016).value == 126.9


# ------------------------------------------------------------------ supply
def test_supply_is_sales_only_and_never_claims_reservoir_data(snap):
    u, n = build_usage_section(snap), build_newater_section(snap)
    s = build_supply_section(snap, u, n)
    assert s.status == "SALES_DATA_ONLY" and s.reservoir_storage_available is False
    assert {i.key for i in s.indicators} == {"potable_total", "newater", "industrial"}
    industrial = next(i for i in s.indicators if i.key == "industrial")
    assert industrial.period == "2023"          # last year with a real value; 'na' after
    assert any("'na'" in l for l in s.limitations)
    assert s.data_kind == "latest_available" and s.period == "2025"


def test_supply_unavailable_without_data():
    empty = WaterSnapshot(generated_at=T0)
    s = build_supply_section(empty, build_usage_section(empty), build_newater_section(empty))
    assert s.status == "UNAVAILABLE" and s.data_kind == "unavailable" and s.indicators == []


# ----------------------------------------------------------------- quality
def test_quality_compliance_and_period(snap):
    q = build_quality_section(snap)
    assert q.reporting_period == "Calendar year 2025" and "annual" in q.frequency
    by = {p.key: p for p in q.parameters}
    assert [p.key for p in q.parameters][:3] == ["ecoli", "ph", "turbidity"]
    assert by["ph"].compliance == "WITHIN_LIMIT" and by["ph"].range_max == 8.9
    assert by["turbidity"].compliance == "WITHIN_LIMIT" and by["turbidity"].range_max == 0.48
    assert by["ecoli"].compliance == "WITHIN_LIMIT"
    assert by["conductivity"].compliance == "NO_LIMIT_PUBLISHED" and by["conductivity"].unit == "µS/cm"
    assert q.other_parameter_count == 1


def test_quality_flags_exceedances():
    recs = [
        {"year": "2025", "parameter": "pH Value", "units": "Units", "average": "9.0", "range": "8.0 - 9.9"},
        {"year": "2025", "parameter": "Turbidity", "units": "NTU", "average": "0.3", "range": "0.1 - 6.0"},
        {"year": "2025", "parameter": "Escherichia coli (E. coli)", "units": "cfu/100mL", "average": "2", "range": "0 - 5"},
    ]
    s = WaterSnapshot(generated_at=T0, quality=parse_water_quality(recs))
    q = build_quality_section(s)
    assert {p.key: p.compliance for p in q.parameters} == {"ecoli": "EXCEEDS_LIMIT", "ph": "EXCEEDS_LIMIT", "turbidity": "EXCEEDS_LIMIT"}
    alerts = build_alerts(build_usage_section(s), build_newater_section(s), q, build_drain_section([]))
    assert {a.id for a in alerts if a.category == "water_quality"} == {"quality-ecoli", "quality-ph", "quality-turbidity"}
    assert all(a.severity == "HIGH" for a in alerts if a.category == "water_quality")


def test_quality_unavailable():
    q = build_quality_section(WaterSnapshot(generated_at=T0))
    assert q.data_kind == "unavailable" and q.parameters == []


# -------------------------------------------------- drain classification
@pytest.mark.parametrize("pct,expected", [
    (0, "NORMAL"), (75, "NORMAL"), (75.01, "ELEVATED"), (90, "ELEVATED"),
    (90.01, "HIGH"), (100, "HIGH"), (100.01, "CRITICAL"), (180, "CRITICAL"),
    (None, "UNAVAILABLE"), (-1, "UNAVAILABLE"), (float("nan"), "UNAVAILABLE"),
])
def test_classify_drain_condition_bands(pct, expected):
    assert classify_drain_condition(pct) == expected


def test_compute_percentage_validation():
    assert compute_percentage(1.5, 3.0) == pytest.approx(50.0)
    assert compute_percentage(3.3, 3.0) == pytest.approx(110.0)       # above reference depth
    for bad in [(-0.1, 3.0), (1.0, 0.0), (1.0, -2.0), (None, 3.0), (1.0, None), (float("nan"), 3.0)]:
        assert compute_percentage(*bad) is None


def test_compute_trend():
    assert compute_trend([10, 30, 50]) == "rising"
    assert compute_trend([50, 30]) == "falling"
    assert compute_trend([40, 41, 41.5]) == "stable"
    assert compute_trend([40]) == "unknown"


SENSORS = [DrainSensor(id="a", name="A", latitude=1.3, longitude=103.8),
           DrainSensor(id="b", name="B", latitude=1.31, longitude=103.81),
           DrainSensor(id="c", name="C", latitude=1.32, longitude=103.82)]


def test_drain_without_readings_is_honest_about_unavailability():
    d = build_drain_section(SENSORS)
    assert d.readings_available is False and d.data_kind == "latest_available"
    assert d.sensor_count == 3 and d.sensors_with_readings == 0
    assert d.condition_counts == {"UNAVAILABLE": 3}
    assert all(s.condition == "UNAVAILABLE" and s.percentage is None for s in d.sensors)
    assert any("no official open feed" in l for l in d.limitations)
    assert overall_from_drain(d) == ("UNKNOWN", "UNKNOWN")         # never "normal" by default


def test_drain_no_sensors_no_readings():
    d = build_drain_section([])
    assert d.data_kind == "unavailable" and d.sensor_locations_available is False


def test_drain_with_injected_readings_classifies_and_trends():
    def r(sid, mins, lvl, ref=2.0):
        return DrainReading(sensor_id=sid, observed_at=T0 + timedelta(minutes=mins), water_level_m=lvl, reference_depth_m=ref)

    readings = [r("a", 0, 0.4), r("a", 5, 1.0), r("a", 10, 1.9),      # a: 95% rising -> HIGH
                r("b", 10, 0.5),                                      # b: 25% NORMAL
                r("c", 10, -1.0)]                                     # c: invalid -> unavailable
    d = build_drain_section(SENSORS, readings=readings)
    by = {s.sensor.id: s for s in d.sensors}
    assert by["a"].condition == "HIGH" and by["a"].percentage == 95.0 and by["a"].trend == "rising"
    assert by["b"].condition == "NORMAL" and by["b"].trend == "unknown"
    assert by["c"].condition == "UNAVAILABLE"
    assert d.readings_available and d.data_kind == "live" and d.sensors_with_readings == 2
    assert d.latest_reading_at == T0 + timedelta(minutes=10)
    assert overall_from_drain(d) == ("ELEVATED", "HIGH")
    alerts = build_alerts(build_usage_section(WaterSnapshot(generated_at=T0)), build_newater_section(WaterSnapshot(generated_at=T0)),
                          build_quality_section(WaterSnapshot(generated_at=T0)), d)
    assert [a.id for a in alerts] == ["drain-a"] and alerts[0].severity == "HIGH"


def test_overall_from_drain_critical():
    d = build_drain_section(SENSORS, readings=[DrainReading(sensor_id="a", observed_at=T0, water_level_m=2.5, reference_depth_m=2.0)])
    assert overall_from_drain(d) == ("CRITICAL", "CRITICAL")


# ------------------------------------------------------------------ alerts
def test_no_yoy_alert_for_small_changes_and_alert_for_large(snap):
    quiet = build_alerts(build_usage_section(snap), build_newater_section(snap), build_quality_section(snap), build_drain_section([]))
    assert quiet == []
    snap.sales["newater"][2025] = 180.0          # +21% vs 148.3
    loud = build_alerts(build_usage_section(snap), build_newater_section(snap), build_quality_section(snap), build_drain_section([]))
    assert [a.id for a in loud] == ["yoy-newater"] and loud[0].severity == "LOW"
    assert "not an official limit" in loud[0].evidence[1]
