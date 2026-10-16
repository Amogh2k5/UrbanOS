"""Regression tests for Issue 14: Flood Overview source + missing-data statuses.

Two defects are pinned here.

Part A - the Rain & Flood Overview card read ``app.state.flood_client``, a PUB
flood-alert adapter whose payload has no ``risk_level`` key at all. The card
therefore reported "Normal" whenever the PUB call succeeded, including when
every rainfall source was unavailable and the flood agent had correctly
assessed nothing.

Part B - ``determine_status`` coerced absent fields to zero and then to
"normal" for fire, PM2.5, transit and roads, contradicting this repository's
own rule that "absence of data is not evidence of normal conditions".

Everything here is pure or mocked: no network, no live API, no LLM.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from backend.app.intelligence.contracts import validate_finding
from backend.app.intelligence.normalize import (
    build_findings, build_kpi, determine_status, normalize_domain_report,
)
from backend.app.overview import api


# ============================================================== helpers
class _FloodRiskLevel(str, Enum):
    """Stands in for the agent's FloodRiskLevel without importing it."""
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


def _pub_snapshot(alert_count: int = 0) -> Dict[str, Any]:
    """The old Overview payload: a PUB alert snapshot, as the adapter emits it.

    Deliberately carries no ``risk_level`` - that absence *is* the defect.
    """
    return {
        "snapshot_at": "2026-10-15T09:00:00+08:00",
        "source": "live_api:PUB_flood_alerts",
        "provider": "PUB / data.gov.sg",
        "endpoint": "https://api.data.gov.sg/v1/environment/flood-alerts",
        "is_live": True,
        "count": alert_count,
        "alerts": [],
    }


def _flood_report(risk: str, **overrides: Any) -> MagicMock:
    """A FloodReport stand-in exposing only what the Overview reads.

    ``risk="UNKNOWN"`` means the agent found no live source, so it also carries
    no evidence - the shape the real agent produces in that case.
    """
    report = MagicMock()
    live = risk != "UNKNOWN"
    payload: Dict[str, Any] = {
        "generated_at": datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc).isoformat(),
        "risk_level": risk,
        "risk_score": 0.0 if not live else 0.1,
        "active_alert_count": 0,
        "active_alerts": [],
        "affected_zones": [],
        "primary_risk_factors": [] if not live else ["Singapore: peak_5m=0.0mm"],
        # The four inputs the agent keeps distinct. With no live source every
        # evidence block is None, exactly as build_report emits it.
        "singapore_rainfall": (
            {"available": True, "peak_5m_mm": 0.0, "stations_reporting": 52}
            if live else None
        ),
        "sumatra_rainfall": (
            {"available": True, "max_1h_mm": 0.0, "stations_reporting": 27}
            if live else None
        ),
        "regional_weather": (
            {"sumatra_available": True, "regional_systems": []} if live else None
        ),
        "past_flood_events": [],
        "data_sources": (
            ["singapore_rainfall:live_api:NEA_rainfall_5min"] if live else []
        ),
        "recommendations": [],
        "confidence": "medium" if live else "low",
        "limitations": [],
        "is_ml_prediction": False,
        "errors": [] if live else ["All primary data sources unavailable"],
    }
    payload.update(overrides)
    report.model_dump.side_effect = lambda **kw: dict(payload)
    return report


