from __future__ import annotations

import asyncio
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from backend.app.environment.flood import rainfall_clients
from backend.app.environment.weather import api as weather_api
from backend.app.intelligence.normalize import CANONICAL_MODULES
from backend.app.overview import api as overview_api


def _run_async(coroutine):
    """Run async tests without Windows' blocked socketpair wakeup pipe."""
    if sys.platform == "win32":
        class _LocalOnlySelectorLoop(asyncio.SelectorEventLoop):
            def _make_self_pipe(self):
                self._ssock = self._csock = None
                self._internal_fds = 0

            def _write_to_self(self):
                return None

            def _close_self_pipe(self):
                return None

        def make_loop():
            loop = _LocalOnlySelectorLoop()
            loop._selector.select = lambda timeout=None: []
            return loop

        with asyncio.Runner(loop_factory=make_loop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def test_overview_concurrent_and_repeated_requests_share_domain_work():
    async def exercise():
        overview_api._OVERVIEW_SUMMARY_CACHE.clear()
        app_state = SimpleNamespace()
        request = SimpleNamespace(app=SimpleNamespace(state=app_state))
        calls = {module: 0 for module in CANONICAL_MODULES}

        def fetcher_for(module):
            async def fetch(_state):
                calls[module] += 1
                return {"error": "upstream rate limited (429)"}
            return fetch

        fetchers = {module: fetcher_for(module) for module in CANONICAL_MODULES}
        with patch.object(overview_api, "peek_city_report_cached", return_value=None), \
             patch.object(overview_api, "_module_fetcher_map", return_value=fetchers):
            first, second = await asyncio.gather(
                overview_api.get_overview_city(request),
                overview_api.get_overview_city(request),
            )
            third = await overview_api.get_overview_city(request)

        assert calls == {module: 1 for module in CANONICAL_MODULES}
        for response in (first, second, third):
            assert [card.id for card in response.modules] == list(CANONICAL_MODULES)
            assert len(response.modules) == 14
            assert all(card.status == "unavailable" for card in response.modules)
        overview_api._OVERVIEW_SUMMARY_CACHE.clear()

    _run_async(exercise())


def test_overview_summary_singleflight_reuses_success_and_returns_independent_values():
    async def exercise():
        overview_api._OVERVIEW_SUMMARY_CACHE.clear()
        app_state = SimpleNamespace()
        calls = 0

        async def load():
            nonlocal calls
            calls += 1
            return {"general": {"temperature_c": 26.5}}

        first, second = await asyncio.gather(*(
            overview_api._OVERVIEW_SUMMARY_CACHE.get(app_state, "weather", load)
            for _ in range(2)
        ))
        first["general"]["temperature_c"] = 0
        third = await overview_api._OVERVIEW_SUMMARY_CACHE.get(app_state, "weather", load)

        assert calls == 1
        assert second["general"]["temperature_c"] == 26.5
        assert third["general"]["temperature_c"] == 26.5
        overview_api._OVERVIEW_SUMMARY_CACHE.clear()

    _run_async(exercise())


def test_cancelled_summary_caller_does_not_start_duplicate_work():
    async def exercise():
        overview_api._OVERVIEW_SUMMARY_CACHE.clear()
        app_state = SimpleNamespace()
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def slow_load():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return {"source_status": "live", "value": 12}

        first = asyncio.create_task(
            overview_api._OVERVIEW_SUMMARY_CACHE.get(app_state, "flood", slow_load)
        )
        await started.wait()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                overview_api._OVERVIEW_SUMMARY_CACHE.get(app_state, "flood", slow_load),
                timeout=0.01,
            )
        second = asyncio.create_task(
            overview_api._OVERVIEW_SUMMARY_CACHE.get(app_state, "flood", slow_load)
        )
        await asyncio.sleep(0)
        assert calls == 1
        release.set()
        assert await first == {"source_status": "live", "value": 12}
        assert await second == {"source_status": "live", "value": 12}
        overview_api._OVERVIEW_SUMMARY_CACHE.clear()

    _run_async(exercise())


