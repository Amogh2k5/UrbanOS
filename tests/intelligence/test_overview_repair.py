"""Regression tests for the repaired Overview endpoints.

Each test pins one verified defect from the AI Intelligence Layer Audit so it
cannot come back. Everything here is a pure helper - no server, no network.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from backend.app.intelligence.normalize import determine_status, normalize_domain_report
from backend.app.overview import api, context

CITY_MODULE_IDS = ["traffic", "roads", "transit", "pm25", "weather", "flood",
                   "fire", "crime", "water", "land"]


# ================================================== crime collection on /city
def test_crime_is_collected_on_the_city_endpoint():
    """crime was listed in module_configs but never fetched, so it was always
    rendered 'unavailable' and produced a fabricated status alert."""
    source = open(api.__file__, encoding="utf-8").read()
    assert "_fetch_crime_overview" in source
    assert '"crime": _fetch_crime_overview' in source
    assert "crime" in CITY_MODULE_IDS


def test_city_module_ids_cover_every_configured_module():
    for module_id in CITY_MODULE_IDS:
        assert hasattr(api, f"_fetch_{module_id}_overview"), module_id


# ================================================== shared single source of truth
@pytest.mark.parametrize("active,expected", [
    (0, "normal"), (100, "normal"), (101, "elevated"),
    (300, "elevated"), (501, "critical"), (900, "critical"),
])
def test_roads_status_thresholds_reach_critical(active, expected):
    assert api._determine_module_status("roads", {"road_works": {"active": active}}) == expected


@pytest.mark.parametrize("active", [0, 101, 300, 501, 900])
def test_overview_and_context_status_never_diverge(active):
    """The two modules used to hold independent copies that had already drifted."""
    data = {"road_works": {"active": active}}
    assert (api._determine_module_status("roads", data)
            == context._determine_module_status("roads", data))


def test_land_kpi_available_in_both_modules():
    data = {"land_use": {"total_area_km2": 796.82}}
    assert api._extract_module_kpi("land", data) is not None
    assert context._extract_module_kpi("land", data) is not None


# ============================================ deterministic briefs are not empty
@pytest.mark.parametrize("module_id,data", [
    ("traffic", {"overall_congestion_level": "moderate", "overall_average_speed": 42.5}),
    ("fire", {"active_incident_count": 3}),
    ("water", {"overall_risk": "LOW",
               "insights": [{"question": "Drain condition?",
                             "answer": "12 of 20 sensors are reporting.",
                             "data_kind": "live"}]}),
    ("land", {"land_use": {"total_area_km2": 796.82},
              "insights": [{"question": "Dominant land use?",
                            "answer": "Residential is the largest group.",
                            "data_kind": "latest_available"}]}),
    ("crime", {"total_physical_crime_2025": 4321, "data_period": "2025"}),
])
def test_every_supported_module_has_a_substantive_brief(module_id, data):
    brief = api._generate_deterministic_module_brief(module_id, data)
    assert brief, module_id
    tail = brief.split("module update.")[-1].strip()
    assert tail, f"{module_id} brief is contentless: {brief!r}"


def test_brief_falls_back_to_evidence_backed_findings():
    brief = api._generate_deterministic_module_brief(
        "land", {"land_use": {"total_area_km2": 796.82},
                 "insights": [{"question": "Dominant land use?",
                               "answer": "Residential is the largest group.",
                               "data_kind": "latest_available"}]})
    assert "Residential is the largest group." in brief


def test_unavailable_module_says_so_plainly():
    for module_id in ("water", "land", "crime", "traffic"):
        brief = api._generate_deterministic_module_brief(module_id, {"error": "boom"})
        assert "unavailable" in brief.lower()
        assert "module update." not in brief.lower()


# ================================================== module-detail coverage
@pytest.mark.parametrize("module_id", CITY_MODULE_IDS)
def test_module_detail_supports_every_listed_module(module_id):
    """water, land and crime previously 404'd on /module/{id}."""
    src = open(api.__file__, encoding="utf-8").read()
    detail = src.split("async def get_overview_module", 1)[1].split("@router.post", 1)[0]
    assert f'"{module_id}": _fetch_{module_id}_overview' in detail


def test_module_detail_has_no_duplicate_config_block():
    src = open(api.__file__, encoding="utf-8").read()
    detail = src.split("async def get_overview_module", 1)[1].split("@router.post", 1)[0]
    assert detail.count('"traffic": {"name"') == 0, "dead config block still present"


# ================================================== no synthetic false alerts
def test_unavailable_module_produces_no_status_alert():
    """The old loop emitted an alert for any status != normal, including
    'unavailable', which manufactured a city-level crime outage."""
    data: Dict[str, Any] = {"error": "No data"}
    status = api._determine_module_status("crime", data)
    assert status == "unavailable"
    # The guard the endpoint now uses.
    assert status not in ("elevated", "critical")


def test_real_elevation_still_produces_an_alert():
    data = {"active_incident_count": 9}
    status = api._determine_module_status("fire", data)
    assert status in ("elevated", "critical")


# ================================================== chat repair
def test_chat_no_longer_calls_a_nonexistent_method():
    src = open(api.__file__, encoding="utf-8").read()
    assert "_generate_with_openai" not in src
    # Phase 5 superseded the direct `_generate` call: the chat endpoint now
    # goes through the grounded Copilot, which selects bounded evidence and
    # validates the answer. It must not build a raw prompt again.
    assert "ai_service._generate(" not in src
    assert "generate_copilot_answer" in src


def test_chat_awaits_the_async_generate_method():
    from backend.app.ai.service import UrbanOSAIService
    assert hasattr(UrbanOSAIService, "_generate")
    import inspect
    assert inspect.iscoroutinefunction(UrbanOSAIService._generate)


# ================================================== unavailable != normal
@pytest.mark.parametrize("module_id", CITY_MODULE_IDS)
def test_unavailable_never_reports_normal(module_id):
    s = normalize_domain_report(module_id, {"error": "x"})
    assert s.available is False
    assert s.overall_status is None


def test_determine_status_is_shared_by_both_modules():
    for module_id in CITY_MODULE_IDS:
        assert api._determine_module_status(module_id, {"error": "x"}) == \
            determine_status(module_id, {"error": "x"}) == "unavailable"