# ================================================ Part A: flood Overview source
class TestFloodOverviewSource:
    """The Overview must read the agent, not the PUB alert client."""

    def test_overview_uses_the_agent_not_the_pub_client(self):
        """Regression: the card read app.state.flood_client, which has no
        risk_level, so it reported Normal whenever PUB answered."""
        app_state = MagicMock()
        client = MagicMock()
        # A PUB client that works perfectly and reports zero alerts.
        client.fetch.return_value = MagicMock(
            to_dict=lambda: _pub_snapshot(alert_count=0)
        )
        app_state.flood_client = client

        with patch("backend.app.environment.flood.agent.run_flood_agent_v3",
                   return_value=_flood_report("LOW")) as run_agent:
            data = _run(_fetch_overview(app_state))

        run_agent.assert_called_once_with()
        client.fetch.assert_not_called()
        assert data["risk_level"] == "LOW"

    def test_assessment_is_dumped_as_json_so_the_enum_never_leaks(self):
        """model_dump() keeps FloodRiskLevel as an enum member whose str() is
        "FloodRiskLevel.LOW" - a string no status rule can match."""
        app_state = MagicMock()
        with patch("backend.app.environment.flood.agent.run_flood_agent_v3",
                   return_value=_flood_report("LOW")):
            data = _run(_fetch_overview(app_state))
        assert isinstance(data["risk_level"], str)
        assert "FloodRiskLevel" not in str(data["risk_level"])

    def test_unavailable_assessment_never_becomes_normal(self):
        """Regression: a successful PUB response with zero alerts used to imply
        a healthy flood picture. It must not."""
        app_state = MagicMock()
        with patch("backend.app.environment.flood.agent.run_flood_agent_v3",
                   return_value=_flood_report("UNKNOWN")):
            data = _run(_fetch_overview(app_state))

        assert data["risk_level"] == "UNKNOWN"
        assert determine_status("flood", data) == "unavailable"
        assert build_kpi("flood", data) is None

        status = normalize_domain_report("flood", data)
        assert status.overall_status == "UNAVAILABLE"
        assert status.findings[0].data_kind == "unavailable"
        assert validate_finding(status.findings[0]) == []

    def test_a_genuine_low_risk_is_an_available_normal_assessment(self):
        """An assessed LOW reading must stay available and normal."""
        app_state = MagicMock()
        with patch("backend.app.environment.flood.agent.run_flood_agent_v3",
                   return_value=_flood_report("LOW")):
            data = _run(_fetch_overview(app_state))

        assert determine_status("flood", data) == "normal"
        assert build_kpi("flood", data) == {"label": "Flood Risk", "value": "Low", "unit": ""}

        status = normalize_domain_report("flood", data)
        assert status.available is True
        assert status.overall_status == "NORMAL"
        assert status.findings[0].data_kind == "live"

    @pytest.mark.parametrize("risk,expected", [
        ("LOW", "normal"),
        ("MODERATE", "elevated"),
        ("HIGH", "critical"),       # unchanged mapping
        ("CRITICAL", "critical"),   # previously fell through to "normal"
    ])
    def test_flood_risk_bands_map_to_status(self, risk, expected):
        with patch("backend.app.environment.flood.agent.run_flood_agent_v3",
                   return_value=_flood_report(risk)):
            data = _run(_fetch_overview(MagicMock()))
        assert determine_status("flood", data) == expected

    def test_enum_risk_level_is_accepted(self):
        """The coordinator path dumps in python mode; an enum must still work."""
        assert determine_status("flood", {"risk_level": _FloodRiskLevel.MODERATE}) == "elevated"
        assert determine_status("flood", {"risk_level": _FloodRiskLevel.UNKNOWN}) == "unavailable"

    def test_agent_failure_surfaces_as_an_error_not_a_normal_reading(self):
        app_state = MagicMock()
        with patch("backend.app.environment.flood.agent.run_flood_agent_v3",
                   side_effect=RuntimeError("boom")):
            data = _run(_fetch_overview(app_state))

        assert data["error"]
        assert determine_status("flood", data) == "unavailable"
        status = normalize_domain_report("flood", data)
        assert status.available is False
        assert status.overall_status is None

    def test_the_four_inputs_stay_distinct(self):
        """Singapore / Sumatra / PUB alerts / NEA weather must not collapse."""
        app_state = MagicMock()
        report = _flood_report(
            "MODERATE",
            active_alert_count=2,
            active_alerts=[{"alert_id": "F1"}],
            regional_weather={"singapore_forecast_code": "TS",
                              "sumatra_available": True},
        )
        with patch("backend.app.environment.flood.agent.run_flood_agent_v3", return_value=report):
            data = _run(_fetch_overview(app_state))

        assert data["singapore_rainfall"]["stations_reporting"] == 52
        assert data["sumatra_rainfall"]["stations_reporting"] == 27
        assert data["regional_weather"]["singapore_forecast_code"] == "TS"
        assert data["active_alert_count"] == 2

    def test_assessment_is_computed_at_most_once_per_request(self):
        """Request-scoped reuse: the agent must not run twice for one request."""
        app_state = MagicMock()
        cache: Dict[str, Any] = {}
        with patch("backend.app.environment.flood.agent.run_flood_agent_v3",
                   return_value=_flood_report("LOW")) as run_agent:
            first = _run(_fetch_overview(app_state, cache))
            second = _run(_fetch_overview(app_state, cache))

        run_agent.assert_called_once()
        assert first is second
        assert cache  # the reuse is explicit, not accidental

    def test_reuse_cache_does_not_leak_across_requests(self):
        """A fresh cache must re-run rather than inherit another request's data."""
        app_state = MagicMock()
        with patch("backend.app.environment.flood.agent.run_flood_agent_v3",
                   return_value=_flood_report("LOW")) as run_agent:
            _run(_fetch_overview(app_state, {}))
            _run(_fetch_overview(app_state, {}))
        assert run_agent.call_count == 2

    def test_overview_works_without_a_cache(self):
        """The optional cache must stay optional (module-detail route)."""
        app_state = MagicMock()
        with patch("backend.app.environment.flood.agent.run_flood_agent_v3",
                   return_value=_flood_report("LOW")):
            assert _run(_fetch_overview(app_state))["risk_level"] == "LOW"


