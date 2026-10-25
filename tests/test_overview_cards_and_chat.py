"""Focused regression tests for the Overview card cache peeks and the chat
route's grounded, bounded single-domain answers.

The regression these pin:
  * /api/overview/city renders real metrics from warm module caches (traffic
    PredictionBundle, PM2.5 snapshot, water/roads TTL caches) without ever
    starting an agent or a coordinator run, and stays honestly unavailable
    for modules with no usable data;
  * /api/overview/chat answers a single-domain question (e.g. weather) from
    that domain's own bounded summary when the coordinator cache is cold -
    it must never run the ~74s coordinator (the old blocking wait is what
    made the frontend time out) and must answer within its budgets.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

import pytest

from backend.app.ai.narrative import NarrativeValidation
from backend.app.infrastructure.energy import api as energy_api
from backend.app.infrastructure.waste import api as waste_api
from backend.app.infrastructure.water import api as water_api
from backend.app.intelligence.contracts import DomainStatus
from backend.app.mobility.roads import aggregator as roads_aggregator
from backend.app.overview import api as overview_api
from backend.app.planning.construction import api as construction_api
from backend.app.planning.housing import api as housing_api


class _ImmediateSemaphore:
    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


async def _immediate_wait_for(awaitable, timeout):
    return await awaitable


async def _immediate_gather(*awaitables):
    return [await awaitable for awaitable in awaitables]


async def _inline_summary_get(_state, _module, loader, *, started=None, timeout_after_start=None):
    """The legacy coroutine-stepper has no running loop for task creation."""
    if started is not None:
        started.set()
    return await loader()


def _run_city_overview(request):
    coroutine = overview_api._city_overview_original(request)
    with patch.object(overview_api.asyncio, "Semaphore", _ImmediateSemaphore), \
         patch.object(overview_api.asyncio, "wait_for", _immediate_wait_for), \
         patch.object(overview_api.asyncio, "gather", _immediate_gather), \
         patch.object(overview_api._OVERVIEW_SUMMARY_CACHE, "get", _inline_summary_get):
        try:
            return coroutine.send(None)
        except StopIteration as completed:
            return completed.value


@pytest.fixture(autouse=True)
def _sync_direct_city_route_calls():
    overview_api._city_overview_original = overview_api.get_overview_city
    try:
        with patch.object(overview_api, "get_overview_city", _run_city_overview):
            yield
    finally:
        del overview_api._city_overview_original


@pytest.fixture(autouse=True)
def _clean_module_caches():
    """Isolate every module-global TTL cache between tests.

    A peek must never see a report another test cached: the card tests assert
    exact available/unavailable outcomes per module.
    """
    modules = (water_api, waste_api, energy_api, housing_api, construction_api)
    saved = {id(m): dict(m._cache) for m in modules}
    for m in modules:
        m._cache.update({k: None for k in m._cache})
        m._cache["expires_at"] = 0.0
        if "cached_at" in m._cache:
            m._cache["cached_at"] = 0.0
    roads_last, roads_at = roads_aggregator._last_good, roads_aggregator._last_good_at
    roads_aggregator._last_good, roads_aggregator._last_good_at = None, 0.0
    try:
        yield
    finally:
        for m in modules:
            m._cache.clear()
            m._cache.update(saved[id(m)])
        roads_aggregator._last_good, roads_aggregator._last_good_at = roads_last, roads_at


@pytest.fixture(autouse=True)
def _mock_cold_overview_fetchers(request):
    """Card/cache unit tests must not reach providers on cold cache misses."""
    if request.cls is None or request.cls.__name__ not in {
        "TestOverviewCardCachePeeks", "TestAllCanonicalModulesHaveCards",
        "TestNewModulePeeksPopulateCards", "TestPartialAndZeroMetrics",
    }:
        yield
        return

    async def unavailable(*_args, **_kwargs):
        return {"error": "mocked_unavailable"}

    with patch.multiple(overview_api, **{
        f"_fetch_{module}_overview": unavailable
        for module in overview_api.CANONICAL_MODULES
    }):
        yield


def _request(state: Optional[SimpleNamespace] = None) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=state or SimpleNamespace()))


def _traffic_bundle_service(speed: float = 80.0):
    """Stands in for the traffic prediction service: bundle already warm.

    ``start`` deliberately explodes: the Overview card must be a pure cache
    read and may never initialize the service.
    """
    link = SimpleNamespace(
        link_id="1", road_name="Road", road_category="1",
        zone_id="SG_NORTH", zone_name="North",
        current_speed=speed, predicted_speed=speed,
        speed_change=0.0,
        prediction_timestamp="2026-10-24T08:09:00+08:00",
        target_timestamp="2026-10-24T08:14:00+08:00",
    )
    bundle = SimpleNamespace(link_preds=[link], observed_at="2026-10-24T08:09:00+08:00")
    service = SimpleNamespace(
        bundle=bundle,
        start=lambda: (_ for _ in ()).throw(AssertionError("Overview must not start services")),
    )
    return service


def _pm25_service(value: float = 12.0):
    snapshot = MagicMock()
    snapshot.to_dict.return_value = {
        "regions": {"north": {"value": value, "observed_at": "2026-10-24T08:00:00+08:00"}},
        "timestamp": "2026-10-24T08:05:00+08:00",
    }
    return SimpleNamespace(snapshot=lambda: snapshot)


def _weather_summary(temp_c: float = 27.4) -> Dict[str, Any]:
    return {
        "general": {"temperature_c": temp_c, "forecast_code": "PS"},
        "timestamp": "2026-10-24T08:00:00+08:00",
    }


class _UnavailableAI:
    """AI service stub: no provider configured -> instant grounded fallback."""

    def is_available(self):
        return False

    async def generate_copilot_answer(self, ctx):
        return None, NarrativeValidation(ok=False, reasons=["ai unavailable"])


def _coordinator_report_with_weather() -> Any:
    from backend.app.intelligence.contracts import (
        CitySituationReport, DomainStatus, Finding,
    )

    return CitySituationReport(
        generated_at="2026-10-24T08:00:00+08:00",
        overall_city_status="NORMAL",
        overall_risk_level="LOW",
        confidence="medium",
        domain_status={
            "weather": DomainStatus(
                domain="weather",
                available=True,
                overall_status="NORMAL",
                key_metrics={"headline": {"label": "Temperature", "value": 30.1, "unit": "°C"}},
                findings=[
                    Finding(
                        id="weather.headline", domain="weather",
                        title="Temperature", answer="Current temperature: 30.1 °C.",
                        data_kind="live", evidence=["Temperature = 30.1 °C"],
                        metrics={"value": 30.1, "unit": "°C"},
                    ),
                ],
            ),
        },
    )


def _module_card(response, module_id: str):
    return next(m for m in response.modules if m.id == module_id)


# ======================================================================
# Overview cards
# ======================================================================

class TestOverviewCardCachePeeks:
    def test_failed_domain_fetches_report_all_modules_unavailable(self):
        with patch.object(overview_api, "peek_city_report_cached", return_value=None):
            response = overview_api.get_overview_city(_request())

        rendered = [m.id for m in response.modules]
        assert len(rendered) == 14, rendered
        assert all(m.status == "unavailable" and (m.kpi is None or m.kpi.value is None)
                   for m in response.modules)
        assert all(not s.available for s in response.domain_status.values())
        assert response.city_assessment_ready is False

    def test_traffic_card_reads_prediction_bundle_without_starting_it(self):
        state = SimpleNamespace(traffic_prediction_service=_traffic_bundle_service())
        with patch.object(overview_api, "peek_city_report_cached", return_value=None):
            response = overview_api.get_overview_city(_request(state))

        traffic = _module_card(response, "traffic")
        assert traffic.status == "normal"
        assert traffic.kpi is not None
        assert traffic.kpi.label == "Average Speed"
        assert traffic.kpi.value == 80.0
        # Other modules honestly unavailable.
        assert _module_card(response, "weather").status == "unavailable"
        assert _module_card(response, "transit").status == "unavailable"

    def test_traffic_card_unavailable_when_bundle_cold(self):
        state = SimpleNamespace(traffic_prediction_service=SimpleNamespace(bundle=None))
        with patch.object(overview_api, "peek_city_report_cached", return_value=None):
            response = overview_api.get_overview_city(_request(state))

        assert _module_card(response, "traffic").status == "unavailable"
        assert _module_card(response, "traffic").kpi is not None
        assert _module_card(response, "traffic").kpi.value is None

    def test_pm25_card_reads_live_snapshot_service(self):
        state = SimpleNamespace(pm25_live_service=_pm25_service(12.0))
        with patch.object(overview_api, "peek_city_report_cached", return_value=None):
            response = overview_api.get_overview_city(_request(state))

        pm25 = _module_card(response, "pm25")
        assert pm25.status == "normal"
        assert pm25.kpi is not None and pm25.kpi.value == 12.0
        assert pm25.kpi.unit == "µg/m³"

    def test_pm25_card_unavailable_when_snapshot_cold(self):
        state = SimpleNamespace(pm25_live_service=SimpleNamespace(snapshot=lambda: None))
        with patch.object(overview_api, "peek_city_report_cached", return_value=None):
            response = overview_api.get_overview_city(_request(state))

        assert _module_card(response, "pm25").status == "unavailable"

    def test_water_peek_serves_fresh_cache_only(self):
        sentinel = object()
        water_api._cache.update({"report": sentinel, "expires_at": time.time() + 600})
        assert water_api.peek_water_report() is sentinel

        water_api._cache.update({"expires_at": time.time() - 1})
        assert water_api.peek_water_report() is None

        water_api._cache.update({"report": None, "expires_at": time.time() + 600})
        assert water_api.peek_water_report() is None

    def test_water_card_reads_ttl_cache_without_running_agent(self):
        cached_report = MagicMock()
        cached_report.model_dump.return_value = {
            "overall_risk": "LOW",
            "usage": {"potable_total": {"value": 515.5, "unit": "million m³"}},
            "generated_at": "2026-10-24T08:00:00+08:00",
        }
        water_api._cache.update({"report": cached_report, "expires_at": time.time() + 600})
        with patch.object(overview_api, "peek_city_report_cached", return_value=None), \
             patch.object(water_api, "run_water_agent",
                          side_effect=AssertionError("agent must not run")):
            response = overview_api.get_overview_city(_request())

        water = _module_card(response, "water")
        assert water.status == "normal"
        assert water.kpi is not None and water.kpi.value == 515.5
        assert water.kpi.label == "Potable Sales"

    def test_roads_peek_serves_fresh_cache_only(self):
        payload = {"road_works": {"active": 3, "upcoming": 1}}
        roads_aggregator._last_good = payload
        roads_aggregator._last_good_at = time.time()
        snapshot = roads_aggregator.peek_roads_snapshot()
        assert snapshot is not None and snapshot["road_works"]["active"] == 3

        roads_aggregator._last_good_at = time.time() - roads_aggregator.ROADS_CACHE_TTL_S - 1
        assert roads_aggregator.peek_roads_snapshot() is None

        roads_aggregator._last_good, roads_aggregator._last_good_at = None, 0.0
        assert roads_aggregator.peek_roads_snapshot() is None

    def test_roads_card_reads_fresh_cache(self):
        roads_aggregator._last_good = {
            "road_works": {"active": 3, "upcoming": 1},
            "road_openings": {"total": 0},
            "taxi_stands": {"total": 0},
            "fetched_at": "2026-10-24T08:00:00+08:00",
            "source_status": "available",
        }
        roads_aggregator._last_good_at = time.time()
        with patch.object(overview_api, "peek_city_report_cached", return_value=None), \
             patch.object(roads_aggregator, "get_roads_snapshot",
                          side_effect=AssertionError("must not refresh")):
            response = overview_api.get_overview_city(_request())

        roads = _module_card(response, "roads")
        assert roads.status == "normal"
        assert roads.kpi is not None and roads.kpi.label == "Active Road Works"
        assert roads.kpi.value == 3

    def test_coordinator_cache_takes_priority_over_module_peeks(self):
        """A warm coordinator report is authoritative for every module it has."""
        report = _coordinator_report_with_weather()
        state = SimpleNamespace(
            traffic_prediction_service=_traffic_bundle_service(),
            pm25_live_service=_pm25_service(12.0),
        )
        with patch.object(overview_api, "peek_city_report_cached",
                          return_value=(report, {})):
            response = overview_api.get_overview_city(_request(state))

        weather = _module_card(response, "weather")
        assert weather.status == "normal"
        assert weather.kpi is not None and weather.kpi.value == 30.1
        # Module peeks still serve the modules the coordinator did not.
        assert _module_card(response, "traffic").kpi is not None
        assert _module_card(response, "pm25").kpi is not None
        # And nothing else was invented.
        assert _module_card(response, "flood").status == "unavailable"

    def test_peek_failure_degrades_to_unavailable(self):
        state = SimpleNamespace(
            traffic_prediction_service=SimpleNamespace(
                bundle=property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
            ),
        )
        with patch.object(overview_api, "peek_city_report_cached", return_value=None):
            response = overview_api.get_overview_city(_request(state))

        assert _module_card(response, "traffic").status == "unavailable"


# ======================================================================
# Chat route
# ======================================================================

class TestChatSingleDomainGrounding:
    @pytest.mark.asyncio
    async def test_weather_question_answers_from_domain_summary(self):
        """Cold coordinator cache: a weather question is grounded in the
        Weather summary via the module's existing fetcher - no coordinator."""
        from contextlib import ExitStack

        from backend.app.overview.api import ChatRequest, chat

        spies = {
            name: AsyncMock(return_value={"error": f"{name} spy unavailable"})
            for name in ("traffic", "roads", "transit", "pm25", "flood",
                         "fire", "crime", "water", "land")
        }
        weather_spy = AsyncMock(return_value=_weather_summary(27.4))
        forbidden_run = MagicMock(side_effect=AssertionError("coordinator started"))

        # ExitStack guarantees every patch is undone (patch.start() returns
        # the mock, not the patcher, so collecting its result cannot be
        # stopped later - that leak is exactly what this test must avoid).
        with ExitStack() as stack:
            for name, spy in spies.items():
                stack.enter_context(
                    patch.object(overview_api, f"_fetch_{name}_overview", spy))
            stack.enter_context(
                patch.object(overview_api, "peek_city_report_cached", return_value=None))
            stack.enter_context(
                patch.object(overview_api, "get_ai_service", return_value=_UnavailableAI()))
            stack.enter_context(
                patch.object(overview_api, "city_report_cached", forbidden_run))
            stack.enter_context(
                patch.object(overview_api, "_fetch_weather_overview", weather_spy))

            resp = await chat(
                _request(),
                ChatRequest(message="tell about weather conditions"),
            )

        weather_spy.assert_awaited_once()
        for name, spy in spies.items():
            assert spy.await_count == 0, f"{name} fetcher must not run"
        forbidden_run.assert_not_called()
        assert "27.4" in resp.response
        assert "temperature" in resp.response.lower()
        assert "timed out" not in resp.response.lower()

    @pytest.mark.asyncio
    async def test_ambiguous_question_with_cold_cache_answers_honestly(self):
        from backend.app.overview.api import ChatRequest, chat

        forbidden_fetch = AsyncMock(
            side_effect=AssertionError("no domain fetch for an ambiguous question"))
        forbidden_run = MagicMock(side_effect=AssertionError("coordinator started"))

        with patch.object(overview_api, "peek_city_report_cached", return_value=None), \
             patch.object(overview_api, "get_ai_service", return_value=_UnavailableAI()), \
             patch.object(overview_api, "city_report_cached", forbidden_run), \
             patch.object(overview_api, "_module_fetcher_map",
                          return_value={name: forbidden_fetch for name in overview_api._CHAT_MODULE_IDS}):
            resp = await chat(
                _request(),
                ChatRequest(message="what is the overall situation"),
            )

        forbidden_fetch.assert_not_called()
        forbidden_run.assert_not_called()
        assert "cannot answer" in resp.response.lower()
        assert "unavailable" in resp.response.lower()

    @pytest.mark.asyncio
    async def test_module_id_routes_the_domain_fetch(self):
        from backend.app.overview.api import ChatRequest, chat

        weather_spy = AsyncMock(return_value=_weather_summary(29.9))

        with patch.object(overview_api, "peek_city_report_cached", return_value=None), \
             patch.object(overview_api, "get_ai_service", return_value=_UnavailableAI()), \
             patch.object(overview_api, "_fetch_weather_overview", weather_spy):
            resp = await chat(
                _request(),
                ChatRequest(message="what is happening", module_id="weather"),
            )

        weather_spy.assert_awaited_once()
        assert "29.9" in resp.response

    @pytest.mark.asyncio
    async def test_domain_fetch_timeout_is_bounded(self, monkeypatch):
        """A hung domain fetch must not hang the chat: the budget converts
        it into an honest unavailable answer."""
        import asyncio as _asyncio

        from backend.app.overview.api import ChatRequest, chat

        monkeypatch.setattr(overview_api, "_CHAT_DOMAIN_FETCH_BUDGET_S", 0.2)

        async def _slow_fetch(app_state):
            await _asyncio.sleep(5)
            return {}

        with patch.object(overview_api, "peek_city_report_cached", return_value=None), \
             patch.object(overview_api, "_fetch_weather_overview", _slow_fetch):
            started = time.time()
            resp = await chat(
                _request(),
                ChatRequest(message="tell about weather conditions"),
            )

        assert time.time() - started < 4.0, "chat must return within its fetch budget"
        assert "cannot answer" in resp.response.lower()

    @pytest.mark.asyncio
    async def test_warm_coordinator_cache_is_preferred_and_no_fetch_runs(self):
        from backend.app.overview.api import ChatRequest, chat

        report = _coordinator_report_with_weather()
        weather_spy = AsyncMock(
            side_effect=AssertionError("domain fetch must not run when cache is warm"))
        forbidden_run = MagicMock(side_effect=AssertionError("coordinator started"))

        with patch.object(overview_api, "peek_city_report_cached",
                          return_value=(report, {})), \
             patch.object(overview_api, "get_ai_service", return_value=_UnavailableAI()), \
             patch.object(overview_api, "city_report_cached", forbidden_run), \
             patch.object(overview_api, "_fetch_weather_overview", weather_spy):
            resp = await chat(
                _request(),
                ChatRequest(message="tell about weather conditions"),
            )

        weather_spy.assert_not_called()
        forbidden_run.assert_not_called()
        # The coordinator's own weather evidence answers the question.
        assert "30.1" in resp.response

    @pytest.mark.asyncio
    async def test_unavailable_domain_data_is_never_invented(self):
        from backend.app.overview.api import ChatRequest, chat

        weather_spy = AsyncMock(return_value={"error": "rate_limited"})

        with patch.object(overview_api, "peek_city_report_cached", return_value=None), \
             patch.object(overview_api, "get_ai_service", return_value=_UnavailableAI()), \
             patch.object(overview_api, "_fetch_weather_overview", weather_spy):
            resp = await chat(
                _request(),
                ChatRequest(message="tell about weather conditions"),
            )

        assert "cannot answer" in resp.response.lower()
        # No temperature was fabricated for unavailable data.
        assert "27" not in resp.response and "°C" not in resp.response


