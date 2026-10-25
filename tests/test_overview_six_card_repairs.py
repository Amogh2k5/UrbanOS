from __future__ import annotations

import asyncio
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.environment.flood import rainfall_clients
from backend.app.environment.flood.rainfall_clients import (
    SumatraForecastApiClient, SumatraLocationForecast,
)
from backend.app.environment.pm25.live_service import Pm25LiveSnapshotService
from backend.app.intelligence.contracts import CitySituationReport, DomainStatus
from backend.app.intelligence.normalize import build_card_metrics, normalize_domain_report
from backend.app.mobility.traffic.api import (
    TrafficSpeedBandV2, TrafficSpeedBandsV2ApiClient, TrafficSpeedBandsV2Snapshot,
)
from backend.app.mobility.traffic.data import snapshot_to_observations
from backend.app.overview import api as overview_api


def _run_async(coroutine):
    if sys.platform == "win32":
        class LocalLoop(asyncio.SelectorEventLoop):
            def _make_self_pipe(self):
                self._ssock = self._csock = None
                self._internal_fds = 0

            def _write_to_self(self):
                return None

            def _close_self_pipe(self):
                return None

        def loop_factory():
            loop = LocalLoop()
            loop._selector.select = lambda timeout=None: []
            return loop

        with asyncio.Runner(loop_factory=loop_factory) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def _speed_snapshot(speeds=(40.0, 60.0), at="2026-10-26T10:00:00+08:00"):
    segments = [TrafficSpeedBandV2(
        link_id=str(i), road_name="Road", road_category="A", speed_band=1,
        minimum_speed=speed - 5, maximum_speed=speed + 5,
        start_latitude=None, start_longitude=None, end_latitude=None,
        end_longitude=None, speed_midpoint=speed, zone_id=None, zone_name=None,
        observed_at=at,
    ) for i, speed in enumerate(speeds)]
    return TrafficSpeedBandsV2Snapshot(
        snapshot_at=at, source="live_api:LTA_traffic_speed_bands_v2",
        provider="LTA DataMall", endpoint="https://example.invalid/speedbands",
        segments=segments, is_live=True,
    )


def test_traffic_overview_uses_observed_speed_bands_not_prediction_bundle():
    snapshot = _speed_snapshot()

    class Client:
        def fetch(self):
            return snapshot

    state = SimpleNamespace(traffic_prediction_service=object())
    with patch("backend.app.mobility.traffic.api.TrafficSpeedBandsV2ApiClient", return_value=Client()):
        data = _run_async(overview_api._fetch_traffic_overview(state))

    assert data["overall_average_speed"] == 50.0
    assert data["generated_at"] == snapshot.snapshot_at
    assert "overall_predicted_speed" not in data
    assert "incident_count" not in data
    assert "overall_congestion_level" not in data


def test_traffic_overview_unavailable_when_live_bands_are_empty():
    empty = TrafficSpeedBandsV2Snapshot(
        snapshot_at="2026-10-26T10:00:00+08:00", source="live_api:LTA_traffic_speed_bands_v2",
        provider="LTA DataMall", endpoint="https://example.invalid/speedbands",
        segments=[], is_live=True,
    )

    class Client:
        def fetch(self):
            return empty

    with patch("backend.app.mobility.traffic.api.TrafficSpeedBandsV2ApiClient", return_value=Client()):
        data = _run_async(overview_api._fetch_traffic_overview(SimpleNamespace()))
    assert data["error"]


def test_overview_does_not_use_coordinator_prediction_for_traffic_card():
    overview_api._OVERVIEW_SUMMARY_CACHE.clear()
    report = CitySituationReport(generated_at="2026-10-26T10:00:00+08:00", domain_status={
        "traffic": DomainStatus(
            domain="traffic", available=True, overall_status="CRITICAL",
            key_metrics={"headline": {"label": "Average Speed", "value": 99, "unit": "km/h"}},
        ),
    })

    async def observed(_state):
        return {
            "overall_average_speed": 42.5,
            "source_status": "live",
            "generated_at": "2026-10-26T09:59:00+08:00",
        }

    # The cached report contains a prediction; only the observed source fetch
    # may populate the Overview traffic card.
    with patch.object(overview_api, "peek_city_report_cached", return_value=(report, {})), \
         patch.object(overview_api, "_fetch_traffic_overview", observed):
        response = _run_async(overview_api.get_overview_city(
            SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        ))
    traffic = next(card for card in response.modules if card.id == "traffic")
    assert traffic.kpi is not None and traffic.kpi.value == 42.5
    assert traffic.updated_at == "2026-10-26T09:59:00+08:00"
    overview_api._OVERVIEW_SUMMARY_CACHE.clear()


