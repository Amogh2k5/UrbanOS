from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.app.coordinator.city_agent import _normalize_crime, _normalize_traffic, _to_domain_status
from backend.app.intelligence.contracts import CitySituationReport, DomainStatus
from backend.app.intelligence.normalize import CANONICAL_MODULES, MODULE_METRICS, build_card_metrics
from backend.app.overview import api as overview_api


@pytest.fixture(autouse=True)
def _mock_cold_summary_fetchers():
    async def unavailable(*_args, **_kwargs):
        return {"error": "mocked_unavailable"}

    with patch.multiple(overview_api, **{
        f"_fetch_{module}_overview": unavailable
        for module in CANONICAL_MODULES
    }):
        overview_api._city_overview_original = overview_api.get_overview_city
        try:
            with patch.object(overview_api, "get_overview_city", _run_city_overview):
                yield
        finally:
            del overview_api._city_overview_original


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
    """The legacy coroutine-stepper has no running event loop for task creation."""
    if started is not None:
        started.set()
    return await loader()


def _run_city_overview(request):
    coroutine = overview_api.__dict__["_city_overview_original"](request)
    with patch.object(overview_api.asyncio, "Semaphore", _ImmediateSemaphore), \
         patch.object(overview_api.asyncio, "wait_for", _immediate_wait_for), \
         patch.object(overview_api.asyncio, "gather", _immediate_gather), \
         patch.object(overview_api._OVERVIEW_SUMMARY_CACHE, "get", _inline_summary_get):
        try:
            return coroutine.send(None)
        except StopIteration as completed:
            return completed.value


def test_all_canonical_modules_have_structured_card_metric_specs():
    assert set(MODULE_METRICS) == set(CANONICAL_MODULES)
    assert all(MODULE_METRICS[domain] for domain in CANONICAL_MODULES)


def test_city_overview_prefers_observed_traffic_speed_summary_to_coordinator_status():
    traffic = _to_domain_status("traffic", _normalize_traffic({
        "overall_status": "disrupted",
        "overall_average_speed": 34.2,
        "overall_predicted_speed": 42.0,
        "overall_speed_change_percent": -18.6,
        "overall_congestion_level": "heavy",
        "incidents": [],
        "generated_at": "2026-10-25T09:55:00+08:00",
    }))
    report = CitySituationReport(generated_at="2026-10-25T10:00:00+08:00", domain_status={
        "traffic": traffic,
    })

    async def observed_summary(_state):
        return {
            "overall_average_speed": 34.2,
            "source_status": "live",
            "generated_at": "2026-10-25T09:55:00+08:00",
        }

    with patch.object(overview_api, "peek_city_report_cached", return_value=(report, {})), \
         patch.object(overview_api, "_fetch_traffic_overview", observed_summary):
        response = overview_api.get_overview_city(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())))

    assert [module.id for module in response.modules] == list(CANONICAL_MODULES)
    assert "environment" not in [module.id for module in response.modules]
    card = next(module for module in response.modules if module.id == "traffic")
    assert card.kpi is not None
    assert (card.kpi.label, card.kpi.value, card.kpi.unit) == ("Average Speed", 34.2, "km/h")
    assert card.status == "unavailable"  # no separate observed-risk rule was supplied
    assert card.data_state == "partial"


def test_city_overview_uses_crime_count_when_only_cybercrime_is_available():
    crime = _to_domain_status("crime", _normalize_crime({
        "source_status": "partial",
        "total_physical_crime_2025": None,
        "total_scams_cybercrime_2025": 55244,
        "generated_at": "2026-10-25T09:55:00+08:00",
    }))
    report = CitySituationReport(generated_at="2026-10-25T10:00:00+08:00", domain_status={
        "crime": crime,
    })

    with patch.object(overview_api, "peek_city_report_cached", return_value=(report, {})):
        response = overview_api.get_overview_city(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())))

    card = next(module for module in response.modules if module.id == "crime")
    assert card.status == "normal"
    assert card.kpi is not None
    assert (card.kpi.label, card.kpi.value) == ("Scams & Cybercrime", 55244)
    assert card.data_state == "partial"
    assert any(metric.label == "Physical Crime" and metric.value is None for metric in card.metrics)


def test_partial_metrics_and_zero_are_preserved_independently():
    metrics = build_card_metrics("traffic", {
        "average_speed_kmh": 0,
        "congestion_level": None,
        "incident_count": 0,
    })

    assert [metric["value"] for metric in metrics] == [0, None, 0]


