"""Water agent, WaterReport, FastAPI endpoints and City Coordinator integration."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.infrastructure.water import api as water_api
from backend.app.infrastructure.water.agent import create_water_agent, run_water_agent
from backend.app.infrastructure.water.models import DrainReading, WaterReport
from backend.app.infrastructure.water.sources import (
    SourceCache, WaterDataClient, WaterSnapshot, fetch_water_snapshot,
)
from test_water_sources import _full_handler  # reuse the fully-mocked official sources

SG = timezone(timedelta(hours=8))


def full_snapshot() -> WaterSnapshot:
    client = WaterDataClient(transport=httpx.MockTransport(_full_handler), cache=SourceCache(), sleep=lambda s: None)
    return fetch_water_snapshot(client)


class FakeProvider:
    def __init__(self, readings=None, boom=False):
        self.readings, self.boom = readings or [], boom

    def fetch(self):
        if self.boom:
            raise RuntimeError("provider down")
        return self.readings


# ------------------------------------------------------------------- agent
def test_agent_full_report_shape_and_honesty():
    r = run_water_agent(fetcher=full_snapshot)
    assert isinstance(r, WaterReport) and r.domain == "infrastructure" and r.subdomain == "water"
    assert r.is_ml_prediction is False and r.forecast.available is False
    assert r.overall_status == "UNKNOWN" and r.overall_risk == "UNKNOWN"     # no live readings
    assert r.supply.status == "SALES_DATA_ONLY" and r.supply.reservoir_storage_available is False
    assert r.drain.sensor_count == 3 and r.drain.readings_available is False
    assert r.usage.potable_total.value == 515.5 and r.newater.latest.value == 153.8
    assert r.quality.reporting_period == "Calendar year 2025"
    assert r.confidence == "medium"                 # 5/5 sources ok but no live drain readings
    assert set(r.data_timestamps) == {"water_sales_annual", "potable_annual", "newater_annual", "drinking_quality", "drain_sensors"}
    assert r.data_timestamps["water_sales_annual"]["latest_data_period"] == "2025"
    assert r.errors == [] and r.alerts == []
    # JSON-safe for the coordinator / API
    assert r.model_dump_json_safe()["generated_at"]


def test_agent_answers_the_standard_questions_with_data_kinds():
    r = run_water_agent(fetcher=full_snapshot)
    by_q = {i.question: i for i in r.insights}
    assert len(by_q) == 7
    supply = by_q["What is the current/latest water supply status?"]
    assert "not published as open data" in supply.answer and "515.5" in supply.answer and supply.data_kind == "latest_available"
    assert by_q["Are any monitored drains showing elevated conditions?"].data_kind == "unavailable"
    assert "not evidence" in by_q["Are any monitored drains showing elevated conditions?"].answer
    usage = by_q["How is water usage changing?"]
    assert usage.data_kind == "historical" and "-0.4%" in usage.answer and "59.0%" in usage.answer
    assert by_q["What is the expected future water usage?"].answer.startswith("No forecast is produced.")
    assert "153.8" in by_q["What are the latest available water indicators?"].answer
    assert "+3.7%" in by_q["What has changed from the previous period?"].answer


def test_agent_with_live_readings_marks_data_live_and_high_confidence():
    t = datetime(2026, 9, 30, 12, tzinfo=SG)
    provider = FakeProvider([DrainReading(sensor_id="CWS186", observed_at=t, water_level_m=1.9, reference_depth_m=2.0)])
    r = run_water_agent(fetcher=full_snapshot, reading_provider=provider)
    assert r.drain.readings_available and r.drain.data_kind == "live"
    assert r.overall_status == "ELEVATED" and r.overall_risk == "HIGH" and r.confidence == "high"
    assert [a.category for a in r.alerts] == ["drain_condition"]
    q = {i.question: i for i in r.insights}["Are any monitored drains showing elevated conditions?"]
    assert q.data_kind == "live" and q.answer.startswith("Yes")


def test_agent_survives_provider_failure():
    r = run_water_agent(fetcher=full_snapshot, reading_provider=FakeProvider(boom=True))
    assert r.drain.readings_available is False
    assert any("provider failed" in e for e in r.errors)


def test_agent_with_all_sources_down_degrades_without_raising():
    def all_down(req):
        return httpx.Response(503)

    def fetcher():
        c = WaterDataClient(transport=httpx.MockTransport(all_down), cache=SourceCache(), sleep=lambda s: None, max_attempts=1)
        return fetch_water_snapshot(c)

    r = run_water_agent(fetcher=fetcher)
    assert r.confidence == "low" and len(r.errors) == 5
    assert r.supply.status == "UNAVAILABLE" and r.usage.data_kind == "unavailable"
    assert r.overall_risk == "UNKNOWN"
    assert {i.data_kind for i in r.insights} <= {"unavailable", "historical", "latest_available"}


def test_agent_graph_nodes():
    g = create_water_agent()
    assert {"ingest_water_data", "analyze_water", "build_report"} <= set(g.nodes)


# --------------------------------------------------------------------- API
@pytest.fixture()
def client():
    report = run_water_agent(fetcher=full_snapshot)
    app = FastAPI()
    app.include_router(water_api.router)
    with patch.object(water_api, "run_water_agent", return_value=report) as m:
        water_api._cache.update({"report": None, "expires_at": 0.0})
        yield TestClient(app), m
    water_api._cache.update({"report": None, "expires_at": 0.0})


@pytest.mark.parametrize("path,key", [
    ("supply", "supply"), ("drain", "drain"), ("usage", "usage"),
    ("forecast", "forecast"), ("newater", "newater"), ("quality", "quality"),
])
def test_section_endpoints(client, path, key):
    c, _ = client
    body = c.get(f"/api/water/{path}").json()
    assert key in body and body["data_timestamps"] and "generated_at" in body


def test_overview_endpoint(client):
    c, _ = client
    body = c.get("/api/water/overview").json()
    assert body["overall_risk"] == "UNKNOWN" and body["confidence"] == "medium"
    h = body["headline"]
    assert h["potable_total"]["value"] == 515.5 and h["newater"]["value"] == 153.8
    assert h["drain_readings_available"] is False and h["reservoir_storage_available"] is False and h["forecast_available"] is False
    assert len(body["insights"]) == 7 and body["limitations"]


def test_report_and_sources_endpoints(client):
    c, _ = client
    rep = c.get("/api/water/report").json()
    assert rep["subdomain"] == "water" and rep["forecast"]["available"] is False
    srcs = c.get("/api/water/sources").json()["sources"]
    assert {s["identifier"] for s in srcs} >= {"d_9db4902c7a47357441dac7d2806032a5", "d_31333fa5cf0834f012d840365b336610"}
    assert all(s["status"] == "ok" for s in srcs)


def test_map_endpoint_is_geojson_and_not_marked_live(client):
    c, _ = client
    body = c.get("/api/water/map").json()
    assert body["type"] == "FeatureCollection" and len(body["features"]) == 3
    f = body["features"][0]
    assert f["geometry"]["type"] == "Point" and f["geometry"]["coordinates"] == pytest.approx([103.798134, 1.33257], abs=1e-6)
    assert f["properties"]["id"] == "CWS186" and f["properties"]["name"].startswith("Eng Neo Ave")
    assert f["properties"]["condition"] == "UNAVAILABLE" and f["properties"]["percentage"] is None
    assert body["metadata"]["readings_available"] is False and body["metadata"]["data_kind"] == "latest_available"


def test_endpoint_caching_and_refresh(client):
    c, agent_mock = client
    c.get("/api/water/usage"); c.get("/api/water/supply")
    assert agent_mock.call_count == 1
    c.get("/api/water/usage?refresh=true")
    assert agent_mock.call_count == 2


def test_endpoint_returns_500_when_agent_crashes():
    app = FastAPI()
    app.include_router(water_api.router)
    water_api._cache.update({"report": None, "expires_at": 0.0})
    with patch.object(water_api, "run_water_agent", side_effect=RuntimeError("boom")):
        r = TestClient(app).get("/api/water/report")
    assert r.status_code == 500 and "water agent error" in r.json()["detail"]


def test_routes_registered_on_real_app():
    os.environ.setdefault("LTA_ACCOUNT_KEY", "dummy")
    from backend.app.main import app
    paths = set(app.openapi()["paths"])
    for p in ("overview", "supply", "drain", "usage", "forecast", "newater", "quality", "map", "report", "sources"):
        assert f"/api/water/{p}" in paths, p


# ---------------------------------------------------- City Coordinator
def _state_with_water(readings=None):
    from coordinator.city_agent import CityCoordinatorState
    st = CityCoordinatorState()
    st.water_report = run_water_agent(fetcher=full_snapshot, reading_provider=FakeProvider(readings) if readings else None)
    return st


def test_coordinator_collects_water_report_and_keeps_other_domains_untouched():
    from coordinator.city_agent import CityCoordinatorState, collect_reports
    report = run_water_agent(fetcher=full_snapshot)
    with patch("coordinator.city_agent.EnvironmentModule") as env, \
         patch("coordinator.city_agent.run_traffic_agent", side_effect=RuntimeError("t")), \
         patch("coordinator.city_agent.run_flood_agent_v3", side_effect=RuntimeError("f")), \
         patch("coordinator.city_agent.run_water_agent", return_value=report):
        env.return_value.run.side_effect = RuntimeError("e")
        st = collect_reports(CityCoordinatorState())
    assert st.water_report is report and st.source_reports["water"]["subdomain"] == "water"
    assert len(st.errors) == 3 and not any("Water" in e for e in st.errors)   # water never adds errors here


def test_coordinator_water_failure_is_a_warning_not_an_error():
    from coordinator.city_agent import CityCoordinatorState, collect_reports
    with patch("coordinator.city_agent.EnvironmentModule") as env, \
         patch("coordinator.city_agent.run_traffic_agent", side_effect=RuntimeError("t")), \
         patch("coordinator.city_agent.run_flood_agent_v3", side_effect=RuntimeError("f")), \
         patch("coordinator.city_agent.run_water_agent", side_effect=RuntimeError("w")):
        env.return_value.run.side_effect = RuntimeError("e")
        st = collect_reports(CityCoordinatorState())
    assert st.water_report is None and any("Water report unavailable" in w for w in st.warnings)


def test_coordinator_normalizes_water_without_inventing_risk():
    from coordinator.city_agent import normalize_state
    ds = normalize_state(_state_with_water()).domain_status["water"]
    assert ds["available"] is True and ds["overall_risk"] == "UNKNOWN" and ds["overall_status"] == "UNKNOWN"
    km = ds["key_metrics"]
    assert km["drain_readings_available"] is False and km["potable_sales_latest_mm3"] == 515.5
    assert km["reservoir_storage_available"] is False and km["forecast_available"] is False
    assert ds["is_ml_prediction"] is False and ds["limitations"]


def test_coordinator_normalizes_missing_water():
    from coordinator.city_agent import CityCoordinatorState, normalize_state
    ds = normalize_state(CityCoordinatorState()).domain_status["water"]
    assert ds["available"] is False and ds["error"]


def test_water_does_not_change_city_confidence_or_risk_when_unknown():
    """Adding a 4th domain must not flip the existing 3-domain confidence rule."""
    from coordinator.city_agent import CityCoordinatorState, prioritize_risks
    ok = {"available": True, "overall_risk": "LOW"}
    st = CityCoordinatorState(domain_status={
        "environment": dict(ok), "traffic": dict(ok), "flood": dict(ok),
        "water": {"available": True, "overall_risk": "UNKNOWN"},
    })
    out = prioritize_risks(st)
    assert out.confidence == "high" and out.overall_risk_level == "LOW" and out.overall_city_status == "NORMAL"


def test_real_drain_stress_with_flood_risk_creates_cross_domain_impact_and_recommendation():
    from coordinator.city_agent import analyze_cross_domain_impacts, generate_recommendations, normalize_state
    t = datetime(2026, 9, 30, 12, tzinfo=SG)
    st = normalize_state(_state_with_water([DrainReading(sensor_id="CWS186", observed_at=t, water_level_m=1.95, reference_depth_m=2.0)]))
    st.domain_status["flood"] = {"available": True, "overall_risk": "HIGH", "affected_zones": ["Central"], "active_alert_count": 2}
    st = analyze_cross_domain_impacts(st)
    impact = next(i for i in st.cross_domain_impacts if i["type"] == "drain_flood_context")
    assert impact["severity"] == "HIGH" and set(impact["domains_involved"]) == {"water", "flood"}
    st.overall_risk_level = "HIGH"
    st = generate_recommendations(st)
    assert any(r.startswith("WATER:") for r in st.city_level_recommendations)


def test_no_drain_flood_impact_without_real_readings():
    from coordinator.city_agent import analyze_cross_domain_impacts, normalize_state
    st = normalize_state(_state_with_water())
    st.domain_status["flood"] = {"available": True, "overall_risk": "HIGH", "affected_zones": ["Central"], "active_alert_count": 2}
    st = analyze_cross_domain_impacts(st)
    assert not [i for i in st.cross_domain_impacts if i["type"] == "drain_flood_context"]


def test_full_coordinator_graph_includes_water_in_final_report():
    from coordinator.city_agent import create_city_coordinator
    report = run_water_agent(fetcher=full_snapshot)
    with patch("coordinator.city_agent.EnvironmentModule") as env, \
         patch("coordinator.city_agent.run_traffic_agent", side_effect=RuntimeError("t")), \
         patch("coordinator.city_agent.run_flood_agent_v3", side_effect=RuntimeError("f")), \
         patch("coordinator.city_agent.run_water_agent", return_value=report):
        env.return_value.run.side_effect = RuntimeError("e")
        from coordinator.city_agent import CityCoordinatorState
        result = create_city_coordinator().invoke(CityCoordinatorState())
    final = result["report"]
    assert final.domain_status["water"].available is True
    assert final.domain_status["water"].key_metrics["potable_sales_latest_mm3"] == 515.5
    assert any(e["source"] == "water" for e in final.evidence)


# ------------------------------------------------------------------ warm-up
def test_warmup_is_disabled_under_pytest_and_by_env(monkeypatch):
    import threading

    before = {t.name for t in threading.enumerate()}
    water_api.start_water_warmup()                       # pytest is in sys.modules -> no-op
    monkeypatch.setenv("URBANOS_WATER_WARMUP", "0")
    water_api.start_water_warmup()
    assert "water-warmup" not in {t.name for t in threading.enumerate()} - before