# ============================================= Part B: missing-data statuses
class TestMissingDataIsUnavailable:
    """Absent fields must never be rendered as a normal reading."""

    @pytest.mark.parametrize("payload", [
        {},                                   # key absent
        {"active_incident_count": None},      # key present, null
        {"active_incident_count": ""},        # malformed
        {"active_incident_count": "n/a"},     # malformed sentinel
        {"active_incident_count": None, "source_status": "unavailable"},
    ], ids=["absent", "null", "empty-string", "sentinel", "null-and-unavailable-source"])
    def test_fire_without_a_count_is_unavailable(self, payload):
        assert determine_status("fire", payload) == "unavailable"
        assert build_kpi("fire", payload) is None

    @pytest.mark.parametrize("payload", [
        {},
        {"regions": {}},
        {"regions": None},
        {"regions": {"central": {}}},                      # region without a value
        {"regions": {"central": {"value": None}}},
        {"regions": {"central": {"value": "n/a"}}},        # malformed
        {"regions": ["central"]},                          # wrong shape
    ], ids=["absent", "empty", "null", "no-value-key", "value-null",
            "value-malformed", "wrong-shape"])
    def test_pm25_without_readings_is_unavailable(self, payload):
        assert determine_status("pm25", payload) == "unavailable"
        assert build_kpi("pm25", payload) is None

    @pytest.mark.parametrize("payload", [
        {},
        {"active_train_alerts": None},
        {"active_train_alerts": ""},
        {"active_train_alerts": "many"},
    ], ids=["absent", "null", "empty-string", "non-numeric"])
    def test_transit_without_a_count_is_unavailable(self, payload):
        assert determine_status("transit", payload) == "unavailable"
        assert build_kpi("transit", payload) is None

    @pytest.mark.parametrize("payload", [
        {},
        {"road_works": {}},
        {"road_works": None},
        {"road_works": {"active": None}},
        {"road_works": {"active": "many"}},
        {"road_works": "closed"},
    ], ids=["absent", "empty", "null", "active-null", "active-non-numeric", "wrong-shape"])
    def test_roads_without_a_count_is_unavailable(self, payload):
        assert determine_status("roads", payload) == "unavailable"
        assert build_kpi("roads", payload) is None

    @pytest.mark.parametrize("module_id,payload", [
        ("fire", {"active_incident_count": None}),
        ("pm25", {"regions": {}}),
        ("transit", {}),
        ("roads", {}),
        ("flood", {"risk_level": "UNKNOWN"}),
    ])
    def test_unavailable_never_reports_normal(self, module_id, payload):
        assert determine_status(module_id, payload) != "normal"


class TestExplicitZeroIsPreserved:
    """A supplied 0 is a measurement and must never be treated as missing."""

    def test_zero_active_incidents_is_normal(self):
        assert determine_status("fire", {"active_incident_count": 0}) == "normal"
        assert build_kpi("fire", {"active_incident_count": 0})["value"] == 0

    def test_zero_active_road_works_is_normal(self):
        assert determine_status("roads", {"road_works": {"active": 0}}) == "normal"
        assert build_kpi("roads", {"road_works": {"active": 0}})["value"] == 0

    def test_zero_train_alerts_is_normal(self):
        assert determine_status("transit", {"active_train_alerts": 0}) == "normal"
        assert build_kpi("transit", {"active_train_alerts": 0})["value"] == 0

    def test_zero_pm25_is_normal_and_is_a_measurement(self):
        payload = {"regions": {"central": {"value": 0}}}
        assert determine_status("pm25", payload) == "normal"
        assert build_kpi("pm25", payload)["value"] == 0.0

    def test_mixed_regions_ignore_the_unreadable_one(self):
        """Sufficient valid evidence exists, so the domain is assessable."""
        payload = {"regions": {"central": {"value": None}, "west": {"value": 12.0}}}
        assert determine_status("pm25", payload) == "normal"
        assert build_kpi("pm25", payload)["value"] == 12.0