def test_unloaded_module_stays_unavailable_without_fetching_domain_workflows():
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Overview triggered domain fetching")

    status = DomainStatus(domain="traffic", available=False)
    report = CitySituationReport(generated_at="2026-10-25T10:00:00+08:00", domain_status={
        "traffic": status,
    })
    with patch.object(overview_api, "peek_city_report_cached", return_value=(report, {})), \
         patch.object(overview_api, "city_report_cached", side_effect=AssertionError("coordinator invoked")), \
         patch.object(overview_api, "_fetch_traffic_overview", forbidden):
        response = overview_api.get_overview_city(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())))

    traffic = next(module for module in response.modules if module.id == "traffic")
    assert traffic.status == "unavailable"
    assert traffic.data_state == "unavailable"
    assert traffic.kpi is not None and traffic.kpi.label == "Average Speed" and traffic.kpi.value is None


def test_cold_overview_restores_direct_module_summary_loading_without_coordinator():
    calls = {name: 0 for name in CANONICAL_MODULES}

    def make_fetcher(name):
        async def fetch(_state):
            calls[name] += 1
            if name == "weather":
                return {
                    "source_status": "available",
                    "general": {"temperature_c": 27.4, "forecast_text": "Cloudy"},
                    "timestamp": "2026-10-26T10:00:00+08:00",
                }
            return {"error": "mocked_unavailable"}
        return fetch

    fetchers = {name: make_fetcher(name) for name in CANONICAL_MODULES}
    with patch.object(overview_api, "peek_city_report_cached", return_value=None), \
         patch.object(overview_api, "city_report_cached", side_effect=AssertionError("coordinator invoked")), \
         patch.object(overview_api, "_module_fetcher_map", return_value=fetchers):
        response = overview_api.get_overview_city(
            SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        )

    assert all(count == 1 for count in calls.values())
    assert [module.id for module in response.modules] == list(CANONICAL_MODULES)
    weather = next(module for module in response.modules if module.id == "weather")
    assert weather.status == "normal"
    assert weather.kpi is not None
    assert (weather.kpi.label, weather.kpi.value, weather.kpi.unit) == (
        "Temperature", 27.4, "°C"
    )
    assert next(module for module in response.modules if module.id == "flood").status == "unavailable"


def test_land_detail_report_cache_is_reused_by_overview_without_running_agent():
    from backend.app.planning.land import api as land_api

    class LandReportFixture:
        generated_at = "2026-10-26T10:00:00+08:00"
        errors = []

        def model_dump(self, **_kwargs):
            return {
                "source_status": "available",
                "generated_at": self.generated_at,
                "land_use": {"total_area_km2": 796.8, "categories": []},
                "planning": {"planning_area_count": 55},
                "errors": [],
            }

    previous_cache = dict(land_api._REPORT_CACHE)
    try:
        land_api._REPORT_CACHE.update(report=None, expires_at=0.0)
        with patch.object(land_api, "run_land_agent", return_value=LandReportFixture()), \
             patch.object(overview_api, "peek_city_report_cached", return_value=None):
            # Exercise the actual detail endpoint and its report cache.
            detail_payload = land_api.land_report()
            assert detail_payload["land_use"]["total_area_km2"] == 796.8
            response = overview_api.get_overview_city(
                SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
            )

        card = next(module for module in response.modules if module.id == "land")
        assert card.status == "normal"
        assert card.kpi is not None
        assert (card.kpi.label, card.kpi.value, card.kpi.unit) == (
            "Land-Use Area", 796.8, "km²"
        )
        assert card.data_state == "available"
    finally:
        land_api._REPORT_CACHE.update(previous_cache)


def test_land_unavailable_cache_is_not_normalized_as_normal():
    from backend.app.planning.land import api as land_api

    unavailable_report = SimpleNamespace(model_dump=lambda **_kwargs: {
        "source_status": "unavailable",
        "land_use": {"total_area_km2": None},
        "planning": {"planning_area_count": None},
        "errors": ["Land source request failed"],
    })
    with patch.object(land_api, "peek_land_report", return_value=unavailable_report), \
         patch.object(overview_api, "peek_city_report_cached", return_value=None):
        response = overview_api.get_overview_city(
            SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        )

    card = next(module for module in response.modules if module.id == "land")
    assert card.status == "unavailable"
    assert card.data_state == "unavailable"
    assert card.kpi is not None and card.kpi.value is None
