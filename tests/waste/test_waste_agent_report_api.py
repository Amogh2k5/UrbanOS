"""WasteManagementAgent, WasteReport, FastAPI endpoints and City Coordinator integration."""
from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.infrastructure.waste import api as waste_api
from backend.app.infrastructure.waste.agent import WasteManagementAgent, create_waste_agent, run_waste_agent
from backend.app.infrastructure.waste.models import WasteReport
from backend.app.infrastructure.waste.sources import SourceCache, WasteDataClient, WasteSnapshot, fetch_waste_snapshot
from test_waste_sources import _full_handler


def full_snapshot() -> WasteSnapshot:
    client = WasteDataClient(transport=httpx.MockTransport(_full_handler), cache=SourceCache(), sleep=lambda s: None)
    return fetch_waste_snapshot(client)


def down_snapshot() -> WasteSnapshot:
    client = WasteDataClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)), cache=SourceCache(), sleep=lambda s: None)
    return fetch_waste_snapshot(client)


# ------------------------------------------------------------------- agent
def test_agent_full_report_shape_and_honesty():
    r = WasteManagementAgent(fetcher=full_snapshot).run()
    assert isinstance(r, WasteReport) and r.domain == "infrastructure" and r.subdomain == "waste"
    assert r.status == "STATISTICS_AVAILABLE" and r.overall_risk == "UNKNOWN"        # never 'LOW'
    assert r.is_ml_prediction is False and r.forecast.available is False
    assert r.errors == [] and r.confidence == "high"
    assert set(r.data_timestamps) == {"waste_statistics", "general_collectors", "recycling_bins", "ewaste_points", "lighting_waste", "disposal_sites"}
    assert r.data_timestamps["waste_statistics"]["latest_data_period"] == "2025"
    assert r.data_timestamps["recycling_bins"]["data_kind"] == "reference"
    # nothing is presented as live
    assert "live" not in {r.generation.data_kind, r.categories.data_kind, r.food.data_kind, r.services.data_kind, r.infrastructure.data_kind}
    assert r.model_dump_json_safe()["generated_at"]


def test_report_kpis_and_sections():
    r = run_waste_agent(fetcher=full_snapshot)
    k = {i.key: i for i in r.kpis}
    assert list(k) == ["total_generated", "total_recycled", "total_disposed", "overall_recycling_rate", "recycling_rate_excl_cd", "food_waste_generated"]
    assert k["total_generated"].value == 7015000 and k["overall_recycling_rate"].value == 52.1
    assert r.generation.latest_year == 2025 and r.categories.rows and r.food.recycling_rate.value == 18
    assert r.services.licensee_count == 6 and {c.key: c.licensees for c in r.services.classes} == {"A": 4, "B": 1, "B.1": 1, "C": 1}
    assert r.infrastructure.total_locations == 10 and r.infrastructure.map_available
    assert {x.key for x in r.unavailable_metrics} >= {"domestic_vs_non_domestic", "bin_fill_levels"}
    assert r.alerts and all(a.severity in ("LOW", "MODERATE") for a in r.alerts)


def test_summary_is_assembled_only_from_report_numbers():
    r = run_waste_agent(fetcher=full_snapshot)
    assert r.summary.startswith("Singapore generated 7.02 million tonnes of waste in 2025")
    assert "3.66 million tonnes (52.1%) was recycled" in r.summary and "3.36 million tonnes was disposed of" in r.summary
    assert "not live measurements" in r.summary


def test_agent_answers_the_standard_questions_with_data_kinds():
    r = run_waste_agent(fetcher=full_snapshot)
    by_q = {i.question: i for i in r.insights}
    assert len(by_q) == 8
    assert "7.02 million tonnes" in by_q["What is the latest national waste picture?"].answer
    assert "+5.4% vs 2024" in by_q["How has waste generation changed?"].answer
    rec = by_q["How is recycling performing?"]
    assert "52.1%" in rec.answer and "42.8% excluding construction & demolition" in rec.answer
    assert "highest level in the series" in by_q["How much waste is disposed of?"].answer
    assert by_q["Which waste types make up most of what is disposed of?"].answer.startswith("In 2025: Plastics")
    assert by_q["What is the food-waste situation?"].data_kind == "historical"
    assert by_q["What waste services and infrastructure are on record?"].data_kind == "reference"
    lim = by_q["What cannot be assessed from the data?"]
    assert lim.data_kind == "unavailable" and "No forecast is produced" in lim.answer


