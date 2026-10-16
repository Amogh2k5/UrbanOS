"""Regression tests for the Overview domain audit.

Every test pins a defect that was observed on the *running* backend, not only
in unit tests. Findings and their evidence are recorded in each docstring.

1. ``_fetch_traffic_incidents`` and ``_fetch_flood_alerts`` took no arguments
   while the alert loop called them with the request cache. The resulting
   ``TypeError`` was swallowed by the loop's ``except Exception``, so both
   sources contributed zero alerts on every request. Confirmed in the running
   server's log.
2. Transit counted stored alert rows, not distinct advisories. 7 rows held 1
   distinct message; the Overview KPI read 5, then 19, for the same advisory.
3. Transit dropped ``category`` when storing, defaulting every row to ``"rail"``.
   A bus diversion was therefore stored - and counted - as a train alert.
4. NEA forecast code ``TL`` ("Thundery Showers") was reported as ``normal``
   because only TS and HR were listed.
5. Water reported ``normal`` while its own ``overall_risk`` was ``UNKNOWN``.
6. PUB flood alerts fell back to the deterministic fixture, publishing two
   invented 2024 "Flash Flood" advisories as live alerts.
7. The roads fetcher blocked the event loop: a 2.1s request measured 24.1s while
   it ran, and the Overview took 45s.
"""
from __future__ import annotations

import asyncio
import inspect
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from backend.app.intelligence.normalize import build_kpi, determine_status
from backend.app.overview import api

SG = timezone(timedelta(hours=8))


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ============================================================ 1. signatures
class TestAlertFetcherSignatures:
    """Regression: a signature mismatch silently emptied two alert sources."""

    ALERTERS = [
        "_fetch_traffic_incidents",
        "_fetch_fire_incidents",
        "_fetch_flood_alerts",
        "_fetch_crime_incidents",
        "_fetch_water_incidents",
    ]

    @pytest.mark.parametrize("name", ALERTERS)
    def test_every_alert_fetcher_accepts_the_request_cache(self, name):
        fn = getattr(api, name)
        assert len(inspect.signature(fn).parameters) >= 1, (
            f"{name} takes no argument but the endpoint calls it with the "
            "request cache; the TypeError is swallowed and the source goes silent"
        )

    @pytest.mark.parametrize("name", ALERTERS)
    def test_every_alert_fetcher_is_callable_the_way_the_endpoint_calls_it(self, name):
        """Belt-and-braces: actually invoke it with one positional argument."""
        fn = getattr(api, name)
        with patch.object(api, "city_report_cached", return_value=None):
            batch = _run(fn({}))
        assert isinstance(batch, list)


# ================================================================ 2. transit
class TestTransitDistinctAlerts:
    def test_repeated_sightings_of_one_advisory_count_once(self, tmp_path):
        from backend.app.mobility.transit.data import TransitDataStore, StoredTrainAlert

        store = TransitDataStore(db_path=tmp_path / "t.db")
        created = datetime.now(SG).isoformat()
        rows = [
            StoredTrainAlert(
                id=0, line="UNKNOWN", direction=None, station=None,
                message="Bus services diverted", status=None, source="live_api",
                fetched_at=(datetime.now(SG) + timedelta(minutes=i)).isoformat(),
                created_at=created, category="bus",
            )
            for i in range(7)
        ]
        store.insert_train_alerts(rows)

        # Seven sightings of one advisory...
        with store._conn() as conn:
            raw = conn.execute("SELECT COUNT(*) FROM train_alerts").fetchone()[0]
        assert raw == 7

        # ...are reported once.
        distinct = store.get_latest_train_alerts(limit=50)
        assert len(distinct) == 1
        assert distinct[0].message == "Bus services diverted"

    def test_distinct_advisories_are_all_kept(self, tmp_path):
        from backend.app.mobility.transit.data import TransitDataStore, StoredTrainAlert

        store = TransitDataStore(db_path=tmp_path / "t.db")
        created = datetime.now(SG).isoformat()
        rows = [
            StoredTrainAlert(
                id=0, line=line, direction=None, station=None, message=msg,
                status=None, source="live_api",
                fetched_at=datetime.now(SG).isoformat(),
                created_at=created, category="rail",
            )
            for line, msg in [("EWL", "Signal fault"), ("NSL", "Track fault")]
        ]
        store.insert_train_alerts(rows)
        assert len(store.get_latest_train_alerts(limit=50)) == 2

    def test_limit_still_applies_to_distinct_alerts(self, tmp_path):
        from backend.app.mobility.transit.data import TransitDataStore, StoredTrainAlert

        store = TransitDataStore(db_path=tmp_path / "t.db")
        created = datetime.now(SG).isoformat()
        store.insert_train_alerts([
            StoredTrainAlert(
                id=0, line=f"L{i}", direction=None, station=None, message=f"msg {i}",
                status=None, source="live_api",
                fetched_at=datetime.now(SG).isoformat(),
                created_at=created, category="rail",
            )
            for i in range(10)
        ])
        assert len(store.get_latest_train_alerts(limit=3)) == 3