def test_traffic_missing_speed_interval_is_not_normalized_to_zero():
    client = TrafficSpeedBandsV2ApiClient(api_key="test-key")
    snapshot = client._normalize({"value": [{"LinkID": "x", "SpeedBand": 2}]})
    assert len(snapshot.segments) == 1
    assert snapshot.segments[0].speed_midpoint is None
    assert snapshot_to_observations(snapshot) == []


def test_traffic_speed_band_source_cache_coalesces_threads():
    from backend.app.mobility.traffic import api as traffic_api

    traffic_api._SPEED_BANDS_CACHE.clear()
    client = TrafficSpeedBandsV2ApiClient(api_key="test-key")
    calls = 0
    lock = threading.Lock()

    def fetch():
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(0.03)
        return _speed_snapshot((42.0,))

    with patch.object(client, "_fetch_uncached", side_effect=fetch):
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda _: client.fetch(), range(5)))
    assert calls == 1
    assert all(result.snapshot_at == results[0].snapshot_at for result in results)
    traffic_api._SPEED_BANDS_CACHE.clear()


def _forecast(loc, rainfall):
    return SumatraLocationForecast(
        group=loc["group"], location=loc["name"], adm4=loc["adm4"],
        latitude=loc["lat"], longitude=loc["lon"],
        forecast_time_local="2026-10-26T10:00:00+08:00",
        weather_condition="Cloudy", temperature_c=None, humidity_pct=None,
        wind_speed_ms=None, wind_direction="", cloud_cover_pct=None,
        rainfall_mm=rainfall, source="live_api:BMKG_forecast",
    )


def test_sumatra_fetch_is_bounded_partial_and_single_flight_cached():
    rainfall_clients._SUMATRA_CACHE.clear()
    client = SumatraForecastApiClient(base_url="https://example.invalid/forecast")
    active = 0
    max_active = 0
    calls = 0
    lock = threading.Lock()

    def fetch_location(loc):
        nonlocal active, max_active, calls
        with lock:
            active += 1
            calls += 1
            max_active = max(max_active, active)
        time.sleep(0.006)
        with lock:
            active -= 1
        if loc is rainfall_clients._ALL_BMKG_LOCATIONS[0]:
            return _forecast(loc, 0.0)  # valid observed forecast value, not a fallback
        return None

    with patch.object(client, "_fetch_location", side_effect=fetch_location):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _: client.fetch(), range(2)))
        third = client.fetch()

    assert calls == len(rainfall_clients._ALL_BMKG_LOCATIONS)
    assert 1 < max_active <= rainfall_clients._SUMATRA_MAX_WORKERS
    assert first.partial is True
    assert len(first.failed_locations) == len(rainfall_clients._ALL_BMKG_LOCATIONS) - 1
    assert first.groups
    assert next(iter(first.groups.values())).max_rainfall_mm == 0.0
    assert second is first and third is first
    rainfall_clients._SUMATRA_CACHE.clear()


def test_sumatra_missing_measurements_remain_null():
    client = SumatraForecastApiClient()
    loc = rainfall_clients._ALL_BMKG_LOCATIONS[0]
    result = client._aggregate_by_group([_forecast(loc, None)])
    summary = next(iter(result.values()))
    assert summary.max_rainfall_mm is None
    assert summary.has_rain is None
    assert summary.avg_wind_speed_ms is None
    assert summary.max_cloud_cover_pct is None


def _pm25_rows(latest="2026-10-26T09:00:00+08:00"):
    return {
        region: {
            "region": region, "value": idx + 1, "observed_at": latest,
            "source": "stored:NEA_pm25", "unit": "µg/m3",
        }
        for idx, region in enumerate(("north", "south", "east", "west", "central"))
    }


def test_pm25_snapshot_reads_valid_store_without_live_refresh():
    rows = _pm25_rows()

    class Store:
        def get_latest_observation_timestamp(self):
            return next(iter(rows.values()))["observed_at"] if rows else None

        def get_latest_snapshot(self):
            return rows

    service = Pm25LiveSnapshotService(api_client=SimpleNamespace(fetch=lambda: (_ for _ in ()).throw(AssertionError("API called"))))
    with patch("backend.app.environment.pm25.data.Pm25ObservationStore", Store):
        snapshot = service.snapshot()
    assert snapshot is not None and snapshot.is_live is False
    assert snapshot.raw_issue_timestamp == "2026-10-26T09:00:00+08:00"
    assert snapshot.regions["north"].value == 1
    assert snapshot.regions["north"].observed_at == snapshot.raw_issue_timestamp