def test_every_number_in_insights_traces_to_the_report():
    """The agent must not introduce statistics: every figure it states matches a value in the structured data."""
    import re
    r = run_waste_agent(fetcher=full_snapshot)

    values = set()

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, bool):
            return
        elif isinstance(o, (int, float)):
            values.add(float(o))
        elif isinstance(o, str):
            for m in re.findall(r"\d[\d,]*\.?\d*", o):
                try:
                    values.add(float(m.replace(",", "").rstrip(".")))
                except ValueError:
                    pass

    walk(r.model_dump(mode="json", exclude={"insights", "summary"}))
    checked = 0
    for ins in r.insights + [type("S", (), {"answer": r.summary, "question": "summary"})()]:
        text = ins.answer
        for m in re.finditer(r"(\d[\d,]*\.?\d*)( million tonnes)?", text):
            num = float(m.group(1).replace(",", "").rstrip("."))
            if m.group(2):     # 'N million tonnes' -> must equal some tonnes value to within rounding
                ok = any(abs(v / 1_000_000 - num) <= 0.0051 for v in values if v >= 10_000)
            else:
                ok = any(abs(v - num) <= 0.051 for v in values)
            assert ok, f"'{m.group(0)}' in {ins.question!r} is not traceable to the report"
            checked += 1
    assert checked > 30        # the guard really inspected the statements


def test_agent_with_all_sources_down_is_graceful_not_fabricated():
    r = run_waste_agent(fetcher=down_snapshot)
    assert r.status == "UNAVAILABLE" and r.overall_risk == "UNKNOWN" and r.confidence == "low"
    assert r.kpis == [] and r.categories.rows == [] and r.services.licensee_count is None
    assert r.infrastructure.total_locations == 0 and r.infrastructure.map_available is False
    assert len(r.errors) == 6 and r.summary == "Official waste statistics are currently unavailable."
    assert r.forecast.available is False
    by_q = {i.question: i for i in r.insights}
    assert by_q["What is the latest national waste picture?"].data_kind == "unavailable"
    assert any(a.id == "source_degraded" for a in r.alerts)


def test_agent_partial_failure_keeps_statistics():
    def handler(req):
        if req.url.host == "files.example":
            return httpx.Response(500)
        return _full_handler(req)
    snap = fetch_waste_snapshot(WasteDataClient(transport=httpx.MockTransport(handler), cache=SourceCache(), sleep=lambda s: None))
    r = run_waste_agent(fetcher=lambda: snap)
    assert r.status == "STATISTICS_AVAILABLE" and r.confidence == "medium"
    assert r.kpis and r.services.licensee_count == 6 and r.infrastructure.total_locations == 0
    assert len(r.errors) == 4 and r.infrastructure.data_kind == "unavailable"


def test_agent_fetcher_that_returns_nothing_still_builds_report():
    r = run_waste_agent(fetcher=lambda: WasteSnapshot(generated_at=datetime.now()))
    assert r.status == "UNAVAILABLE" and r.kpis == []


def test_graph_has_the_expected_nodes():
    g = create_waste_agent()
    assert {"ingest_waste_data", "analyze_waste", "build_report"} <= set(g.nodes)


# ------------------------------------------------------------------- API
@pytest.fixture()
def client(monkeypatch):
    snap = full_snapshot()
    monkeypatch.setattr(waste_api, "fetch_waste_snapshot", lambda **kw: snap)
    waste_api._cache.update(report=None, snapshot=None, expires_at=0.0)
    app = FastAPI()
    app.include_router(waste_api.router)
    yield TestClient(app)
    waste_api._cache.update(report=None, snapshot=None, expires_at=0.0)


def test_report_endpoint_returns_full_report(client):
    body = client.get("/api/waste/report").json()
    assert body["subdomain"] == "waste" and body["status"] == "STATISTICS_AVAILABLE" and body["overall_risk"] == "UNKNOWN"
    assert body["kpis"][0]["value"] == 7015000 and body["is_ml_prediction"] is False
    assert len(body["sources"]) == 6


def test_report_never_leaks_contact_details_or_map_points(client):
    raw = client.get("/api/waste/report").text
    assert "secret" not in raw and "@example.com" not in raw and "6000000" not in raw
    assert "coordinates" not in raw                                   # points live on /map only


def test_focused_endpoints(client):
    ov = client.get("/api/waste/overview").json()
    assert ov["status"] == "STATISTICS_AVAILABLE" and len(ov["kpis"]) == 6 and ov["summary"].startswith("Singapore generated")
    assert client.get("/api/waste/categories").json()["categories"]["rows"]
    assert client.get("/api/waste/food").json()["food"]["generated"]["value"] == 790000
    assert client.get("/api/waste/services").json()["services"]["licensee_count"] == 6
    srcs = client.get("/api/waste/sources").json()["sources"]
    assert {s["status"] for s in srcs} == {"ok"} and {s["data_kind"] for s in srcs} >= {"reference", "latest_available"}