def test_expired_overview_summary_is_refetched():
    async def exercise():
        overview_api._OVERVIEW_SUMMARY_CACHE.clear()
        app_state = SimpleNamespace()
        calls = 0

        async def load():
            nonlocal calls
            calls += 1
            return {"source_status": "live", "value": calls}

        with patch.object(overview_api, "_OVERVIEW_DEFAULT_SUCCESS_TTL_S", 0.01):
            assert await overview_api._OVERVIEW_SUMMARY_CACHE.get(app_state, "traffic", load) == {
                "source_status": "live", "value": 1
            }
            await asyncio.sleep(0.02)
            assert await overview_api._OVERVIEW_SUMMARY_CACHE.get(app_state, "traffic", load) == {
                "source_status": "live", "value": 2
            }
        assert calls == 2
        overview_api._OVERVIEW_SUMMARY_CACHE.clear()

    _run_async(exercise())


def test_city_overview_timeout_is_per_active_domain_and_isolates_other_modules():
    async def exercise():
        overview_api._OVERVIEW_SUMMARY_CACHE.clear()
        app_state = SimpleNamespace()
        request = SimpleNamespace(app=SimpleNamespace(state=app_state))
        calls = {module: 0 for module in CANONICAL_MODULES}
        slow_started = asyncio.Event()
        slow_release = asyncio.Event()
        slow_finished = asyncio.Event()

        def fetcher_for(module):
            async def fetch(_state):
                calls[module] += 1
                if module == CANONICAL_MODULES[0]:
                    slow_started.set()
                    await slow_release.wait()
                    slow_finished.set()
                else:
                    await asyncio.sleep(0)
                return {
                    "available": True,
                    "source_status": "live",
                    "generated_at": "2026-10-26T10:00:00+08:00",
                    "overall_status": "NORMAL",
                    "overall_risk": "LOW",
                    "key_metrics": {"headline": {"label": "Reading", "value": 1, "unit": ""}},
                }
            return fetch

        fetchers = {module: fetcher_for(module) for module in CANONICAL_MODULES}

        async def release_after_timeout():
            await slow_started.wait()
            await asyncio.sleep(0.03)
            slow_release.set()

        with patch.object(overview_api, "peek_city_report_cached", return_value=None), \
             patch.object(overview_api, "_MODULE_PEEKS", {}), \
             patch.object(overview_api, "_module_fetcher_map", return_value=fetchers), \
             patch.object(overview_api, "_OVERVIEW_DOMAIN_TIMEOUT_S", 0.01):
            releaser = asyncio.create_task(release_after_timeout())
            response = await overview_api.get_overview_city(request)
            await releaser
            await slow_finished.wait()
            second = await overview_api.get_overview_city(request)

        assert set(calls.values()) == {1}
        assert len(response.modules) == 14
        assert response.domain_status[CANONICAL_MODULES[0]].available is False
        assert all(response.domain_status[module].available for module in CANONICAL_MODULES[1:])
        # The timed-out report completes in the background and is reusable by
        # the next sequential Overview request with its original timestamp.
        assert second.domain_status[CANONICAL_MODULES[0]].available is True
        assert second.domain_status[CANONICAL_MODULES[0]].generated_at == "2026-10-26T10:00:00+08:00"
        overview_api._OVERVIEW_SUMMARY_CACHE.clear()

    _run_async(exercise())


def _rainfall_response(status_code, *, headers=None, payload=None):
    return httpx.Response(
        status_code,
        request=httpx.Request("GET", "https://example.test/rainfall"),
        headers=headers,
        json=payload or {},
    )


def _rainfall_payload():
    return {"data": {
        "stations": [{"id": "S1", "name": "Station", "location": {}}],
        "readings": [{"timestamp": "2026-10-26T00:00:00Z", "data": [{"stationId": "S1", "value": 0}]}],
    }}