class TestThresholdsUnchanged:
    """Part B must not move any existing boundary."""

    @pytest.mark.parametrize("active,expected", [
        (0, "normal"), (100, "normal"), (101, "elevated"),
        (300, "elevated"), (501, "critical"), (900, "critical"),
    ])
    def test_roads_thresholds(self, active, expected):
        assert determine_status("roads", {"road_works": {"active": active}}) == expected

    @pytest.mark.parametrize("active,expected", [
        (0, "normal"), (3, "elevated"), (6, "critical"), (9, "critical"),
    ])
    def test_fire_thresholds(self, active, expected):
        assert determine_status("fire", {"active_incident_count": active}) == expected

    @pytest.mark.parametrize("alerts,expected", [
        (0, "normal"), (10, "normal"), (11, "elevated"),
    ])
    def test_transit_thresholds(self, alerts, expected):
        assert determine_status("transit", {"active_train_alerts": alerts}) == expected

    @pytest.mark.parametrize("value,expected", [
        (0, "normal"), (100, "normal"), (100.5, "elevated"), (300, "elevated"),
    ])
    def test_pm25_threshold(self, value, expected):
        assert determine_status("pm25", {"regions": {"c": {"value": value}}}) == expected


class TestCoordinatorBehaviourPreserved:
    """The coordinator must be unaffected by the normalisation change."""

    def test_unavailable_flood_still_reaches_the_coordinator_as_unknown(self):
        from backend.app.coordinator.city_agent import _normalize_flood

        report = MagicMock()
        report.risk_level = _FloodRiskLevel.UNKNOWN
        report.model_dump.return_value = {"risk_level": "UNKNOWN", "active_alert_count": 0}
        report.model_dump.side_effect = lambda **kw: {"risk_level": "UNKNOWN",
                                                      "active_alert_count": 0}

        norm = _normalize_flood(report)
        assert norm["overall_risk"] == "UNKNOWN"
        assert norm["available"] is True

    def test_city_risk_does_not_change_when_a_domain_becomes_unavailable(self):
        """UNKNOWN must never escalate, and never lower, the city level."""
        from backend.app.coordinator.city_agent import (
            CityCoordinatorState, prioritize_risks,
        )

        state = CityCoordinatorState()
        state.domain_status = {
            "environment": {"available": True, "overall_risk": "LOW"},
            "traffic": {"available": True, "overall_risk": "MODERATE"},
            "flood": {"available": True, "overall_risk": "UNKNOWN"},
        }
        prioritize_risks(state)
        assert state.overall_risk_level == "MODERATE"
        assert state.overall_city_status == "ELEVATED"

    def test_unknown_flood_does_not_raise_a_cross_domain_impact(self):
        """An unassessable flood must not anchor any impact."""
        from backend.app.coordinator.city_agent import (
            CityCoordinatorState, analyze_cross_domain_impacts,
        )

        state = CityCoordinatorState()
        state.domain_status = {
            "flood": {"available": True, "overall_risk": "UNKNOWN",
                      "affected_zones": []},
            "traffic": {"available": True, "overall_status": "disrupted",
                        "overall_risk": "HIGH", "affected_zones": []},
            "environment": {"available": True, "key_metrics": {}},
        }
        analyze_cross_domain_impacts(state)
        assert state.cross_domain_impacts == []

    def test_existing_overview_and_context_still_agree(self):
        from backend.app.overview import context

        for module_id, data in [
            ("flood", {"risk_level": "HIGH"}),
            ("fire", {"active_incident_count": 3}),
            ("pm25", {"regions": {"c": {"value": 5}}}),
            ("roads", {"road_works": {"active": 900}}),
            ("transit", {"active_train_alerts": 11}),
        ]:
            assert (api._determine_module_status(module_id, data)
                    == context._determine_module_status(module_id, data)), module_id


# ------------------------------------------------------------------ plumbing
def _fetch_overview(app_state, cache: Dict[str, Any] = None) -> Any:
    return api._fetch_flood_overview(app_state, cache)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)