def test_map_endpoint_geojson_and_kind_filter(client):
    m = client.get("/api/waste/map").json()
    assert m["type"] == "FeatureCollection" and len(m["features"]) == 10
    assert m["metadata"]["data_kind"] == "reference" and {k["key"] for k in m["metadata"]["kinds"]} == {"recycling_bins", "ewaste", "lighting_waste", "disposal_sites"}
    bins = [f for f in m["features"] if f["properties"]["kind"] == "recycling_bins"]
    assert len(bins) == 3 and set(bins[0]["properties"]) == {"kind", "name"}     # compact payload for bins
    ew = client.get("/api/waste/map", params={"kind": "ewaste"}).json()["features"]
    assert len(ew) == 2 and ew[0]["properties"]["address"] == "460 ALEXANDRA ROAD" and ew[0]["properties"]["record_date"] == "2022-06-02"
    lon, lat = ew[0]["geometry"]["coordinates"]
    assert 103.5 < lon < 104.2 and 1.1 < lat < 1.5
    assert client.get("/api/waste/map", params={"kind": "nope"}).status_code == 422


def test_map_empty_when_layers_unavailable(monkeypatch):
    snap = down_snapshot()
    monkeypatch.setattr(waste_api, "fetch_waste_snapshot", lambda **kw: snap)
    waste_api._cache.update(report=None, snapshot=None, expires_at=0.0)
    app = FastAPI(); app.include_router(waste_api.router)
    c = TestClient(app)
    m = c.get("/api/waste/map").json()
    assert m["features"] == [] and m["metadata"]["data_kind"] == "unavailable" and m["metadata"]["errors"]
    rep = c.get("/api/waste/report")
    assert rep.status_code == 200 and rep.json()["status"] == "UNAVAILABLE"        # unavailable != HTTP error
    waste_api._cache.update(report=None, snapshot=None, expires_at=0.0)


def test_report_is_cached_and_refresh_bypasses_cache(monkeypatch):
    calls = {"n": 0}
    snap = full_snapshot()

    def fetch(**kw):
        calls["n"] += 1
        return snap

    monkeypatch.setattr(waste_api, "fetch_waste_snapshot", fetch)
    waste_api._cache.update(report=None, snapshot=None, expires_at=0.0)
    app = FastAPI(); app.include_router(waste_api.router)
    c = TestClient(app)
    c.get("/api/waste/report"); c.get("/api/waste/overview")
    assert calls["n"] == 1
    c.get("/api/waste/report", params={"refresh": "true"})
    assert calls["n"] == 2
    waste_api._cache.update(report=None, snapshot=None, expires_at=0.0)


def test_errors_use_the_short_ttl(monkeypatch):
    snap = down_snapshot()
    monkeypatch.setattr(waste_api, "fetch_waste_snapshot", lambda **kw: snap)
    waste_api._cache.update(report=None, snapshot=None, expires_at=0.0)
    import time
    waste_api.get_waste_report(True)
    assert waste_api._cache["expires_at"] - time.time() <= waste_api._ERR_TTL_S + 1
    waste_api._cache.update(report=None, snapshot=None, expires_at=0.0)


def test_unexpected_agent_exception_becomes_500_with_message(monkeypatch):
    def boom(**kw):
        raise RuntimeError("kaput")
    monkeypatch.setattr(waste_api, "fetch_waste_snapshot", boom)
    waste_api._cache.update(report=None, snapshot=None, expires_at=0.0)
    app = FastAPI(); app.include_router(waste_api.router)
    r = TestClient(app).get("/api/waste/report")
    assert r.status_code == 500 and "waste agent error: kaput" in r.json()["detail"]


def test_routes_registered_on_real_app():
    import os
    os.environ.setdefault("LTA_ACCOUNT_KEY", "dummy")
    from backend.app.main import app
    paths = set(app.openapi()["paths"])
    for p in ("report", "overview", "categories", "food", "services", "sources", "map"):
        assert f"/api/waste/{p}" in paths
    assert "/api/water/report" in paths        # existing modules untouched


# ------------------------------------------------------------------- City Coordinator
def _collect(waste_fn):
    from unittest.mock import patch
    from coordinator.city_agent import CityCoordinatorState, collect_reports, normalize_state
    with patch("coordinator.city_agent.EnvironmentModule") as env, \
         patch("coordinator.city_agent.run_traffic_agent", side_effect=RuntimeError("t")), \
         patch("coordinator.city_agent.run_flood_agent_v3", side_effect=RuntimeError("f")), \
         patch("coordinator.city_agent.run_water_agent", side_effect=RuntimeError("w")), \
         patch("coordinator.city_agent.run_waste_agent", side_effect=waste_fn):
        env.return_value.run.side_effect = RuntimeError("e")
        st = collect_reports(CityCoordinatorState())
        return normalize_state(st)