# ======================================================================
# Missing module cards (all 14 canonical modules must render)
# ======================================================================

def _stub_report(payload: Dict[str, Any]):
    """A report stand-in: model_dump() returns exactly the given payload."""
    stub = MagicMock()
    stub.model_dump.return_value = payload
    return stub


class TestAllCanonicalModulesHaveCards:
    def _response(self):
        with patch.object(overview_api, "peek_city_report_cached", return_value=None):
            return overview_api.get_overview_city(_request())

    def test_every_canonical_module_renders_a_card_when_cold(self):
        from backend.app.intelligence.normalize import CANONICAL_MODULES

        response = self._response()
        rendered = {m.id for m in response.modules}

        assert rendered == set(CANONICAL_MODULES)
        assert len(response.modules) == 14

    def test_legacy_environment_alias_never_duplicates_pm25_or_weather(self):
        """The coordinator owns an `environment` umbrella over pm25+weather;
        it must never appear as its own card next to them."""
        response = self._response()
        rendered = [m.id for m in response.modules]

        assert "environment" not in rendered
        assert "pm25" in rendered and "weather" in rendered

    def test_cold_cards_are_honestly_unavailable_not_missing(self):
        response = self._response()
        for module in response.modules:
            assert module.status == "unavailable"
            assert module.kpi is None or module.kpi.value is None
            # A cold module has no metric values - and never invented ones.
            assert all(m.value is None for m in module.metrics)

    def test_names_and_routes_cover_all_canonical_modules(self):
        from backend.app.intelligence.normalize import (
            CANONICAL_MODULES, DOMAIN_NAMES, DOMAIN_ROUTES,
        )
        for module_id in CANONICAL_MODULES:
            assert module_id in DOMAIN_NAMES, module_id
            assert module_id in DOMAIN_ROUTES, module_id

        response = self._response()
        by_id = {m.id: m for m in response.modules}
        for module_id in CANONICAL_MODULES:
            assert by_id[module_id].name == DOMAIN_NAMES[module_id]
            assert by_id[module_id].detail_route == DOMAIN_ROUTES[module_id]