def test_pm25_empty_or_incomplete_store_stays_unavailable():
    rows = {}

    class Store:
        def get_latest_observation_timestamp(self):
            return "2026-10-26T09:00:00+08:00" if rows else None

        def get_latest_snapshot(self):
            return rows

    with patch("backend.app.environment.pm25.data.Pm25ObservationStore", Store):
        assert Pm25LiveSnapshotService().snapshot() is None
        rows.update(_pm25_rows())
        rows.pop("east")
        assert Pm25LiveSnapshotService().snapshot() is None
        rows.clear()
        rows.update(_pm25_rows())
        rows["north"]["value"] = float("nan")
        assert Pm25LiveSnapshotService().snapshot() is None


def test_pm25_failed_live_refresh_retains_persisted_snapshot_as_stale():
    rows = _pm25_rows()

    class Store:
        def get_latest_observation_timestamp(self):
            return "2026-10-26T09:00:00+08:00"

        def get_latest_snapshot(self):
            return rows

    service = Pm25LiveSnapshotService(api_client=SimpleNamespace(fetch=lambda: (_ for _ in ()).throw(RuntimeError("offline"))))
    with patch("backend.app.environment.pm25.data.Pm25ObservationStore", Store):
        before = service.snapshot()
        service._refresh()
        after = service.snapshot()
    assert before is after and not after.is_live
    data = overview_api._peek_pm25_summary(SimpleNamespace(pm25_live_service=service))
    assert data["source_status"] == "stale"
    assert data["generated_at"] == "2026-10-26T09:00:00+08:00"


def test_water_historical_metrics_are_partial_while_unknown_risk_stays_unavailable():
    report = {
        "overall_risk": "UNKNOWN",
        "usage": {
            "potable_total": {"value": 515.5, "unit": "million m³", "period": "2024"},
            "newater": 153.8,
        },
        "drain": {"readings_available": False, "sensors_with_readings": 0, "sensor_count": 0},
    }
    status = normalize_domain_report("water", report)
    metrics = [overview_api.ModuleMetric(**item) for item in build_card_metrics("water", report)]
    assert status.overall_status == "UNAVAILABLE"
    assert next(m for m in metrics if m.key == "potable_sales").value == 515.5
    assert next(m for m in metrics if m.key == "drain_sensors").value is None
    assert overview_api._card_data_state(status, metrics) == "partial"


def test_water_without_historical_or_live_metrics_is_unavailable():
    report = {"overall_risk": "UNKNOWN", "usage": {}, "drain": {"readings_available": False}}
    status = normalize_domain_report("water", report)
    metrics = [overview_api.ModuleMetric(**item) for item in build_card_metrics("water", report)]
    assert all(metric.value is None for metric in metrics)
    assert overview_api._card_data_state(status, metrics) == "unavailable"


def test_construction_overview_uses_source_update_time_or_leaves_it_unknown():
    report = SimpleNamespace(model_dump=lambda: {
        "generated_at": "2026-10-26T10:05:00+08:00", "status": "PARTIAL",
        "sources": [
            {"last_updated_at": "2026-10-20T00:00:00+08:00"},
            {"last_updated_at": None},
        ],
    })
    data = overview_api._construction_overview_data(report)
    assert data["generated_at"] == "2026-10-20T00:00:00+08:00"
    assert data["source_status"] == "partial"

    no_publication = SimpleNamespace(model_dump=lambda: {
        "generated_at": "2026-10-26T10:05:00+08:00", "status": "OK", "sources": [],
    })
    assert overview_api._construction_overview_data(no_publication)["generated_at"] is None


def test_construction_unavailable_source_does_not_become_zero_records():
    data = {
        "status": "PARTIAL",
        "greenmark_buildings": [],
        "pipeline_records": [],
        "sources": [
            {"key": "greenmark_buildings", "status": "unavailable"},
            {"key": "ura_construction_pipeline", "status": "unavailable"},
        ],
    }
    assert normalize_domain_report("construction", data).overall_status == "UNAVAILABLE"
    assert all(metric["value"] is None for metric in build_card_metrics("construction", data))


def test_construction_status_and_counts_follow_source_success():
    data = {
        "status": "OK",
        "greenmark_buildings": [{"id": "a"}],
        "pipeline_records": [],
        "sources": [
            {"key": "greenmark_buildings", "status": "available"},
            {"key": "ura_construction_pipeline", "status": "empty"},
        ],
    }
    assert normalize_domain_report("construction", data).overall_status == "NORMAL"
    assert [metric["value"] for metric in build_card_metrics("construction", data)] == [1, 0]


def test_fire_historical_only_report_does_not_claim_zero_active_incidents():
    data = {
        "active_incident_count": None,
        "critical_incident_count": None,
        "total_physical_crime_2025": None,
        "historical_fire_counts": [{"year": 2024, "fires": 1200}],
        "source_status": "historical_only",
    }
    assert normalize_domain_report("fire", data).overall_status == "UNAVAILABLE"
    assert build_card_metrics("fire", data)[0]["value"] is None
