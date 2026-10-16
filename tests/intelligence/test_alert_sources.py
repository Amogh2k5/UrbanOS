"""Regression tests for Issue 15: traffic, flood and crime alert generation.

Three confirmed defects are pinned here.

1. ``_fetch_traffic_incidents`` read ``inc.type`` and ``inc.timestamp``.
   ``TrafficIncident`` has ``incident_type`` and **no timestamp at all**, so the
   fetcher raised ``AttributeError`` on every call and the bare
   ``except Exception: return []`` swallowed it. Traffic alerts were therefore
   permanently empty and nothing was logged.

2. ``_fetch_flood_alerts`` read ``alert.type``. ``FloodAlert`` names the field
   ``alert_type`` (its ``to_dict`` renames it to ``"type"``, which is what made
   the dataclass read look wrong). Flood alerts were permanently empty.

3. ``_fetch_crime_incidents`` iterated the ``crime_cases`` datastore as if it
   were an incident feed. Those records are annual aggregate rows shaped
   ``{"DataSeries": ..., "2025": ...}`` - no ``offence``, ``year`` or ``area``
   key exists - so every field fell back to a placeholder and the endpoint
   rendered three identical ``"Crime Case" / "Incident - N/A"`` rows with an
   empty timestamp and an invented ``"elevated"`` severity.

Everything here is mocked: no network, no live API, no LLM.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from backend.app.environment.flood.api import FloodAlert, FloodAlertsSnapshot
from backend.app.mobility.traffic.api import (
    TrafficIncident, TrafficIncidentsSnapshot,
)
from backend.app.overview import api


SG = timezone(timedelta(hours=8))


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# --------------------------------------------------------------- model facts
class TestSourceModelsMatchWhatTheFetchersRead:
    """The defects were field-name mismatches, so pin the real field names."""

    def test_traffic_incident_has_no_type_or_timestamp_attribute(self):
        """The two names the old fetcher used do not exist. If a future change
        adds them, this test tells the fetcher to be reviewed."""
        inc = TrafficIncident(
            incident_type="Heavy Traffic", latitude=None, longitude=None,
            message="Heavy traffic", source="live_api:LTA",
        )
        assert not hasattr(inc, "type")
        assert not hasattr(inc, "timestamp")
        assert inc.incident_type == "Heavy Traffic"

    def test_flood_alert_has_alert_type_not_type(self):
        alert = FloodAlert(
            alert_id="F1", location="Orchard Road", latitude=None, longitude=None,
            alert_type="Flash Flood", severity="High", message="Heavy rain",
            issued_at=datetime(2026, 10, 15, 9, 0, tzinfo=SG), source="live_api:PUB",
        )
        assert not hasattr(alert, "type")
        assert alert.alert_type == "Flash Flood"

    def test_crime_dataset_rows_carry_no_incident_fields(self):
        """The real shape of a crime_cases record, per tests/crime fixtures."""
        row = {"DataSeries": "Physical Crime Cases Recorded", "2025": "20857"}
        for key in ("offence", "year", "area"):
            assert key not in row


# ------------------------------------------------------------------ traffic
def _traffic_snapshot(incidents: List[TrafficIncident]) -> TrafficIncidentsSnapshot:
    return TrafficIncidentsSnapshot(
        snapshot_at="2026-10-15T09:00:00+08:00",
        source="live_api:LTA_TrafficIncidents",
        provider="LTA DataMall",
        endpoint="https://api.data.gov.sg/v1/traffic/incidents",
        incidents=incidents,
        is_live=True,
    )


class TestTrafficAlerts:
    def test_valid_incidents_are_returned_with_real_fields(self):
        snap = _traffic_snapshot([
            TrafficIncident(
                incident_type="Heavy Traffic", latitude=None, longitude=None,
                message="Heavy traffic on the AYE.", source="live_api:LTA",
                zone_id="SG_CENTRAL_SOUTH", zone_name="Central South",
            ),
        ])
        with patch_client("backend.app.mobility.traffic.api.TrafficIncidentsApiClient",
                         snap):
            alerts = _run(api._fetch_traffic_incidents())

        assert len(alerts) == 1
        alert = alerts[0]
        assert alert["domain"] == "traffic"
        assert alert["title"] == "Heavy Traffic"
        assert "Heavy traffic on the AYE." in alert["description"]
        assert "Central South" in alert["description"]
        assert alert["affected_zones"] == ["SG_CENTRAL_SOUTH"]

    def test_timestamp_comes_from_the_snapshot(self):
        """No per-incident timestamp exists, so the snapshot time is used
        rather than inventing one."""
        snap = _traffic_snapshot([
            TrafficIncident(incident_type="Accident", latitude=None, longitude=None,
                            message="Collision", source="live_api:LTA"),
        ])
        with patch_client("backend.app.mobility.traffic.api.TrafficIncidentsApiClient",
                         snap):
            alerts = _run(api._fetch_traffic_incidents())

        assert alerts[0]["timestamp"] == "2026-10-15T09:00:00+08:00"

    def test_severity_is_not_inferred(self):
        """The LTA feed publishes no severity, so none may be claimed."""
        snap = _traffic_snapshot([
            TrafficIncident(incident_type="Accident", latitude=None, longitude=None,
                            message="Collision", source="live_api:LTA"),
        ])
        with patch_client("backend.app.mobility.traffic.api.TrafficIncidentsApiClient",
                         snap):
            alerts = _run(api._fetch_traffic_incidents())

        assert alerts[0]["severity"] == "info"

    def test_empty_response_is_a_successful_empty_source(self):
        snap = _traffic_snapshot([])
        with patch_client("backend.app.mobility.traffic.api.TrafficIncidentsApiClient",
                         snap):
            batch = _run(api._fetch_traffic_incidents())

        assert list(batch) == []
        assert batch.source_ok is True
        assert batch.source_error is None

    def test_source_failure_is_flagged_and_logged(self, caplog):
        with patch_client("backend.app.mobility.traffic.api.TrafficIncidentsApiClient",
                          error=RuntimeError("api.data.gov.sg connection refused")):
            with caplog.at_level("WARNING"):
                batch = _run(api._fetch_traffic_incidents())

        assert list(batch) == []
        assert batch.source_ok is False
        assert "unavailable" in batch.source_error
        # The failure is recorded, not silently swallowed.
        assert "Traffic incident source unavailable" in caplog.text
        # ...and the response never carries the raw exception.
        assert "connection refused" not in batch.source_error
        assert "data.gov.sg" not in batch.source_error

    def test_at_most_three_alerts(self):
        snap = _traffic_snapshot([
            TrafficIncident(incident_type=f"Incident {i}", latitude=None,
                            longitude=None, message="m", source="s")
            for i in range(7)
        ])
        with patch_client("backend.app.mobility.traffic.api.TrafficIncidentsApiClient",
                         snap):
            alerts = _run(api._fetch_traffic_incidents())
        assert len(alerts) == 3

    def test_missing_zone_is_not_an_empty_string_entry(self):
        snap = _traffic_snapshot([
            TrafficIncident(incident_type="Accident", latitude=None, longitude=None,
                            message="Collision", source="s"),
        ])
        with patch_client("backend.app.mobility.traffic.api.TrafficIncidentsApiClient",
                         snap):
            alerts = _run(api._fetch_traffic_incidents())
        assert alerts[0]["affected_zones"] == []


# -------------------------------------------------------------------- flood
def _flood_snapshot(alerts: List[FloodAlert]) -> FloodAlertsSnapshot:
    return FloodAlertsSnapshot(
        snapshot_at="2026-10-15T09:00:00+08:00",
        source="live_api:PUB_flood_alerts",
        provider="PUB / data.gov.sg",
        endpoint="https://api.data.gov.sg/v1/environment/flood-alerts",
        alerts=alerts,
        is_live=True,
    )


def _flood_alert(**overrides: Any) -> FloodAlert:
    base: Dict[str, Any] = dict(
        alert_id="FLD_20261015_001",
        location="Orchard Road / Stamford Canal",
        latitude=1.3033, longitude=103.8317,
        alert_type="Flash Flood", severity="High",
        message="Heavy rain causing flash floods at Orchard Road.",
        issued_at=datetime(2026, 10, 15, 8, 45, tzinfo=SG),
        source="live_api:PUB_flood_alerts",
        zone_id="SG_CENTRAL_SOUTH", zone_name="Central South",
    )
    base.update(overrides)
    return FloodAlert(**base)


class TestFloodAlerts:
    def test_valid_alerts_are_returned_with_real_fields(self):
        snap = _flood_snapshot([_flood_alert()])
        with patch_client("backend.app.environment.flood.api.FloodAlertsApiClient",
                         snap):
            alerts = _run(api._fetch_flood_alerts())

        assert len(alerts) == 1
        alert = alerts[0]
        assert alert["domain"] == "flood"
        assert alert["title"] == "Flash Flood"
        assert "Heavy rain causing flash floods" in alert["description"]
        assert "Orchard Road" in alert["description"]
        assert alert["affected_zones"] == ["SG_CENTRAL_SOUTH"]

    def test_publisher_severity_is_passed_through(self):
        snap = _flood_snapshot([_flood_alert(severity="Moderate")])
        with patch_client("backend.app.environment.flood.api.FloodAlertsApiClient",
                         snap):
            alerts = _run(api._fetch_flood_alerts())
        assert alerts[0]["severity"] == "Moderate"

    def test_alert_issue_time_is_used(self):
        snap = _flood_snapshot([_flood_alert()])
        with patch_client("backend.app.environment.flood.api.FloodAlertsApiClient",
                         snap):
            alerts = _run(api._fetch_flood_alerts())
        assert alerts[0]["timestamp"] == "2026-10-15T08:45:00+08:00"

    def test_zero_alerts_is_successful_and_empty_not_manufactured(self):
        """Regression: an empty PUB response must never be turned into a fake
        alert, and must not be reported as a failed source."""
        snap = _flood_snapshot([])
        with patch_client("backend.app.environment.flood.api.FloodAlertsApiClient",
                         snap):
            batch = _run(api._fetch_flood_alerts())

        assert list(batch) == []
        assert batch.source_ok is True

    def test_source_failure_is_flagged_and_logged(self, caplog):
        with patch_client("backend.app.environment.flood.api.FloodAlertsApiClient",
                          error=ValueError("DATA_GOV_SG_API_KEY not configured")):
            with caplog.at_level("WARNING"):
                batch = _run(api._fetch_flood_alerts())

        assert list(batch) == []
        assert batch.source_ok is False
        assert "Flood alert source unavailable" in caplog.text
        # Credentials must never reach an API client.
        assert "API_KEY" not in batch.source_error

    def test_at_most_two_alerts(self):
        snap = _flood_snapshot([_flood_alert(alert_id=f"F{i}") for i in range(5)])
        with patch_client("backend.app.environment.flood.api.FloodAlertsApiClient",
                         snap):
            alerts = _run(api._fetch_flood_alerts())
        assert len(alerts) == 2


# -------------------------------------------------------------------- crime
def _crime_report(**overrides: Any):
    from backend.app.safety.crime.models import CrimeReport

    base: Dict[str, Any] = dict(
        generated_at=datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc),
        source_status="available",
        data_period="2011-2025 for selected major offences/arrests/NPC",
        total_physical_crime_2025=20857,
        total_scams_cybercrime_2025=41974,
        total_scams_2025=37308,
    )
    base.update(overrides)
    return CrimeReport(**base)


class TestCrimeAlerts:
    def test_no_placeholder_incident_rows_are_produced(self):
        """Regression: the old fetcher emitted
        title='Crime Case' / description='Incident - N/A' / timestamp='' /
        severity='elevated', three times over."""
        with patch_client("backend.app.safety.crime.agent.run_crime_agent",
                         _crime_report()):
            alerts = _run(api._fetch_crime_incidents())

        for alert in alerts:
            assert "Crime Case" not in alert["title"]
            assert "N/A" not in alert["description"]
            assert alert["timestamp"] != ""
            assert alert["severity"] != "elevated"

    def test_a_single_statistics_summary_is_emitted(self):
        with patch_client("backend.app.safety.crime.agent.run_crime_agent",
                         _crime_report()):
            alerts = _run(api._fetch_crime_incidents())

        assert len(alerts) == 1
        alert = alerts[0]
        assert alert["domain"] == "crime"
        assert "annual statistics" in alert["title"].lower()
        assert "20,857" in alert["description"]
        assert "41,974" in alert["description"]

    def test_the_summary_states_it_is_not_live_incident_data(self):
        with patch_client("backend.app.safety.crime.agent.run_crime_agent",
                         _crime_report()):
            alerts = _run(api._fetch_crime_incidents())

        description = alerts[0]["description"].lower()
        assert "annual" in description
        assert "not live incidents" in description
        assert "no incident-level crime feed" in description

    def test_the_summary_carries_no_invented_location(self):
        with patch_client("backend.app.safety.crime.agent.run_crime_agent",
                         _crime_report()):
            alerts = _run(api._fetch_crime_incidents())
        assert alerts[0]["affected_zones"] == []

    def test_unknown_data_period_is_stated_not_invented(self):
        with patch_client("backend.app.safety.crime.agent.run_crime_agent",
                         _crime_report(data_period="unknown")):
            alerts = _run(api._fetch_crime_incidents())
        assert "period not stated" in alerts[0]["description"]

    def test_unavailable_statistics_are_not_summarised(self, caplog):
        """No totals means nothing to say - never a placeholder row."""
        report = _crime_report(source_status="unavailable",
                               total_physical_crime_2025=None,
                               total_scams_cybercrime_2025=None,
                               total_scams_2025=None)
        with patch_client("backend.app.safety.crime.agent.run_crime_agent", report):
            with caplog.at_level("WARNING"):
                batch = _run(api._fetch_crime_incidents())

        assert list(batch) == []
        assert batch.source_ok is False
        assert "Crime statistics unavailable" in caplog.text

    def test_loaded_but_empty_statistics_is_a_successful_empty_source(self):
        """Statistics loaded, but no 2025 totals: genuinely nothing to report."""
        report = _crime_report(source_status="partial",
                               total_physical_crime_2025=None,
                               total_scams_cybercrime_2025=None,
                               total_scams_2025=None)
        with patch_client("backend.app.safety.crime.agent.run_crime_agent", report):
            batch = _run(api._fetch_crime_incidents())

        assert list(batch) == []
        assert batch.source_ok is True

    def test_source_failure_is_flagged_and_logged(self, caplog):
        with patch_client("backend.app.safety.crime.agent.run_crime_agent",
                          error=RuntimeError("data.gov.sg 429")):
            with caplog.at_level("WARNING"):
                batch = _run(api._fetch_crime_incidents())

        assert list(batch) == []
        assert batch.source_ok is False
        assert "Crime statistics source unavailable" in caplog.text
        assert "data.gov.sg" not in batch.source_error

    def test_the_report_is_reused_within_one_request(self):
        cache: Dict[str, Any] = {}
        with patch_client("backend.app.safety.crime.agent.run_crime_agent",
                         _crime_report()) as calls:
            first = _run(api._fetch_crime_incidents(cache))
            second = _run(api._fetch_crime_incidents(cache))
        assert len(calls.calls) == 1
        assert first == second


# --------------------------------------------------------- isolation / shape
class TestAlertBatchAndIsolation:
    def test_batch_is_still_a_plain_list_to_every_consumer(self):
        """The endpoint does isinstance(result, list) and .extend()."""
        batch = api.AlertBatch([{"domain": "traffic"}])
        assert isinstance(batch, list)
        combined: List[Dict[str, Any]] = []
        combined.extend(batch)
        assert combined == [{"domain": "traffic"}]

    def test_default_batch_is_a_healthy_source(self):
        batch = api.AlertBatch()
        assert batch.source_ok is True and batch.source_error is None

    def test_one_failing_source_does_not_stop_the_others(self, caplog):
        """Every fetcher is isolated: each catches its own failure."""
        results = {}
        sources = {
            "traffic": ("backend.app.mobility.traffic.api.TrafficIncidentsApiClient",
                        "traffic"),
            "flood": ("backend.app.environment.flood.api.FloodAlertsApiClient", "flood"),
            "crime": ("backend.app.safety.crime.agent.run_crime_agent", "crime"),
        }
        fetchers = {
            "traffic": api._fetch_traffic_incidents,
            "flood": api._fetch_flood_alerts,
            "crime": api._fetch_crime_incidents,
        }
        with caplog.at_level("WARNING"):
            for name, fetcher in fetchers.items():
                target, _ = sources[name]
                with patch_client(target, error=RuntimeError("down")):
                    results[name] = _run(fetcher())

        for name, batch in results.items():
            assert list(batch) == [], name
            assert batch.source_ok is False, name
        # All three logged independently.
        assert caplog.text.count("source unavailable") >= 3

    def test_alert_dicts_satisfy_the_response_contract(self):
        """Every alert carries exactly the keys AlertItem requires."""
        required = {"domain", "severity", "title", "description",
                    "timestamp", "affected_zones"}
        with patch_client("backend.app.mobility.traffic.api.TrafficIncidentsApiClient",
                         _traffic_snapshot([
                             TrafficIncident(incident_type="Accident", latitude=None,
                                             longitude=None, message="m", source="s",
                                             zone_id="Z1")])):
            produced = _run(api._fetch_traffic_incidents())
        with patch_client("backend.app.environment.flood.api.FloodAlertsApiClient",
                         _flood_snapshot([_flood_alert()])):
            produced += _run(api._fetch_flood_alerts())
        with patch_client("backend.app.safety.crime.agent.run_crime_agent",
                         _crime_report()):
            produced += _run(api._fetch_crime_incidents())

        assert produced
        for alert in produced:
            assert required <= set(alert), alert
            # Everything the response model declares must be JSON-safe.
            for key in ("title", "description", "timestamp", "severity"):
                assert isinstance(alert[key], str), (key, alert)
            assert all(isinstance(z, str) for z in alert["affected_zones"])


# ------------------------------------------------------------------ plumbing
class _FakeClient:
    """Minimal stand-in for an API adapter; ``fetch`` returns a prepared snapshot."""

    def __init__(self, result: Any = None, error: Optional[Exception] = None) -> None:
        self._result = result
        self._error = error

    def fetch(self, *args: Any, **kwargs: Any) -> Any:
        if self._error is not None:
            raise self._error
        return self._result


class _Patcher:
    """Context manager that swaps in a prepared source and counts invocations.

    The fetchers import their dependency *inside* the function body, so patching
    the module attribute is enough - the import happens at call time.
    """

    def __init__(self, target: str, result: Any = None,
                 error: Optional[Exception] = None) -> None:
        self.calls: List[Any] = []
        self._target = target
        self._result = result
        self._error = error

    def _client(self, *args: Any, **kwargs: Any) -> _FakeClient:
        self.calls.append(1)
        return _FakeClient(result=self._result, error=self._error)

    def _agent(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(1)
        if self._error is not None:
            raise self._error
        return self._result

    def __enter__(self) -> "_Patcher":
        factory = self._agent if self._target.endswith("run_crime_agent") else self._client
        self._patcher = patch(self._target, factory)
        self._patcher.__enter__()
        return self

    def __exit__(self, *exc: Any) -> Any:
        return self._patcher.__exit__(*exc)


def patch_client(target: str, result: Any = None,
                 error: Optional[Exception] = None) -> _Patcher:
    return _Patcher(target, result=result, error=error)