def test_rainfall_429_respects_retry_after_and_then_caches_success():
    rainfall_clients._RAINFALL_CACHE.clear()
    with patch.object(rainfall_clients.httpx, "Client") as client_cls, \
         patch.object(rainfall_clients.time, "sleep") as sleep:
        client_cls.return_value.__enter__.return_value.get.side_effect = [
            _rainfall_response(429, headers={"Retry-After": "7"}),
            _rainfall_response(200, payload=_rainfall_payload()),
        ]
        client = rainfall_clients.RainfallApiClient(
            base_url="https://example.test", offline=False, allow_fallback_fixture=False
        )
        assert client.fetch().is_live is True
        assert client.fetch().is_live is True

    assert client_cls.return_value.__enter__.return_value.get.call_count == 2
    sleep.assert_called_once_with(7.0)
    rainfall_clients._RAINFALL_CACHE.clear()


def test_rainfall_permanent_failure_is_not_retried_or_reissued_immediately():
    rainfall_clients._RAINFALL_CACHE.clear()
    with patch.object(rainfall_clients.httpx, "Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = _rainfall_response(403)
        client = rainfall_clients.RainfallApiClient(
            base_url="https://example.test", offline=False, allow_fallback_fixture=False
        )
        for _ in range(2):
            with pytest.raises(httpx.HTTPStatusError):
                client.fetch()

    assert client_cls.return_value.__enter__.return_value.get.call_count == 1
    rainfall_clients._RAINFALL_CACHE.clear()


def test_empty_live_rainfall_response_is_unavailable_not_fixture_data():
    rainfall_clients._RAINFALL_CACHE.clear()
    with patch.object(rainfall_clients.httpx, "Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = _rainfall_response(
            200, payload={"data": {"stations": [], "readings": []}}
        )
        client = rainfall_clients.RainfallApiClient(
            base_url="https://example.test", offline=False, allow_fallback_fixture=False
        )
        with pytest.raises(ValueError, match="missing data.readings"):
            client.fetch()
    assert client_cls.return_value.__enter__.return_value.get.call_count == 1
    rainfall_clients._RAINFALL_CACHE.clear()


def test_rainfall_singleflight_keys_are_independent_by_endpoint_and_date():
    rainfall_clients._RAINFALL_CACHE.clear()
    release = threading.Event()
    calls = []

    def response(*args, **kwargs):
        calls.append((args, kwargs))
        release.wait(timeout=2)
        return _rainfall_response(200, payload=_rainfall_payload())

    clients = [
        rainfall_clients.RainfallApiClient(base_url="https://one.test", offline=False),
        rainfall_clients.RainfallApiClient(base_url="https://two.test", offline=False),
        rainfall_clients.RainfallApiClient(base_url="https://one.test", offline=False),
    ]
    results = []
    with patch.object(rainfall_clients.httpx, "Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.side_effect = response
        workers = [
            threading.Thread(target=lambda c=c, d=d: results.append(c.fetch(d)))
            for c, d in zip(clients, (None, None, "2026-10-26"))
        ]
        for worker in workers:
            worker.start()
        deadline = time.monotonic() + 3
        while len(calls) < 3 and time.monotonic() < deadline:
            time.sleep(0.005)
        release.set()
        for worker in workers:
            worker.join(timeout=3)

    # Different base URLs and dates each run independently. Same endpoint/date
    # callers would share one operation; here no two complete keys match.
    assert len(calls) == 3
    assert len(results) == 3
    rainfall_clients._RAINFALL_CACHE.clear()


def test_timed_out_provider_caller_keeps_source_singleflight_until_work_finishes():
    async def exercise():
        rainfall_clients._RAINFALL_CACHE.clear()
        entered = threading.Event()
        release = threading.Event()

        def response(*args, **kwargs):
            entered.set()
            release.wait(timeout=3)
            return _rainfall_response(200, payload=_rainfall_payload())

        clients = [
            rainfall_clients.RainfallApiClient(base_url="https://timeout.test", offline=False),
            rainfall_clients.RainfallApiClient(base_url="https://timeout.test", offline=False),
        ]
        with patch.object(rainfall_clients.httpx, "Client") as client_cls:
            client_cls.return_value.__enter__.return_value.get.side_effect = response
            first = asyncio.create_task(asyncio.to_thread(clients[0].fetch))
            assert await asyncio.to_thread(entered.wait, 2)
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(first), timeout=0.01)
            second = asyncio.create_task(asyncio.to_thread(clients[1].fetch))
            await asyncio.sleep(0.03)
            assert client_cls.return_value.__enter__.return_value.get.call_count == 1
            release.set()
            assert (await second).is_live is True
        rainfall_clients._RAINFALL_CACHE.clear()

    _run_async(exercise())


def test_weather_forecast_singleflight_coalesces_same_source_and_separates_parameters():
    weather_api._WEATHER_FORECAST_CACHE.clear()
    release = threading.Event()
    calls = []
    payload = {"data": {"records": [{"general": {"forecast": {"code": "Cloudy"}}}]}}

    def response(*args, **kwargs):
        calls.append((args, kwargs))
        release.wait(timeout=2)
        return httpx.Response(
            200, request=httpx.Request("GET", "https://example.test/weather"), json=payload
        )

    clients = [
        weather_api.WeatherApiClient(base_url="https://one.test", allow_fallback_fixture=False),
        weather_api.WeatherApiClient(base_url="https://one.test", allow_fallback_fixture=False),
        weather_api.WeatherApiClient(base_url="https://one.test", allow_fallback_fixture=False),
    ]
    results = []
    with patch.object(weather_api.httpx, "Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.side_effect = response
        workers = [
            threading.Thread(target=lambda c=c, d=d: results.append(c._get_payload(d)))
            for c, d in zip(clients, (None, None, "2026-10-26"))
        ]
        for worker in workers:
            worker.start()
        deadline = time.monotonic() + 3
        while len(calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        release.set()
        for worker in workers:
            worker.join(timeout=3)

    assert len(calls) == 2
    assert len(results) == 3
    weather_api._WEATHER_FORECAST_CACHE.clear()


def test_weather_forecast_429_honors_retry_after_and_403_is_not_retried():
    weather_api._WEATHER_FORECAST_CACHE.clear()
    with patch.object(weather_api.httpx, "Client") as client_cls, \
         patch.object(weather_api.time, "sleep") as sleep:
        client_cls.return_value.__enter__.return_value.get.side_effect = [
            httpx.Response(
                429, request=httpx.Request("GET", "https://example.test/weather"),
                headers={"Retry-After": "5"},
            ),
            httpx.Response(
                200, request=httpx.Request("GET", "https://example.test/weather"),
                json={"data": {"records": [{}]}},
            ),
        ]
        client = weather_api.WeatherApiClient(
            base_url="https://example.test", allow_fallback_fixture=False
        )
        assert client._get_payload(None)[1] is True
        assert client_cls.return_value.__enter__.return_value.get.call_count == 2
        sleep.assert_called_once_with(5.0)

        weather_api._WEATHER_FORECAST_CACHE.clear()
        mock_get = client_cls.return_value.__enter__.return_value.get
        mock_get.reset_mock()
        mock_get.side_effect = None
        mock_get.return_value = httpx.Response(
            403, request=httpx.Request("GET", "https://example.test/weather")
        )
        with pytest.raises(httpx.HTTPStatusError):
            client._get_payload(None)
        with pytest.raises(httpx.HTTPStatusError):
            client._get_payload(None)
        assert mock_get.call_count == 1
    weather_api._WEATHER_FORECAST_CACHE.clear()


def test_empty_live_weather_response_uses_failure_cooldown():
    weather_api._WEATHER_FORECAST_CACHE.clear()
    with patch.object(weather_api.httpx, "Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = httpx.Response(
            200, request=httpx.Request("GET", "https://empty.test/weather"),
            json={"data": {"records": []}},
        )
        client = weather_api.WeatherApiClient(
            base_url="https://empty.test", allow_fallback_fixture=False
        )
        for _ in range(2):
            with pytest.raises(ValueError, match="Weather payload missing data.records"):
                client.fetch()
    assert client_cls.return_value.__enter__.return_value.get.call_count == 1
    weather_api._WEATHER_FORECAST_CACHE.clear()