class TestTransitCategoryPropagation:
    def test_the_classified_category_reaches_storage(self):
        """Regression: category was omitted, so every row defaulted to 'rail'
        and a bus diversion was counted as a train alert."""
        from backend.app.mobility.transit.api import TrainServiceAlert
        from backend.app.mobility.transit.data import train_alerts_snapshot_to_stored

        snapshot = MagicMock()
        snapshot.alerts = [
            TrainServiceAlert(
                line="UNKNOWN", direction=None, station=None,
                message="Bus services 170 and 170X have been diverted from "
                        "Woodlands Road",
                status=None, source="live_api:LTA_train_alerts",
                fetched_at="2026-10-16T10:06:00+08:00", category="bus",
            )
        ]
        stored = train_alerts_snapshot_to_stored(snapshot)
        assert stored[0].category == "bus"

    def test_a_missing_category_does_not_become_none(self):
        from backend.app.mobility.transit.data import train_alerts_snapshot_to_stored

        snapshot = MagicMock()
        alert = MagicMock(spec=["line", "direction", "station", "message",
                                "status", "source", "fetched_at"])
        alert.line, alert.direction, alert.station = "EWL", None, None
        alert.message, alert.status = "Signal fault", None
        alert.source, alert.fetched_at = "s", "t"
        snapshot.alerts = [alert]
        stored = train_alerts_snapshot_to_stored(snapshot)
        assert stored[0].category == "rail"

    def test_the_bus_advisory_is_not_counted_as_a_train_alert(self, tmp_path):
        """End to end: a stored bus alert must not raise the train-alert KPI."""
        from backend.app.mobility.transit.data import TransitDataStore, StoredTrainAlert

        store = TransitDataStore(db_path=tmp_path / "t.db")
        store.insert_train_alerts([
            StoredTrainAlert(
                id=0, line="UNKNOWN", direction=None, station=None,
                message="Bus services diverted", status=None, source="s",
                fetched_at=datetime.now(SG).isoformat(),
                created_at=datetime.now(SG).isoformat(), category="bus",
            )
        ])
        alerts = store.get_latest_train_alerts(limit=60)
        train_count = sum(1 for a in alerts if a.category in ("metro", "rail"))
        assert train_count == 0


# =============================================================== 4. weather
class TestWeatherForecastCodes:
    @pytest.mark.parametrize("code", ["TS", "TL", "TRW", "HR"])
    def test_convective_codes_are_elevated(self, code):
        assert determine_status("weather", {"general": {"forecast_code": code}}) == "elevated"

    @pytest.mark.parametrize("code", ["FW", "DR", "SW", "SG"])
    def test_settled_codes_stay_normal(self, code):
        assert determine_status("weather", {"general": {"forecast_code": code}}) == "normal"

    def test_the_live_reading_that_was_reported_normal(self):
        """The actual payload from the running API."""
        payload = {"general": {"forecast_code": "TL", "forecast_text": "Thundery Showers"}}
        assert determine_status("weather", payload) == "elevated"

    def test_agrees_with_the_flood_agent_about_thunderstorms(self):
        """One reading of the same source must not mean two different things."""
        from backend.app.environment.flood.agent import assess_risk, FloodAgentState

        state = FloodAgentState()
        state.nea_weather = MagicMock()
        state.nea_weather.is_live = True
        state.nea_weather.source = "live_api:NEA_24h_weather"
        state.nea_weather.general.forecast_code = "TL"
        state.nea_weather.general.wind_direction = "NE"
        assess_risk(state)
        assert any("Thunderstorms" in f for f in state.primary_risk_factors)


