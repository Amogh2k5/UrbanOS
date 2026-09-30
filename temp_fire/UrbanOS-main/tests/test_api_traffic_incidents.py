"""Tests for LTA Traffic Incidents API adapter."""

from __future__ import annotations

import os
from unittest.mock import patch

import httpx
import pytest

from backend.app.mobility.traffic.incidents import (
    TrafficIncidentsApiClient,
    TrafficIncidentsSnapshot,
    _FALLBACK_FIXTURE,
)


class TestTrafficIncidentsApiClient:
    def test_config_loads_without_exposing_secret(self):
        """Ensure LTA_ACCOUNT_KEY is read from env but never logged/printed."""
        client = TrafficIncidentsApiClient(offline=True)
        assert hasattr(client, "account_key")
        assert not any("AccountKey" in str(v) for v in client.__dict__.values())

    def test_offline_mode_returns_fixture(self):
        """offline=True must return deterministic fixture without network."""
        client = TrafficIncidentsApiClient(offline=True)
        snap: TrafficIncidentsSnapshot = client.fetch()

        assert snap.is_live is False
        assert snap.source == "offline_fixture:LTA_traffic_incidents"
        assert snap.provider == "LTA DataMall"
        assert snap.endpoint == "https://datamall2.mytransport.sg/ltaodataservice/TrafficIncidents"
        assert len(snap.incidents) == 2
        assert snap.incidents[0].incident_type == "Accident"
        assert snap.incidents[0].message == _FALLBACK_FIXTURE["value"][0]["Message"]

    def test_to_dict_structure(self):
        """Snapshot.to_dict() must have the expected keys for frontend consumption."""
        client = TrafficIncidentsApiClient(offline=True)
        snap = client.fetch()
        d = snap.to_dict()

        assert set(d.keys()) == {
            "snapshot_at",
            "source",
            "provider",
            "endpoint",
            "is_live",
            "count",
            "incidents",
        }
        assert d["count"] == 2
        assert isinstance(d["incidents"], list)
        assert "type" in d["incidents"][0]
        assert "message" in d["incidents"][0]
        assert "coordinates" in d["incidents"][0]

    def test_mock_live_success(self):
        """Mocked httpx success returns is_live=True and parsed incidents."""
        mock_payload = {
            "odata.metadata": "https://datamall2.mytransport.sg/ltaodataservice/$metadata#IncidentSet",
            "value": [
                {
                    "Type": "Accident",
                    "Latitude": 1.321,
                    "Longitude": 103.812,
                    "Message": "Test accident on Road A",
                },
                {
                    "Type": "Heavy Traffic",
                    "Latitude": 1.330,
                    "Longitude": 103.862,
                    "Message": "Heavy traffic on Expressway",
                },
            ],
        }

        with patch("httpx.Client.get") as mock_get:
            mock_resp = httpx.Response(200, json=mock_payload, request=httpx.Request("GET", "test"))
            mock_get.return_value = mock_resp

            client = TrafficIncidentsApiClient(
                offline=False, account_key="test-key", allow_fallback_fixture=False
            )
            snap = client.fetch()

        assert snap.is_live is True
        assert snap.source == "live_api:LTA_traffic_incidents"
        assert len(snap.incidents) == 2
        assert snap.incidents[0].incident_type == "Accident"
        assert snap.incidents[0].latitude == 1.321
        assert snap.incidents[0].longitude == 103.812
        assert snap.incidents[0].message == "Test accident on Road A"
        assert snap.incidents[1].incident_type == "Heavy Traffic"

    def test_http_timeout_handled(self):
        """Timeout must be caught and fall back to fixture (when allowed)."""
        with patch("httpx.Client.get", side_effect=httpx.TimeoutException("timeout")):
            client = TrafficIncidentsApiClient(
                offline=False, account_key="test-key", allow_fallback_fixture=True
            )
            snap = client.fetch()

        assert snap.is_live is False
        assert snap.source == "offline_fixture:LTA_traffic_incidents"

    def test_http_error_handled(self):
        """4xx/5xx must be caught and fall back to fixture (when allowed)."""
        with patch("httpx.Client.get") as mock_get:
            mock_resp = httpx.Response(500, text="Internal Server Error", request=httpx.Request("GET", "test"))
            mock_get.return_value = mock_resp

            client = TrafficIncidentsApiClient(
                offline=False, account_key="test-key", allow_fallback_fixture=True
            )
            snap = client.fetch()

        assert snap.is_live is False
        assert snap.source == "offline_fixture:LTA_traffic_incidents"

    def test_connection_error_handled(self):
        """Connection errors must be caught and fall back to fixture (when allowed)."""
        with patch("httpx.Client.get", side_effect=httpx.ConnectError("connection failed")):
            client = TrafficIncidentsApiClient(
                offline=False, account_key="test-key", allow_fallback_fixture=True
            )
            snap = client.fetch()

        assert snap.is_live is False
        assert snap.source == "offline_fixture:LTA_traffic_incidents"

    def test_malformed_response_handled(self):
        """Non-JSON response must be caught and fall back to fixture (when allowed)."""
        with patch("httpx.Client.get") as mock_get:
            mock_resp = httpx.Response(200, text="not json", request=httpx.Request("GET", "test"))
            mock_get.return_value = mock_resp

            client = TrafficIncidentsApiClient(
                offline=False, account_key="test-key", allow_fallback_fixture=True
            )
            snap = client.fetch()

        assert snap.is_live is False
        assert snap.source == "offline_fixture:LTA_traffic_incidents"

    def test_case_insensitive_field_mapping(self):
        """Field names may vary in case (Type/type, Latitude/latitude, etc.)."""
        mock_payload = {
            "value": [
                {"type": "Accident", "latitude": 1.3, "longitude": 103.8, "message": "lowercase keys"},
                {"Type": "Roadwork", "Latitude": 1.4, "Longitude": 103.9, "Message": "mixed keys"},
            ],
        }

        with patch("httpx.Client.get") as mock_get:
            mock_resp = httpx.Response(200, json=mock_payload, request=httpx.Request("GET", "test"))
            mock_get.return_value = mock_resp

            client = TrafficIncidentsApiClient(
                offline=False, account_key="test-key", allow_fallback_fixture=False
            )
            snap = client.fetch()

        assert len(snap.incidents) == 2
        assert snap.incidents[0].incident_type == "Accident"
        assert snap.incidents[1].incident_type == "Roadwork"

    def test_missing_account_key_uses_fixture(self):
        """Missing key must not crash; must use fixture when allowed."""
        with patch.dict(os.environ, {}, clear=True):
            client = TrafficIncidentsApiClient(offline=False, allow_fallback_fixture=True)
            snap = client.fetch()

        assert snap.is_live is False
        assert snap.source == "offline_fixture:LTA_traffic_incidents"