"""Tests for NEA Air Temperature API integration."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from backend.app.environment.weather.api import (
    AirTemperatureApiClient,
    AirTemperatureSnapshot,
    aggregate_city_temperature,
    _make_fallback_fixture,
)
from backend.app.environment.weather.api import WeatherApiClient, WeatherLiveSnapshot


class TestAirTemperatureApiClient:
    """Tests for the Air Temperature API client."""

    def test_offline_fixture_structure(self):
        """Test that offline fixture has expected structure."""
        client = AirTemperatureApiClient(offline=True)
        snapshot = client.fetch()

        assert snapshot.is_live is False
        assert snapshot.source == "offline_fixture:NEA_air_temperature"
        assert snapshot.provider == "NEA / data.gov.sg"
        assert snapshot.unit == "deg C"
        assert snapshot.reading_type == "DBT 1M F"
        assert len(snapshot.readings) == 5

        for reading in snapshot.readings.values():
            assert reading.station_id
            assert reading.station_name
            assert reading.value_c is not None
            assert reading.observed_at
            assert reading.latitude is not None
            assert reading.longitude is not None

    def test_fallback_fixture_has_recent_timestamp(self):
        """Test that offline fixture uses current timestamp."""
        fixture = _make_fallback_fixture()
        
        # Check structure
        assert fixture["code"] == 0
        assert "data" in fixture
        assert "stations" in fixture["data"]
        assert "readings" in fixture["data"]
        assert len(fixture["data"]["readings"]) == 1
        
        reading = fixture["data"]["readings"][0]
        assert "timestamp" in reading
        assert "data" in reading
        assert len(reading["data"]) == 5

    def test_live_fetch_fails_gracefully(self):
        """Test that live fetch failure returns unavailable state."""
        with patch("backend.app.environment.weather.api.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.side_effect = Exception("Network error")
            mock_client_class.return_value.__enter__.return_value = mock_client
            
            client = AirTemperatureApiClient(offline=False, allow_fallback_fixture=False)
            
            with pytest.raises(Exception, match="Network error"):
                client.fetch()


class TestAggregateCityTemperature:
    """Tests for city-level temperature aggregation."""

    def _make_snapshot(self, readings_dict, is_live=True):
        """Helper to create a snapshot with given readings."""
        readings = {}
        for station_id, data in readings_dict.items():
            from backend.app.environment.weather.api import AirTemperatureReading
            readings[station_id] = AirTemperatureReading(
                station_id=station_id,
                station_name=data.get("name", station_id),
                latitude=data.get("lat"),
                longitude=data.get("lon"),
                value_c=data["value"],
                observed_at=data["time"],
                source="test",
            )
        return AirTemperatureSnapshot(
            snapshot_at="2026-08-20T16:35:44+08:00",
            source="test",
            provider="test",
            endpoint="test",
            unit="deg C",
            reading_type="DBT 1M F",
            readings=readings,
            is_live=is_live,
        )

    def test_valid_observations_aggregated(self):
        """Test valid station observations produce correct aggregation."""
        from datetime import datetime, timezone, timedelta
        
        now = datetime.now(timezone(timedelta(hours=8))).isoformat()
        readings = {
            "S109": {"name": "Ang Mo Kio", "lat": 1.3793, "lon": 103.85, "value": 28.5, "time": now},
            "S106": {"name": "Pulau Ubin", "lat": 1.4168, "lon": 103.9673, "value": 29.2, "time": now},
            "S117": {"name": "Banyan Road", "lat": 1.2542, "lon": 103.6741, "value": 28.8, "time": now},
            "S107": {"name": "East Coast Parkway", "lat": 1.3133, "lon": 103.962, "value": 29.0, "time": now},
            "S104": {"name": "Woodlands", "lat": 1.4439, "lon": 103.7854, "value": 28.2, "time": now},
        }
        
        snapshot = self._make_snapshot(readings)
        result = aggregate_city_temperature(snapshot)
        
        assert result["available"] is True
        assert result["value_c"] == 28.7  # (28.5+29.2+28.8+29.0+28.2)/5 = 28.74 -> 28.7
        assert result["min_c"] == 28.2
        assert result["max_c"] == 29.2
        assert result["stations_used"] == 5
        assert result["observed_at"] == now
        assert result["aggregation"] == "mean_of_recent_valid_stations"
        assert len(result["stations"]) == 5
        assert result["freshness_minutes"] < 1.0  # Should be very fresh

    def test_stale_observations_excluded(self):
        """Test that stale observations are excluded from aggregation."""
        from datetime import datetime, timedelta, timezone
        
        old_time = (datetime.now(timezone(timedelta(hours=8))) - timedelta(minutes=20)).isoformat()
        recent_time = datetime.now(timezone(timedelta(hours=8))).isoformat()
        
        readings = {
            "S109": {"name": "Ang Mo Kio", "lat": 1.3793, "lon": 103.85, "value": 28.5, "time": old_time},  # 20 min old
            "S106": {"name": "Pulau Ubin", "lat": 1.4168, "lon": 103.9673, "value": 29.2, "time": recent_time},
        }
        
        snapshot = self._make_snapshot(readings)
        result = aggregate_city_temperature(snapshot, max_age_minutes=10)
        
        assert result["available"] is True
        assert result["stations_used"] == 1
        assert result["value_c"] == 29.2
        assert result["min_c"] == 29.2
        assert result["max_c"] == 29.2

    def test_all_observations_stale(self):
        """Test that all stale observations returns unavailable."""
        from datetime import datetime, timedelta, timezone
        
        old_time = (datetime.now(timezone(timedelta(hours=8))) - timedelta(minutes=30)).isoformat()
        
        readings = {
            "S109": {"name": "Ang Mo Kio", "lat": 1.3793, "lon": 103.85, "value": 28.5, "time": old_time},
            "S106": {"name": "Pulau Ubin", "lat": 1.4168, "lon": 103.9673, "value": 29.2, "time": old_time},
        }
        
        snapshot = self._make_snapshot(readings)
        result = aggregate_city_temperature(snapshot, max_age_minutes=10)
        
        assert result["available"] is False
        assert "freshness window" in result["unavailable_reason"]
        assert result["value_c"] is None

    def test_no_readings(self):
        """Test empty readings returns unavailable."""
        snapshot = AirTemperatureSnapshot(
            snapshot_at="2026-08-20T16:35:44+08:00",
            source="test",
            provider="test",
            endpoint="test",
            unit="deg C",
            reading_type="DBT 1M F",
            readings={},
            is_live=True,
        )
        
        result = aggregate_city_temperature(snapshot)
        
        assert result["available"] is False
        assert result["unavailable_reason"] == "No station readings in snapshot"
        assert result["stations_used"] == 0

    def test_missing_values_ignored(self):
        """Test that None values are handled gracefully."""
        from datetime import datetime, timezone, timedelta
        
        now = datetime.now(timezone(timedelta(hours=8))).isoformat()
        readings = {
            "S109": {"name": "Ang Mo Kio", "lat": 1.3793, "lon": 103.85, "value": 28.5, "time": now},
            "S106": {"name": "Pulau Ubin", "lat": 1.4168, "lon": 103.9673, "value": None, "time": now},  # Invalid value
        }
        
        snapshot = self._make_snapshot(readings)
        result = aggregate_city_temperature(snapshot)
        
        assert result["available"] is True
        assert result["stations_used"] == 1
        assert result["value_c"] == 28.5


class TestWeatherApiWithAirTemperature:
    """Tests for Weather API with integrated air temperature."""

    def test_weather_includes_current_temperature(self):
        """Test that weather snapshot includes current temperature."""
        air_client = AirTemperatureApiClient(offline=True)
        weather_client = WeatherApiClient(offline=True, air_temperature_client=air_client)
        
        snap = weather_client.fetch()
        
        assert snap.current_temperature is not None
        assert snap.current_temperature["available"] is True
        assert "value_c" in snap.current_temperature
        assert "stations_used" in snap.current_temperature
        assert "min_c" in snap.current_temperature
        assert "max_c" in snap.current_temperature

    def test_weather_without_air_temp_client(self):
        """Test weather works without air temperature client."""
        weather_client = WeatherApiClient(offline=True)
        
        snap = weather_client.fetch()
        
        assert snap.current_temperature is None

    def test_air_temp_failure_handled(self):
        """Test that air temperature fetch failure is handled gracefully."""
        with patch("backend.app.environment.weather.api.AirTemperatureApiClient.fetch") as mock_fetch:
            mock_fetch.side_effect = Exception("API error")
            
            air_client = AirTemperatureApiClient(offline=False, allow_fallback_fixture=False)
            weather_client = WeatherApiClient(offline=True, air_temperature_client=air_client)
            
            snap = weather_client.fetch()
            
            assert snap.current_temperature is not None
            assert snap.current_temperature["available"] is False
            assert "failed" in snap.current_temperature["unavailable_reason"].lower()


class TestUnits:
    """Tests for correct unit representation."""

    def test_temperature_unit_is_celsius(self):
        """Test that temperature is reported in degrees Celsius."""
        client = AirTemperatureApiClient(offline=True)
        snapshot = client.fetch()
        
        assert snapshot.unit == "deg C"
        
        for reading in snapshot.readings.values():
            assert isinstance(reading.value_c, float)
            # Values should be reasonable for Singapore (20-35°C)
            assert 15 <= reading.value_c <= 40


if __name__ == "__main__":
    pytest.main([__file__, "-v"])