def test_coordinator_collects_and_normalises_waste():
    st = _collect(lambda: run_waste_agent(fetcher=full_snapshot))
    ds = st.domain_status["waste"]
    assert ds["available"] is True and ds["overall_risk"] == "UNKNOWN" and ds["overall_status"] == "STATISTICS_AVAILABLE"
    km = ds["key_metrics"]
    assert km["waste_generated_tonnes"] == 7015000 and km["overall_recycling_rate_pct"] == 52.1 and km["statistics_year"] == "2025"
    assert km["licensed_collectors"] == 6 and km["infrastructure_locations"] == 10 and km["forecast_available"] is False
    assert st.source_reports["waste"]["subdomain"] == "waste"
    assert ds["is_ml_prediction"] is False and ds["affected_zones"] == []


def test_coordinator_survives_waste_failure():
    def boom():
        raise RuntimeError("down")
    st = _collect(boom)
    assert st.domain_status["waste"] == {"domain": "waste", "available": False, "error": "Waste report not available"}
    assert any("Waste report unavailable" in w for w in st.warnings)


def test_waste_does_not_change_city_risk_confidence_or_impacts():
    from coordinator.city_agent import CityCoordinatorState, analyze_cross_domain_impacts, prioritize_risks
    st = CityCoordinatorState()
    st.domain_status = {"waste": _collect(lambda: run_waste_agent(fetcher=full_snapshot)).domain_status["waste"]}
    st = prioritize_risks(analyze_cross_domain_impacts(st))
    assert st.overall_risk_level == "UNKNOWN" and st.overall_city_status == "UNKNOWN"
    assert st.cross_domain_impacts == [] and st.priority_incidents == []


def test_full_coordinator_report_contains_waste_domain():
    from unittest.mock import patch
    from coordinator.city_agent import run_city_coordinator
    with patch("coordinator.city_agent.EnvironmentModule") as env, \
         patch("coordinator.city_agent.run_traffic_agent", side_effect=RuntimeError("t")), \
         patch("coordinator.city_agent.run_flood_agent_v3", side_effect=RuntimeError("f")), \
         patch("coordinator.city_agent.run_water_agent", side_effect=RuntimeError("w")), \
         patch("coordinator.city_agent.run_waste_agent", side_effect=lambda: run_waste_agent(fetcher=full_snapshot)):
        env.return_value.run.side_effect = RuntimeError("e")
        rep = run_city_coordinator()
    assert rep.domain_status["waste"].key_metrics["waste_disposed_tonnes"] == 3358000
    assert any(e["source"] == "waste" for e in rep.evidence)
    assert rep.confidence == "low"        # waste is not a core domain: it does not lift confidence


# ------------------------------------------------------------------- layers still loading (rate-limited downloads)
def loading_snapshot() -> WasteSnapshot:
    snap = full_snapshot()
    snap.facilities.clear()
    for s in snap.sources:
        if s.key in ("recycling_bins", "ewaste_points", "lighting_waste", "disposal_sites"):
            s.status, s.record_count, s.latest_data_period, s.last_fetched_at = "loading", None, None, None
    for k in snap.facility_status:
        snap.facility_status[k] = "loading"
    return snap


def test_loading_layers_are_not_errors_alerts_or_failures():
    r = run_waste_agent(fetcher=loading_snapshot)
    assert r.status == "STATISTICS_AVAILABLE" and r.errors == [] and r.confidence == "medium"
    assert all(a.id != "source_degraded" for a in r.alerts)
    assert {k.status for k in r.infrastructure.kinds} == {"loading"} and r.infrastructure.total_locations == 0
    assert r.infrastructure.map_available is False
    assert any("Still downloading from data.gov.sg" in l and "DATA_GOV_SG_API_KEY" in l for l in r.infrastructure.limitations)
    assert all(k.note.startswith("Downloading") for k in r.infrastructure.kinds)
    q = {i.question: i for i in r.insights}["What waste services and infrastructure are on record?"]
    assert "Still downloading: recycling bins" in q.answer and "6 NEA-licensed" in q.answer


def test_api_rechecks_quickly_while_layers_load_and_map_reports_loading(monkeypatch):
    snap = loading_snapshot()
    monkeypatch.setattr(waste_api, "fetch_waste_snapshot", lambda **kw: snap)
    waste_api._cache.update(report=None, snapshot=None, expires_at=0.0)
    app = FastAPI(); app.include_router(waste_api.router); c = TestClient(app)
    import time
    m = c.get("/api/waste/map").json()
    assert m["features"] == [] and {k["status"] for k in m["metadata"]["kinds"]} == {"loading"}
    assert m["metadata"]["errors"] == []
    assert waste_api._cache["expires_at"] - time.time() <= waste_api._LOADING_TTL_S + 1
    assert c.get("/api/waste/report").json()["status"] == "STATISTICS_AVAILABLE"
    waste_api._cache.update(report=None, snapshot=None, expires_at=0.0)
