"""Land agent, LandReport schema and FastAPI endpoints - all mocked."""
from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.planning.land import api as land_api
from backend.app.planning.land.agent import (
    STANDARD_QUESTIONS, agent_capabilities, create_land_agent, run_land_agent,
)
from backend.app.planning.land.models import LandReport
from backend.app.planning.land.sources import (
    LandDataClient, LandSnapshot, PlanningAreaIndex, SourceCache, fetch_land_snapshot,
    _dataset_id_for,
)
from land_fixtures import (
    cadastral_doc, docs_by_key, gls_doc, jtc_doc, land_use_doc, land_use_feature,
    planning_area_doc, poll_download_response, region_doc,
)
from test_land_sources import all_sources_handler, make_client

DOCS = docs_by_key()


def full_snapshot(client=None) -> LandSnapshot:
    c = client or make_client(all_sources_handler())
    return fetch_land_snapshot(c)


@pytest.fixture()
def report():
    return run_land_agent(fetcher=full_snapshot)


# ================================================================== agent
def test_graph_nodes_present():
    g = create_land_agent()
    assert {"ingest_land_data", "analyze_land", "build_report"} <= set(g.nodes)


def test_report_shape_and_honesty(report):
    assert isinstance(report, LandReport)
    assert report.domain == "planning" and report.subdomain == "land"
    assert report.is_ml_prediction is False
    assert report.source_status == "available"
    assert report.confidence == "high"
    assert len(report.sources) == 6
    assert all(s.crs.startswith("EPSG:4326") for s in report.sources)
    assert all(s.identifier.startswith("d_") for s in report.sources)


def test_report_uses_real_parsed_values(report):
    assert report.land_use.total_zones == 3
    assert report.planning.planning_area_count == 2
    assert report.planning.region_count == 1
    assert report.cadastral.parcel_count == 3
    assert report.gls.site_count == 2
    assert report.industrial.estate_count == 1


def test_report_json_safe(report):
    d = report.model_dump_json_safe()
    assert d["generated_at"] and d["source_status"] == "available"


def test_report_states_the_three_vocabulary_distinctions(report):
    joined = " ".join(report.limitations).lower()
    assert "cadastral parcel is not available land" in joined
    assert "not current physical land use" in joined
    assert "not all available land" in joined


def test_insights_answer_every_standard_question(report):
    assert len(report.insights) == len(STANDARD_QUESTIONS)
    for q in STANDARD_QUESTIONS:
        assert any(i.question == q for i in report.insights)


def test_insights_carry_data_kind(report):
    for i in report.insights:
        assert i.data_kind in {"live", "latest_available", "historical", "forecast", "unavailable"}
        assert i.answer.strip()


def test_agent_never_invents_zero_when_all_sources_fail():
    def dead():
        c = make_client(lambda r: httpx.Response(503), max_attempts=1)
        return fetch_land_snapshot(c)

    r = run_land_agent(fetcher=dead)
    assert r.source_status == "unavailable"
    assert r.confidence == "low"
    assert r.land_use.total_area_sqm is None
    assert r.cadastral.parcel_count is None
    assert r.gls.site_count is None
    assert r.planning.planning_area_count is None
    assert len(r.errors) == 6
    # insights must still exist but must say unavailable, not fabricate numbers
    assert all(i.data_kind == "unavailable" for i in r.insights if "unavailable" in i.answer.lower() or i.data_kind == "unavailable")


def test_agent_degrades_to_partial():
    def partial():
        c = make_client(all_sources_handler(fail_keys=("jtc_estates",)))
        return fetch_land_snapshot(c)

    r = run_land_agent(fetcher=partial)
    assert r.source_status == "partial"
    assert r.confidence == "medium"
    assert r.industrial.estate_count is None
    assert r.land_use.total_zones == 3  # unaffected source still present


def test_agent_capabilities_declares_no_ml():
    caps = agent_capabilities()
    assert caps["uses_ml"] is False
    assert len(caps["standard_questions"]) == len(STANDARD_QUESTIONS)


def test_no_live_condition_alerts_are_invented(report):
    for a in report.alerts:
        assert a.category in {"data_quality", "source_availability"}
        assert a.severity == "LOW"


# ================================================================== API
@pytest.fixture()
def client_and_report(report):
    app = FastAPI()
    app.include_router(land_api.router)
    land_api._REPORT_CACHE.update({"report": None, "expires_at": 0.0})
    with patch.object(land_api, "run_land_agent", return_value=report):
        yield TestClient(app)
    land_api._REPORT_CACHE.update({"report": None, "expires_at": 0.0})


def test_report_endpoint(client_and_report):
    c = client_and_report
    r = c.get("/api/planning/land/report")
    assert r.status_code == 200
    b = r.json()
    assert b["subdomain"] == "land" and b["source_status"] == "available"
    assert b["land_use"]["total_zones"] == 3


@pytest.mark.parametrize("path,key", [
    ("use", "land_use"),
    ("planning-areas", "planning"),
    ("gls", "gls"),
    ("industrial", "industrial"),
    ("sources", "sources"),
])
def test_section_endpoints(client_and_report, path, key):
    b = client_and_report.get(f"/api/planning/land/{path}").json()
    assert key in b
    assert b["generated_at"] and "data_timestamps" in b


def test_overview_endpoint(client_and_report):
    b = client_and_report.get("/api/planning/land/overview").json()
    h = b["headline"]
    assert b["source_status"] == "available"
    assert h["planning_area_count"] == 2 and h["region_count"] == 1
    assert h["cadastral_parcel_count"] == 3 and h["gls_site_count"] == 2
    assert h["dominant_category"]
    assert len(b["insights"]) == len(STANDARD_QUESTIONS)


def test_map_endpoint_serves_only_available_layers(client_and_report):
    b = client_and_report.get("/api/planning/land/map").json()
    ids = {layer["id"] for layer in b["layers"]}
    assert "planning_areas" in ids
    pa = next(l for l in b["layers"] if l["id"] == "planning_areas")
    assert pa["data"]["type"] == "FeatureCollection"
    for f in pa["data"]["features"]:
        assert f["geometry"]["type"] == "Polygon"
        assert len(f["geometry"]["coordinates"][0]) >= 4
    assert "cadastral" in b["layers_unavailable"]
    assert "145 MB" in b["layers_unavailable"]["cadastral"]


def test_endpoint_caching_and_refresh(client_and_report):
    c = client_and_report
    c.get("/api/planning/land/use")
    c.get("/api/planning/land/use")
    c.get("/api/planning/land/use?refresh=true")


def test_endpoint_returns_500_when_agent_crashes():
    app = FastAPI()
    app.include_router(land_api.router)
    land_api._REPORT_CACHE.update({"report": None, "expires_at": 0.0})
    with patch.object(land_api, "run_land_agent", side_effect=RuntimeError("boom")):
        r = TestClient(app).get("/api/planning/land/report")
    assert r.status_code == 500
    assert "land agent error" in r.json()["detail"]


def test_warmup_disabled_under_pytest_and_env(monkeypatch):
    import threading

    before = {t.name for t in threading.enumerate()}
    land_api.start_land_warmup()  # pytest in sys.modules -> no-op
    monkeypatch.setenv("URBANOS_LAND_WARMUP", "0")
    land_api.start_land_warmup()
    assert "land-warmup" not in {t.name for t in threading.enumerate()} - before


def test_routes_registered_on_real_app():
    from backend.app.main import app

    paths = set(app.openapi()["paths"])
    for p in ("report", "overview", "use", "planning-areas", "gls", "industrial", "map", "sources"):
        assert f"/api/planning/land/{p}" in paths, p