class TestNewModulePeeksPopulateCards:
    """waste / energy / housing / construction read their warm TTL caches."""

    def test_waste_card_reads_ttl_cache_with_kpis_list(self):
        waste_api._cache.update({
            "report": _stub_report({
                "status": "STATISTICS_AVAILABLE",
                "overall_risk": "UNKNOWN",
                "kpis": [
                    {"key": "total_generated", "label": "Total Waste Generated",
                     "value": 7_000_000, "unit": "tonnes"},
                    {"key": "total_recycled", "label": "Total Recycled",
                     "value": 3_500_000, "unit": "tonnes"},
                    {"key": "overall_recycling_rate", "label": "Overall Recycling Rate",
                     "value": 50.0, "unit": "%"},
                ],
                "generated_at": "2026-10-24T08:00:00+08:00",
            }),
            "expires_at": time.time() + 600,
        })
        with patch.object(overview_api, "peek_city_report_cached", return_value=None), \
             patch.object(waste_api, "run_waste_agent",
                          side_effect=AssertionError("agent must not run")):
            response = overview_api.get_overview_city(_request())

        card = _module_card(response, "waste")
        assert card.status == "normal"
        assert card.kpi is not None and card.kpi.value == 7_000_000
        metrics = {m.key: m for m in card.metrics}
        assert metrics["generated"].value == 7_000_000
        assert metrics["recycled"].value == 3_500_000
        assert metrics["recycling_rate"].value == 50.0

    def test_energy_card_reads_ttl_cache(self):
        energy_api._cache.update({
            "report": _stub_report({
                "status": "OK",
                "key_metrics": {
                    "latest_peak_demand_mw": 7200.0,
                    "max_peak_demand_mw": 7500.0,
                    "latest_solar_capacity_mwp": 500.0,
                },
                "generated_at": "2026-10-24T08:00:00+08:00",
            }),
            "expires_at": time.time() + 1800,
        })
        with patch.object(overview_api, "peek_city_report_cached", return_value=None), \
             patch.object(energy_api, "run_energy_agent",
                          side_effect=AssertionError("agent must not run")):
            response = overview_api.get_overview_city(_request())

        card = _module_card(response, "energy")
        assert card.status == "normal"
        metrics = {m.key: m for m in card.metrics}
        assert metrics["peak_demand"].value == 7200.0
        assert metrics["max_peak"].value == 7500.0
        assert metrics["solar"].value == 500.0

    def test_housing_card_reads_ttl_cache(self):
        housing_api._cache.update({
            "report": _stub_report({
                "status": "AVAILABLE",
                "kpis": {
                    "resale_applications": 4500,
                    "hdb_property_records": 10500,
                    "hdb_total_dwelling_units_in_records": 1_050_000,
                },
                "generated_at": "2026-10-24T08:00:00+08:00",
            }),
            "expires_at": time.time() + 1800,
        })
        with patch.object(overview_api, "peek_city_report_cached", return_value=None), \
             patch.object(housing_api, "run_housing_agent",
                          side_effect=AssertionError("agent must not run")):
            response = overview_api.get_overview_city(_request())

        card = _module_card(response, "housing")
        assert card.status == "normal"
        metrics = {m.key: m for m in card.metrics}
        assert metrics["resale_apps"].value == 4500
        assert metrics["property_records"].value == 10500
        assert metrics["dwelling_units"].value == 1_050_000

    def test_construction_card_reads_ttl_cache(self):
        construction_api._cache.update({
            "report": _stub_report({
                "status": "available",
                "greenmark_buildings": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
                "pipeline_records": [{"id": "P1"}],
                "generated_at": "2026-10-24T08:00:00+08:00",
            }),
            "expires_at": time.time() + 1800,
        })
        with patch.object(overview_api, "peek_city_report_cached", return_value=None), \
             patch.object(construction_api, "run_construction_agent",
                          side_effect=AssertionError("agent must not run")):
            response = overview_api.get_overview_city(_request())

        card = _module_card(response, "construction")
        assert card.status == "normal"
        metrics = {m.key: m for m in card.metrics}
        assert metrics["greenmark"].value == 3
        assert metrics["pipeline"].value == 1

    def test_expired_cache_is_ignored_rather_than_served(self):
        waste_api._cache.update({
            "report": _stub_report({"status": "STATISTICS_AVAILABLE"}),
            "expires_at": time.time() - 1,
        })
        with patch.object(overview_api, "peek_city_report_cached", return_value=None):
            response = overview_api.get_overview_city(_request())

        assert _module_card(response, "waste").status == "unavailable"


