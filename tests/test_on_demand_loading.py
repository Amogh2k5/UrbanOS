"""Regression tests for startup and Overview's on-demand data contract."""
from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import requests


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
    if started is not None:
        started.set()
    return await loader()


def _run_city_overview(api, request):
    coroutine = api.get_overview_city(request)
    with patch.object(api.asyncio, "Semaphore", _ImmediateSemaphore), \
         patch.object(api.asyncio, "wait_for", _immediate_wait_for), \
         patch.object(api.asyncio, "gather", _immediate_gather), \
         patch.object(api._OVERVIEW_SUMMARY_CACHE, "get", _inline_summary_get):
        try:
            return coroutine.send(None)
        except StopIteration as completed:
            return completed.value


def test_app_construction_does_not_start_collectors_or_fetch_providers():
    from backend.app.environment.pm25.live_service import Pm25LiveSnapshotService
    from backend.app.environment.weather.scheduler import WeatherScheduler
    from backend.app.mobility.traffic.prediction_service import TrafficPredictionService
    from backend.app.mobility.transit.scheduler import TransitAlertsScheduler
    from backend.app.infrastructure.water import api as water_api
    from backend.app.planning.land import api as land_api
    from backend.app.coordinator import access as coordinator_access

    with patch.object(requests.sessions.Session, "request", side_effect=AssertionError("unexpected HTTP")) as requests_call, \
         patch.object(httpx.Client, "request", side_effect=AssertionError("unexpected HTTP")) as httpx_call, \
         patch("urllib.request.urlopen", side_effect=AssertionError("unexpected HTTP")) as urllib_call, \
         patch.object(TrafficPredictionService, "start") as traffic_start, \
         patch.object(Pm25LiveSnapshotService, "start") as pm25_start, \
         patch.object(WeatherScheduler, "run") as weather_run, \
         patch.object(TransitAlertsScheduler, "run") as transit_run, \
         patch.object(water_api, "start_water_warmup") as water_warmup, \
         patch.object(land_api, "start_land_warmup") as land_warmup, \
         patch.object(coordinator_access, "start_coordinator_warmup") as coordinator_warmup:
        main = importlib.import_module("backend.app.main")
        main = importlib.reload(main)
        app = main._build_app()

    assert app is not None
    requests_call.assert_not_called()
    httpx_call.assert_not_called()
    urllib_call.assert_not_called()
    traffic_start.assert_not_called()
    pm25_start.assert_not_called()
    weather_run.assert_not_called()
    transit_run.assert_not_called()
    water_warmup.assert_not_called()
    land_warmup.assert_not_called()
    coordinator_warmup.assert_not_called()


def test_overview_loads_domain_summaries_without_starting_coordinator():
    from backend.app.overview import api

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Overview invoked a domain fetcher")

    # The canonical 14-module roster. `environment` is deliberately absent
    # from the fetcher patches: it is the legacy umbrella over pm25+weather
    # and must never have a fetcher or a card; the id assertions below prove
    # it cannot leak in as a duplicate.
    domain_names = (
        "traffic", "roads", "transit", "pm25", "weather", "flood",
        "fire", "crime", "water", "waste", "energy",
        "land", "housing", "construction",
    )
    with patch.object(api, "peek_city_report_cached", return_value=None) as peek, \
         patch.object(api, "city_report_cached", side_effect=AssertionError("coordinator started")), \
         patch.object(api, "_coordinator_assessment", side_effect=AssertionError("coordinator started")), \
         patch.multiple(api, **{f"_fetch_{name}_overview": forbidden for name in domain_names}):
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        response = _run_city_overview(api, request)

    rendered_ids = [m.id for m in response.modules]
    assert len(rendered_ids) == 14, rendered_ids
    assert "environment" not in rendered_ids, "legacy umbrella must not duplicate pm25/weather"
    assert sorted(rendered_ids) == sorted(domain_names)
    assert all(module.status == "unavailable" for module in response.modules)
    # A declared metric keeps its label even when its cold value is unknown.
    # This distinguishes unavailable data from a domain with no supported KPI.
    assert all(module.kpi is None or module.kpi.value is None for module in response.modules)
    assert all(not status.available for status in response.domain_status.values())
    assert response.alerts == []
    assert response.city_assessment_ready is False
    assert "assessment pending" in response.ai_brief.lower()
    peek.assert_called_once_with()


def test_overview_reuses_cached_domain_summaries_without_fetching():
    from backend.app.overview import api
    from backend.app.intelligence.contracts import CitySituationReport, DomainStatus

    report = CitySituationReport(
        generated_at="2026-10-24T10:00:00+08:00",
        domain_status={
            "water": DomainStatus(
                domain="water",
                available=True,
                overall_status="normal",
                generated_at="2026-10-24T09:55:00+08:00",
                key_metrics={"headline": {"label": "Potable Sales", "value": 515.5, "unit": "million m³"}},
            ),
        },
    )
    with patch.object(api, "peek_city_report_cached", return_value=(report, {})):
        response = _run_city_overview(api, SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())))

    water = next(module for module in response.modules if module.id == "water")
    assert water.status == "normal"
    assert water.kpi is not None and water.kpi.value == 515.5
    assert water.updated_at == "2026-10-24T09:55:00+08:00"


def _run_immediate(coroutine):
    """Drive mocked async code without opening Windows event-loop sockets."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("mocked operation unexpectedly suspended")


def test_city_narrative_endpoint_does_not_start_a_cold_coordinator():
    from backend.app.overview import api

    with patch.object(api, "peek_city_report_cached", return_value=None) as peek, \
         patch.object(api, "city_report_cached", side_effect=AssertionError("coordinator started")):
        response = _run_immediate(api.get_city_narrative())

    assert response.city_assessment_ready is False
    assert response.ai_brief is None
    assert response.report_generated_at is None
    peek.assert_called_once_with()


def test_module_detail_calls_only_requested_module_workflow():
    from backend.app.overview import api

    names = (
        "traffic", "roads", "transit", "pm25", "weather", "flood",
        "fire", "crime", "water", "waste", "energy",
        "land", "housing", "construction",
    )
    spies = {name: AsyncMock(return_value={"error": "mock unavailable"}) for name in names}
    patches = [patch.object(api, f"_fetch_{name}_overview", spies[name]) for name in names]
    for item in patches:
        item.start()
    try:
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        with patch.object(api._OVERVIEW_SUMMARY_CACHE, "get", _inline_summary_get):
            response = _run_immediate(api.get_overview_module(request, "water"))
    finally:
        for item in reversed(patches):
            item.stop()

    assert response.module_id == "water"
    for name, spy in spies.items():
        assert spy.await_count == (1 if name == "water" else 0), name
