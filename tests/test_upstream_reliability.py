from __future__ import annotations

import json
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from unittest.mock import MagicMock

import httpx
import pytest
import requests

from backend.app.upstream import SingleFlightTTLCache, retry_after_seconds


def test_singleflight_cache_coalesces_concurrent_source_loads_and_reuses_fresh_value():
    cache = SingleFlightTTLCache()
    started = threading.Event()
    call_count = 0
    count_lock = threading.Lock()

    def fetch():
        nonlocal call_count
        with count_lock:
            call_count += 1
        started.set()
        time.sleep(0.05)
        return {"records": [1], "retrieved_at": "source-time"}

    with ThreadPoolExecutor(max_workers=8) as pool:
        first = pool.submit(cache.get_or_fetch, "dataset", fetch, ttl_seconds=60)
        assert started.wait(1)
        rest = [pool.submit(cache.get_or_fetch, "dataset", fetch, ttl_seconds=60) for _ in range(7)]
        results = [first.result(), *(future.result() for future in rest)]

    assert call_count == 1
    assert all(result is results[0] for result in results)
    assert cache.get_or_fetch("dataset", lambda: pytest.fail("fresh cache missed"), ttl_seconds=60) is results[0]


def test_retry_after_header_is_parsed_as_seconds_and_http_date():
    exc = requests.HTTPError("429")
    exc.response = requests.Response()
    exc.response.headers["Retry-After"] = "7"
    assert retry_after_seconds(exc) == 7.0


def test_429_without_retry_after_uses_bounded_exponential_jitter():
    from backend.app.upstream import retry_429_delay

    exc = requests.HTTPError("429")
    exc.response = requests.Response()
    exc.response.status_code = 429
    assert retry_429_delay(exc, 2, base_seconds=2, max_seconds=10,
                           jitter=lambda low, high: high * 0.75) == 6.0


def test_energy_429_retries_once_after_retry_after_and_coalesces_results(monkeypatch):
    from backend.app.infrastructure.energy import data
    from backend.app import upstream

    data.clear_energy_source_cache()
    calls = []
    sleeps = []
    limited = requests.Response()
    limited.status_code = 429
    limited.url = data.BASE
    limited.headers["Retry-After"] = "4"
    success = requests.Response()
    success.status_code = 200
    success.url = data.BASE
    success._content = json.dumps({"success": True, "result": {"records": [{"year": "2020"}]}}).encode()

    def get(*args, **kwargs):
        calls.append((args, kwargs))
        return limited if len(calls) == 1 else success

    monkeypatch.setattr(data.requests, "get", get)
    monkeypatch.setattr(upstream.time, "sleep", sleeps.append)
    result = data.fetch_dataset("consumption")
    reused = data.fetch_dataset("consumption")

    assert result is reused
    assert len(calls) == 2
    assert sleeps == [4.0]


def test_air_temperature_403_is_not_retried_or_replaced_with_fixture(monkeypatch):
    from backend.app.environment.weather import api as weather_api

    weather_api._AIR_TEMPERATURE_CACHE.clear()
    calls = []
    response = httpx.Response(403, request=httpx.Request("GET", "https://nea.test/air-temperature"))
    client = MagicMock()
    client.get.return_value = response
    context = MagicMock()
    context.__enter__.return_value = client
    monkeypatch.setattr(weather_api.httpx, "Client", MagicMock(return_value=context))
    source = weather_api.AirTemperatureApiClient(
        base_url="https://nea.test", api_key="test-key", offline=False,
        allow_fallback_fixture=False,
    )

    with pytest.raises(httpx.HTTPStatusError):
        source.fetch()
    with pytest.raises(httpx.HTTPStatusError):
        source.fetch()  # short negative cache; still no repeated provider call
    assert client.get.call_count == 1


def test_flood_403_is_not_retried_and_negative_cache_coalesces_clients(monkeypatch):
    from backend.app.environment.flood import api as flood_api

    flood_api._FLOOD_ALERT_CACHE.clear()
    response = httpx.Response(403, request=httpx.Request("GET", "https://pub.test/flood-alerts"))
    client = MagicMock()
    client.get.return_value = response
    context = MagicMock()
    context.__enter__.return_value = client
    monkeypatch.setattr(flood_api.httpx, "Client", MagicMock(return_value=context))
    first = flood_api.FloodAlertsApiClient(
        base_url="https://pub.test", account_key="test-key", offline=False,
        allow_fallback_fixture=False,
    )
    second = flood_api.FloodAlertsApiClient(
        base_url="https://pub.test", account_key="test-key", offline=False,
        allow_fallback_fixture=False,
    )

    for source in (first, second):
        with pytest.raises(httpx.HTTPStatusError):
            source.fetch()
    assert client.get.call_count == 1