# ======================================================================
# Partial and zero-valued card metrics
# ======================================================================

class TestPartialAndZeroMetrics:
    def test_one_missing_field_does_not_discard_the_metric_group(self):
        """Only total_generated exists; recycled and recycling_rate must
        still render as explicit unavailable placeholders."""
        waste_api._cache.update({
            "report": _stub_report({
                "status": "STATISTICS_AVAILABLE",
                "kpis": [
                    {"key": "total_generated", "label": "Total Waste Generated",
                     "value": 7_000_000, "unit": "tonnes"},
                ],
                "generated_at": "2026-10-24T08:00:00+08:00",
            }),
            "expires_at": time.time() + 600,
        })
        with patch.object(overview_api, "peek_city_report_cached", return_value=None):
            response = overview_api.get_overview_city(_request())

        metrics = {m.key: m for m in _module_card(response, "waste").metrics}
        assert len(metrics) == 3, "the whole group must survive a missing field"
        assert metrics["generated"].value == 7_000_000
        assert metrics["recycled"].value is None
        assert metrics["recycling_rate"].value is None

    def test_zero_valued_metric_is_a_reading_not_a_gap(self):
        """A dataset that loaded with zero records reports 0 - never None,
        never hidden by a truthiness check."""
        construction_api._cache.update({
            "report": _stub_report({
                "status": "empty",
                "greenmark_buildings": [],
                "pipeline_records": [],
                "generated_at": "2026-10-24T08:00:00+08:00",
            }),
            "expires_at": time.time() + 1800,
        })
        with patch.object(overview_api, "peek_city_report_cached", return_value=None):
            response = overview_api.get_overview_city(_request())

        card = _module_card(response, "construction")
        assert card.status == "normal"
        metrics = {m.key: m for m in card.metrics}
        assert metrics["greenmark"].value == 0
        assert metrics["pipeline"].value == 0

    def test_unknown_flood_risk_is_a_gap_not_a_zero(self):
        from backend.app.intelligence.normalize import build_card_metrics

        metrics = {m["key"]: m for m in build_card_metrics(
            "flood", {"risk_level": "UNKNOWN", "active_alert_count": 0})}
        assert metrics["risk"]["value"] is None, "UNKNOWN must not read as a value"
        assert metrics["active_alerts"]["value"] == 0, "a real zero must survive"

    def test_coordinator_flat_key_metrics_also_feed_the_card(self):
        """Coordinator-cached statuses publish flat key_metrics (no embedded
        list); the same canonical spec must resolve them."""
        report = MagicMock()
        status_dict = DomainStatus(
            domain="waste",
            available=True,
            overall_status="NORMAL",
            key_metrics={
                "waste_generated_tonnes": 7_000_000,
                "waste_recycled_tonnes": 3_500_000,
                "overall_recycling_rate_pct": 50.0,
            },
        )
        report.domain_status = {"waste": status_dict}
        with patch.object(overview_api, "peek_city_report_cached",
                          return_value=(report, {})):
            response = overview_api.get_overview_city(_request())

        metrics = {m.key: m for m in _module_card(response, "waste").metrics}
        assert metrics["generated"].value == 7_000_000
        assert metrics["recycled"].value == 3_500_000
        assert metrics["recycling_rate"].value == 50.0

    def test_headline_kpi_and_metric_list_agree_on_the_first_metric(self):
        """The card's big number must be one of the card's metrics, with the
        same value, so the frontend can de-duplicate it from the metric rows
        by label. The headline must never disagree with its own metric."""
        waste_api._cache.update({
            "report": _stub_report({
                "status": "STATISTICS_AVAILABLE",
                "kpis": [
                    {"key": "total_generated", "label": "Total Waste Generated",
                     "value": 7_000_000, "unit": "tonnes"},
                ],
            }),
            "expires_at": time.time() + 600,
        })
        with patch.object(overview_api, "peek_city_report_cached", return_value=None):
            response = overview_api.get_overview_city(_request())

        card = _module_card(response, "waste")
        assert card.kpi is not None
        matching = [m for m in card.metrics if m.label == card.kpi.label]
        assert matching, (
            "headline label must exist in the metric list so the card never "
            "shows two numbers for the same metric")
        assert matching[0].value == card.kpi.value