# ================================================================= 5. water
class TestWaterUnknownIsNotNormal:
    def test_unknown_risk_is_unavailable(self):
        assert determine_status("water", {"overall_risk": "UNKNOWN"}) == "unavailable"

    def test_absent_risk_is_unavailable(self):
        assert determine_status("water", {}) == "unavailable"

    @pytest.mark.parametrize("risk,expected", [
        ("LOW", "normal"), ("MODERATE", "elevated"), ("HIGH", "elevated"),
        ("CRITICAL", "critical"),
    ])
    def test_real_risk_levels_are_unchanged(self, risk, expected):
        assert determine_status("water", {"overall_risk": risk}) == expected

    def test_the_running_payload_that_reported_normal(self):
        """Exactly what /api/water/report returned during the audit."""
        payload = {"overall_risk": "UNKNOWN", "overall_status": "UNKNOWN"}
        assert determine_status("water", payload) == "unavailable"

    def test_kpi_is_unaffected(self):
        """The real potable-sales reading is still available as a metric."""
        payload = {"usage": {"potable_total": {"value": 515.5, "unit": "million m3"}}}
        assert build_kpi("water", payload) is not None


# =============================================================== 6. flood
class TestFloodFixtureIsNotPublishedAsLive:
    def test_the_alert_source_refuses_the_fixture(self):
        from backend.app.environment.flood.api import FloodAlertsApiClient

        client = FloodAlertsApiClient(offline=False, allow_fallback_fixture=False)
        assert client.allow_fallback_fixture is False
        with pytest.raises(ValueError):
            client.fetch()

    def test_no_fixture_alert_reaches_the_overview(self):
        batch = _run(api._fetch_flood_alerts({}))
        assert list(batch) == []
        assert batch.source_ok is False

    def test_real_flood_alerts_are_still_published(self):
        from backend.app.environment.flood.api import FloodAlert, FloodAlertsSnapshot

        snap = FloodAlertsSnapshot(
            snapshot_at="2026-10-16T23:00:00+08:00", source="live_api:PUB_flood_alerts",
            provider="PUB", endpoint="e", is_live=True,
            alerts=[FloodAlert(
                alert_id="F1", location="Orchard Road", latitude=None, longitude=None,
                alert_type="Flash Flood", severity="High", message="Heavy rain",
                issued_at=datetime(2026, 10, 16, 22, 45, tzinfo=SG),
                source="live_api:PUB_flood_alerts", zone_id="Z1",
            )],
        )
        with patch("backend.app.environment.flood.api.FloodAlertsApiClient",
                   return_value=MagicMock(fetch=lambda: snap)):
            batch = _run(api._fetch_flood_alerts({}))
        assert len(batch) == 1
        assert batch[0]["title"] == "Flash Flood"

    def test_the_app_state_client_cannot_serve_the_fixture(self):
        """The /kpi/live/flood route must not return the 2024 fixture."""
        import backend.app.main as main_mod

        source = Path(main_mod.__file__).read_text(encoding="utf-8-sig")
        assert "FloodAlertsApiClient(\n        offline=offline, allow_fallback_fixture=False" \
            in source or "allow_fallback_fixture=False" in source


# ============================================================ 7. event loop
class TestRoadsFetcherDoesNotBlockTheLoop:
    def test_the_blocking_work_runs_in_a_worker_thread(self):
        """Regression: synchronous HTTP ran on the event loop, so a 2.1s
        request measured 24.1s while the Overview was assembling."""
        assert hasattr(api, "_roads_overview_sync")

        import asyncio as _asyncio

        async def probe():
            ticks = 0

            async def ticker():
                nonlocal ticks
                while True:
                    ticks += 1
                    await _asyncio.sleep(0.01)

            t = _asyncio.create_task(ticker())
            with patch.object(api, "_roads_overview_sync",
                              side_effect=lambda: (_ for _ in ()).throw(RuntimeError("x"))):
                await api._fetch_roads_overview(MagicMock())
            t.cancel()
            return ticks

        # The loop kept running while the fetch awaited, which it could not do
        # if the work were inline.
        assert _run(probe()) > 0

    def test_failures_are_still_reported_as_unavailable(self):
        with patch.object(api, "_roads_overview_sync",
                          side_effect=RuntimeError("upstream down")):
            data = _run(api._fetch_roads_overview(MagicMock()))
        assert data["error"]
        assert determine_status("roads", data) == "unavailable"