def test_flood_v2_response_uses_official_endpoint_shape_and_optional_api_key(monkeypatch):
    from backend.app.environment.flood import api as flood_api

    monkeypatch.delenv("DATA_GOV_SG_API_KEY", raising=False)
    flood_api._FLOOD_ALERT_CACHE.clear()
    request = httpx.Request(
        "GET", "https://api-open.data.gov.sg/v2/real-time/api/weather/flood-alerts"
    )
    response = httpx.Response(200, request=request, json={
        "code": 0,
        "data": {"records": [{
            "datetime": "2026-10-25T09:55:00+08:00",
            "item": {
                "identifier": "PUB-123",
                "readings": [{
                    "area": {"areaDesc": "Test Road", "circle": [1.33, 103.87, 1]},
                    "description": "Flash flood reported.",
                    "event": "Flood",
                    "headline": "Flash Flood Alert",
                    "severity": "Minor",
                }],
            },
            "updatedTimestamp": "2026-10-25T10:00:00+08:00",
        }]},
        "errorMsg": "",
    })
    client = MagicMock()
    client.get.return_value = response
    context = MagicMock()
    context.__enter__.return_value = client
    monkeypatch.setattr(flood_api.httpx, "Client", MagicMock(return_value=context))

    snapshot = flood_api.FloodAlertsApiClient(offline=False).fetch()

    assert snapshot.is_live is True
    assert snapshot.endpoint == "https://api-open.data.gov.sg/v2/real-time/api/weather/flood-alerts"
    assert len(snapshot.alerts) == 1
    alert = snapshot.alerts[0]
    assert (alert.alert_id, alert.location, alert.alert_type, alert.severity) == (
        "PUB-123", "Test Road", "Flood", "Minor"
    )
    assert (alert.latitude, alert.longitude) == (1.33, 103.87)
    assert alert.issued_at.isoformat() == "2026-10-25T09:55:00+08:00"
    _, kwargs = client.get.call_args
    assert "Authorization" not in kwargs["headers"]
    assert "x-api-key" not in kwargs["headers"]


def test_flood_v2_empty_records_are_a_valid_empty_snapshot():
    from backend.app.environment.flood.api import FloodAlertsApiClient

    snapshot = FloodAlertsApiClient(offline=False)._normalize(
        {"code": 0, "data": {"records": []}, "errorMsg": ""}, is_live=True
    )
    assert snapshot.is_live is True
    assert snapshot.alerts == []


def test_flood_malformed_v2_response_is_not_misreported_as_no_alerts():
    from backend.app.environment.flood.api import FloodAlertsApiClient

    with pytest.raises(ValueError, match="response structure"):
        FloodAlertsApiClient(offline=False)._normalize({"data": {}}, is_live=True)


def test_construction_empty_upstream_response_is_explicit_and_negatively_cached(monkeypatch):
    from backend.app.planning.construction import data

    data.clear_construction_source_cache()
    calls = []

    class EmptyResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            calls.append(1)
            return b""

    monkeypatch.setattr(data.urllib.request, "urlopen", lambda *_args, **_kwargs: EmptyResponse())
    monkeypatch.setattr(data.time, "sleep", lambda _seconds: None)

    result = data._fetch_geojson_dataset("greenmark_geojson")
    again = data._fetch_geojson_dataset("greenmark_geojson")
    assert result.status == "unavailable"
    assert "Empty response" in (result.error or "")
    assert again is result
    assert len(calls) == data.MAX_RETRIES


def test_housing_dataset_calls_share_the_same_cached_fetch(monkeypatch):
    from backend.app.planning.housing import data

    data.clear_housing_source_cache()
    count = 0
    lock = threading.Lock()

    def fetch(_key, _limit):
        nonlocal count
        with lock:
            count += 1
        time.sleep(0.05)
        return data.SourceResult("median_resale", "Median", "HDB", "url", "available", records=[{"x": 1}])

    monkeypatch.setattr(data, "_fetch_dataset_uncached", fetch)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _index: data._fetch_dataset("median_resale"), range(6)))
    assert count == 1
    assert all(result is results[0] for result in results)


@pytest.mark.parametrize("module_path", [
    "backend.app.planning.housing.data",
    "backend.app.planning.construction.data",
])
def test_data_gov_modules_respect_retry_after_on_429(module_path, monkeypatch):
    import importlib

    module = importlib.import_module(module_path)
    from io import BytesIO
    from urllib.request import Request

    calls = []
    sleeps = []
    headers = Message()
    headers["Retry-After"] = "3"
    limited = urllib.error.HTTPError("https://data.gov.sg/test", 429, "rate limit", headers, None)

    class GoodResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"success":true,"result":{"records":[]}}'

    def urlopen(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise limited
        return GoodResponse()

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(module.time, "sleep", sleeps.append)
    assert module._fetch_with_retry(Request("https://data.gov.sg/test")) == {
        "success": True, "result": {"records": []}
    }
    assert len(calls) == 2
    assert sleeps == [3.0]
