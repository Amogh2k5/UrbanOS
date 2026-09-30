"""Tests for Flood Agent V3 — Live Regional API + Manual Rules."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Import V3 components
from backend.app.environment.flood.agent import (
    FloodAgentState,
    create_flood_agent_v3,
    load_past_flood_events,
    fetch_singapore_rainfall,
    fetch_malaysia_rainfall,
    fetch_sumatra_forecast,
    fetch_pub_alerts,
    fetch_nea_weather,
    assess_risk,
    build_report,
    run_flood_agent_v3,
    _CATALOGUE_PATH,
    _analyze_singapore_rainfall,
    _analyze_nea_weather,
)
from backend.app.environment.flood.models import (
    FloodReport, PastFloodEvent, ActiveFloodAlert,
    SingaporeRainfallEvidence, MalaysiaRainfallEvidence, SumatraRainfallEvidence,
    RegionalWeatherStatus, FloodRiskLevel
)
from backend.app.environment.flood.api import FloodAlertsApiClient, FloodAlertsSnapshot
from backend.app.environment.flood.rainfall_clients import (
    RainfallApiClient, RainfallSnapshot,
    MalaysiaRainfallApiClient, MalaysiaRainfallSnapshot,
    SumatraForecastApiClient, SumatraForecastSnapshot,
)
from backend.app.environment.weather.api import WeatherApiClient, WeatherLiveSnapshot


class TestFloodAgentV3Nodes:
    """Test individual nodes of the Flood Agent V3."""
    
    def test_load_past_flood_events(self):
        """Test loading past flood events (reference only)."""
        mock_df = pd.DataFrame({
            "event_id": ["SG_FLD_2010_01", "SG_FLD_2011_01"],
            "date_start": ["2010-01-01", "2011-01-01"],
            "date_end": ["2010-01-02", "2011-01-02"],
            "location": ["Orchard Road", "Bukit Timah"],
            "region": ["Central", "Central/West"],
            "flood_type": ["flash_flood", "flash_flood"],
            "primary_cause": ["extreme_rainfall", "extreme_rainfall"],
            "confidence": ["high", "high"],
            "rainfall_mm": [100.0, 150.0],
        })
        
        # Point catalogue path to test fixture
        fixture_path = Path(__file__).parent / "fixtures" / "flood_events_curated_v0.5.csv"
        with patch("backend.app.environment.flood.agent._CATALOGUE_PATH", fixture_path), \
             patch("backend.app.environment.flood.agent.pd.read_csv", return_value=mock_df):
            state = FloodAgentState()
            result = load_past_flood_events(state)
        
        assert len(result.past_flood_events) == 2
        assert "historical_catalogue:flood_events_curated_v0.5" in result.data_sources
    
    def test_fetch_singapore_rainfall_offline(self):
        """Test fetching Singapore rainfall in offline mode."""
        with patch("backend.app.environment.flood.agent.RainfallApiClient") as mock_client_class:
            mock_client = MagicMock()
            mock_snapshot = MagicMock()
            mock_snapshot.is_live = False
            mock_snapshot.source = "offline_fixture:NEA_rainfall_5min"
            mock_snapshot.readings = {"S90": MagicMock(value_mm=0.0, observed_at="2024-12-01T14:30:00+08:00")}
            mock_client.fetch.return_value = mock_snapshot
            mock_client_class.return_value = mock_client
            
            state = FloodAgentState()
            os.environ["FLOOD_AGENT_OFFLINE"] = "true"
            result = fetch_singapore_rainfall(state)
        
        assert result.singapore_rainfall is not None
        assert result.singapore_rainfall.is_live is False
        assert "singapore_rainfall:offline_fixture:NEA_rainfall_5min" in result.data_sources
    
    def test_fetch_malaysia_rainfall_offline(self):
        """Test fetching Malaysia rainfall in offline mode."""
        with patch("backend.app.environment.flood.agent.MalaysiaRainfallApiClient") as mock_client_class:
            mock_client = MagicMock()
            mock_evidence = {
                "available": False,
                "source": "offline_fixture:MetMalaysia_rainfall",
                "error": "No live data",
                "stations": {},
                "max_1h_mm": 0.0,
                "max_24h_mm": 0.0,
                "weather_systems": [],
            }
            mock_client.fetch.return_value = MagicMock()  # Not used directly
            mock_client_class.return_value = mock_client
            
            with patch("backend.app.environment.flood.agent.get_malaysia_rainfall_evidence", return_value=mock_evidence):
                state = FloodAgentState()
                os.environ["FLOOD_AGENT_OFFLINE"] = "true"
                result = fetch_malaysia_rainfall(state)
        
        assert result.malaysia_evidence is not None
        assert result.malaysia_evidence["available"] is False
        assert "malaysia_rainfall:offline_fixture:MetMalaysia_rainfall" in result.data_sources

    def test_fetch_sumatra_forecast_offline(self):
        """Test fetching Sumatra rainfall in offline mode."""
        with patch("backend.app.environment.flood.agent.SumatraForecastApiClient") as mock_client_class:
            mock_client = MagicMock()
            mock_snapshot = MagicMock()
            mock_snapshot.is_live = False
            mock_snapshot.source = "offline_fixture:BMKG_forecast"
            mock_snapshot.error = "No live data"
            mock_snapshot.groups = {}
            mock_client.fetch.return_value = mock_snapshot
            mock_client_class.return_value = mock_client

            state = FloodAgentState()
            os.environ["URBANOS_API_OFFLINE"] = "true"
            result = fetch_sumatra_forecast(state)
        assert result.sumatra_rainfall is not None
        assert result.sumatra_rainfall.is_live is False
        assert result.sumatra_rainfall.error == "No live data"

    def test_fetch_pub_alerts_offline(self):
        """Test fetching PUB alerts in offline mode."""
        with patch("backend.app.environment.flood.agent.FloodAlertsApiClient") as mock_client_class:
            mock_client = MagicMock()
            mock_snapshot = MagicMock()
            mock_snapshot.source = "offline_fixture:PUB_flood_alerts"
            mock_snapshot.is_live = False
            mock_snapshot.to_dict.return_value = {
                "alerts": [
                    {
                        "alert_id": "FLD_001",
                        "location": "Orchard Road",
                        "severity": "High",
                        "zone_name": "Central South",
                        "issued_at": "2024-12-01T14:30:00+08:00",
                        "type": "Flash Flood",
                        "message": "Heavy rain",
                        "latitude": 1.3033,
                        "longitude": 103.8317,
                    }
                ],
                "is_live": False,
                "source": "offline_fixture:PUB_flood_alerts",
            }
            mock_client.fetch.return_value = mock_snapshot
            mock_client_class.return_value = mock_client
            
            state = FloodAgentState()
            os.environ["FLOOD_AGENT_OFFLINE"] = "true"
            result = fetch_pub_alerts(state)
        
        assert len(result.pub_alerts) == 1
        assert "pub_alerts:offline_fixture:PUB_flood_alerts" in result.data_sources
    
    def test_fetch_nea_weather_offline(self):
        """Test fetching NEA weather in offline mode."""
        with patch("backend.app.environment.flood.agent.WeatherApiClient") as mock_client_class:
            mock_client = MagicMock()
            mock_snapshot = MagicMock()
            mock_snapshot.is_live = False
            mock_snapshot.source = "offline_fixture:NEA_24h_weather"
            mock_snapshot.general.forecast_code = "FW"
            mock_snapshot.general.forecast_text = "Fair and Warm"
            mock_snapshot.general.wind_direction = "NE"
            mock_client.fetch.return_value = mock_snapshot
            mock_client_class.return_value = mock_client
            
            state = FloodAgentState()
            os.environ["FLOOD_AGENT_OFFLINE"] = "true"
            result = fetch_nea_weather(state)
        
        assert result.nea_weather is not None
        assert "nea_weather:offline_fixture:NEA_24h_weather" in result.data_sources
    
    def test_analyze_singapore_rainfall(self):
        """Test Singapore rainfall analysis (uses 5-min readings directly)."""
        # Mock snapshot with readings
        mock_snapshot = MagicMock()
        mock_snapshot.is_live = True
        mock_snapshot.source = "live_api:NEA_rainfall_5min"
        mock_reading = MagicMock()
        mock_reading.value_mm = 5.0  # 5mm in 5-min
        mock_snapshot.readings = {"S90": mock_reading, "S61": mock_reading}
        
        result = _analyze_singapore_rainfall(mock_snapshot)
        
        assert result["available"] is True
        assert result["peak_5m_mm"] == 5.0
        # New behavior: uses 5-min reading directly (no extrapolation)
        assert result["max_1h_mm"] == 5.0
        assert result["max_3h_mm"] == 5.0
        assert result["stations_reporting"] == 2
        assert result["stations_with_rain"] == 2
    
    def test_analyze_nea_weather(self):
        """Test NEA weather analysis."""
        mock_snapshot = MagicMock()
        mock_snapshot.is_live = True
        mock_snapshot.source = "live_api:NEA_24h_weather"
        mock_snapshot.general.forecast_code = "SQ"
        mock_snapshot.general.forecast_text = "Sumatra Squall"
        mock_snapshot.general.wind_direction = "SW"
        mock_snapshot.general.temperature_high_c = 32.0
        mock_snapshot.general.temperature_low_c = 26.0
        
        result = _analyze_nea_weather(mock_snapshot)
        
        assert result["available"] is True
        assert result["forecast_code"] == "SQ"
        assert result["wind_direction"] == "SW"
    
    def test_assess_risk_no_evidence(self):
        """Test risk assessment with no evidence -> LOW or UNKNOWN."""
        state = FloodAgentState(
            singapore_rainfall=None,
            malaysia_evidence={"available": False},
            sumatra_evidence={"available": False},
            pub_alerts=[],
            nea_weather=None,
            errors=[],
        )
        
        result = assess_risk(state)
        
        # All unavailable -> UNKNOWN
        assert result.risk_level == FloodRiskLevel.UNKNOWN
        assert "All primary data sources unavailable" in " ".join(result.primary_risk_factors)
    
    def test_assess_risk_singapore_heavy_rainfall(self):
        """Test risk assessment with Singapore heavy 5-min rainfall -> MODERATE/HIGH."""
        state = FloodAgentState(
            singapore_rainfall=MagicMock(is_live=True, source="live_api:NEA_rainfall_5min", readings={
                "S90": MagicMock(value_mm=6.0),  # 6mm/5min = heavy (>5mm)
            }),
            malaysia_evidence={"available": False},
            sumatra_evidence={"available": False},
            pub_alerts=[],
            nea_weather=None,
            errors=[],
        )
        
        result = assess_risk(state)
        
        # 6mm/5min exceeds SINGAPORE_5M_HEAVY (5mm) -> score >= 0.35 -> MODERATE or HIGH
        assert result.risk_level in [FloodRiskLevel.MODERATE, FloodRiskLevel.HIGH]
        assert any("Heavy 5-min intensity" in f or "Extreme 5-min intensity" in f for f in result.primary_risk_factors)
    
    def test_assess_risk_singapore_extreme_rainfall(self):
        """Test risk assessment with Singapore extreme 5-min rainfall -> HIGH."""
        state = FloodAgentState(
            singapore_rainfall=MagicMock(is_live=True, source="live_api:NEA_rainfall_5min", readings={
                "S90": MagicMock(value_mm=9.0),  # 9mm/5min = extreme (>8mm)
            }),
            malaysia_evidence={"available": False},
            sumatra_evidence={"available": False},
            pub_alerts=[],
            nea_weather=None,
            errors=[],
        )
        
        result = assess_risk(state)
        
        # 9mm/5min exceeds SINGAPORE_5M_EXTREME (8mm) -> score >= 0.5 -> HIGH
        assert result.risk_level == FloodRiskLevel.HIGH
        assert any("Extreme 5-min intensity" in f for f in result.primary_risk_factors)
    
    def test_assess_risk_pub_high_alert(self):
        """Test risk assessment with PUB HIGH alert -> HIGH."""
        state = FloodAgentState(
            singapore_rainfall=MagicMock(is_live=True, source="live_api:NEA_rainfall_5min", readings={}),
            malaysia_evidence={"available": False},
            sumatra_evidence={"available": False},
            pub_alerts=[{"severity": "High", "zone_name": "Central South"}],
            nea_weather=None,
            errors=[],
        )
        
        result = assess_risk(state)
        
        assert result.risk_level in [FloodRiskLevel.HIGH, FloodRiskLevel.CRITICAL]
        assert any("PUB HIGH alert" in f for f in result.primary_risk_factors)
    
    def test_assess_risk_singapore_heavy_plus_pub_moderate(self):
        """Test Singapore heavy rain + PUB MODERATE alert -> HIGH."""
        state = FloodAgentState(
            singapore_rainfall=MagicMock(is_live=True, source="live_api:NEA_rainfall_5min", readings={
                "S90": MagicMock(value_mm=5.0),  # 60mm/1h
            }),
            malaysia_evidence={"available": False},
            sumatra_evidence={"available": False},
            pub_alerts=[{"severity": "Moderate", "zone_name": "Central South"}],
            nea_weather=None,
            errors=[],
        )
        
        result = assess_risk(state)
        
        # Heavy rain (0.4) + MODERATE alert (0.7) = 1.1 -> HIGH
        assert result.risk_level in [FloodRiskLevel.HIGH, FloodRiskLevel.CRITICAL]
    
    def test_assess_risk_malaysia_heavy_rainfall(self):
        """Test Malaysia heavy rainfall supporting evidence."""
        state = FloodAgentState(
            singapore_rainfall=MagicMock(is_live=True, source="live_api:NEA_rainfall_5min", readings={
                "S90": MagicMock(value_mm=2.0),  # 24mm/1h = moderate
            }),
            malaysia_evidence={"available": True, "max_1h_mm": 60.0, "weather_systems": []},
            sumatra_evidence={"available": False},
            pub_alerts=[],
            nea_weather=None,
            errors=[],
        )
        
        result = assess_risk(state)
        
        # Singapore moderate (0.2) + Malaysia heavy (0.3*0.5=0.15) = 0.35 -> LOW/MODERATE
        assert result.risk_level in [FloodRiskLevel.LOW, FloodRiskLevel.MODERATE]
        assert any("Johor heavy rainfall" in f for f in result.primary_risk_factors)
    
    def test_assess_risk_sumatra_squall(self):
        """Test Sumatra squall detection."""
        state = FloodAgentState(
            singapore_rainfall=MagicMock(is_live=True, source="live_api:NEA_rainfall_5min", readings={}),
            malaysia_evidence={"available": False},
            sumatra_evidence={"available": True, "max_1h_mm": 40.0, "weather_systems": ["possible_sumatra_squall"]},
            pub_alerts=[],
            nea_weather=MagicMock(general=MagicMock(forecast_code="SQ", wind_direction="SW")),
            errors=[],
        )
        
        result = assess_risk(state)
        
        # Sumatra squall adds SUMATRA_SQUALL_WEIGHT (0.4) + NEA SQ (0.4) + SW wind (0.15)
        assert result.risk_level in [FloodRiskLevel.MODERATE, FloodRiskLevel.HIGH]
        assert any("Sumatra squall" in f or "possible_sumatra_squall" in f for f in result.primary_risk_factors)
    
    def test_assess_risk_case_a_singapore_dry_regional_heavy(self):
        """CASE A: Singapore dry + Malaysia heavy + Sumatra heavy -> LOW or WATCH."""
        state = FloodAgentState(
            singapore_rainfall=MagicMock(is_live=True, source="live_api:NEA_rainfall_5min", readings={
                "S90": MagicMock(value_mm=0.0),
            }),
            malaysia_evidence={"available": True, "max_1h_mm": 80.0, "weather_systems": []},
            sumatra_evidence={"available": True, "max_1h_mm": 70.0, "weather_systems": ["possible_sumatra_squall"]},
            pub_alerts=[],
            nea_weather=MagicMock(general=MagicMock(forecast_code="FW", wind_direction="NE")),
            errors=[],
        )
        
        result = assess_risk(state)
        
        # Singapore dry (0) + regional only -> should NOT be HIGH
        # Malaysia (0.3*0.5=0.15) + Sumatra (0.3*0.5=0.15) + Sumatra squall (0.4*0.3=0.12) = ~0.42 -> MODERATE at most
        assert result.risk_level in [FloodRiskLevel.LOW, FloodRiskLevel.MODERATE]
        assert result.risk_level != FloodRiskLevel.HIGH
        assert result.risk_level != FloodRiskLevel.CRITICAL
    
    def test_assess_risk_case_b_singapore_heavy_regional_active(self):
        """CASE B: Singapore heavy + Johor heavy + regional activity -> higher risk."""
        state = FloodAgentState(
            singapore_rainfall=MagicMock(is_live=True, source="live_api:NEA_rainfall_5min", readings={
                "S90": MagicMock(value_mm=5.0),  # 60mm/1h
            }),
            malaysia_evidence={"available": True, "max_1h_mm": 60.0, "weather_systems": []},
            sumatra_evidence={"available": True, "max_1h_mm": 50.0, "weather_systems": []},
            pub_alerts=[],
            nea_weather=MagicMock(general=MagicMock(forecast_code="SQ", wind_direction="SW")),
            errors=[],
        )
        
        result = assess_risk(state)
        
        # Singapore heavy (0.4) + Malaysia (0.15) + Sumatra (0.15) + SQ (0.4) + SW (0.15) = 1.25 -> CRITICAL or HIGH
        assert result.risk_level in [FloodRiskLevel.HIGH, FloodRiskLevel.CRITICAL]
    
    def test_build_report(self):
        """Test building FloodReport V3."""
        from datetime import datetime
        from backend.app.environment.flood.agent import SG_OFFSET
        
        state = FloodAgentState(
            risk_level=FloodRiskLevel.HIGH,
            risk_score=0.85,
            pub_alerts=[
                {
                    "alert_id": "FLD_001",
                    "location": "Orchard Road",
                    "zone_id": "SG_CENTRAL_SOUTH",
                    "zone_name": "Central South",
                    "severity": "High",
                    "type": "Flash Flood",
                    "message": "Heavy rain",
                    "issued_at": "2024-12-01T14:30:00+08:00",
                    "latitude": 1.3033,
                    "longitude": 103.8317,
                    "source": "offline_fixture:PUB_flood_alerts",
                }
            ],
            singapore_evidence={
                "available": True,
                "source": "live_api:NEA_rainfall_5min",
                "max_1h_mm": 60.0,
                "max_3h_mm": 120.0,
                "max_6h_mm": 150.0,
                "max_24h_mm": 180.0,
                "max_15m_mm": 20.0,
                "peak_5m_mm": 8.0,
                "stations_reporting": 60,
                "stations_with_rain": 30,
            },
            malaysia_evidence={
                "available": True,
                "source": "live_api:MetMalaysia_rainfall",
                "max_1h_mm": 40.0,
                "stations_reporting": 5,
                "weather_systems": ["heavy_rainfall_johor"],
            },
            sumatra_evidence={
                "available": True,
                "source": "live_api:BMKG_rainfall_community",
                "max_1h_mm": 30.0,
                "stations_reporting": 4,
                "weather_systems": [],
            },
            regional_weather_status={
                "available": True,
                "source": "live_api:NEA_24h_weather",
                "forecast_code": "SQ",
                "forecast_text": "Sumatra Squall",
                "wind_direction": "SW",
                "temperature_high": 32.0,
                "temperature_low": 26.0,
            },
            past_flood_events=[
                {
                    "event_id": "SG_FLD_2010_01",
                    "date_start": "2010-06-16",
                    "date_end": "2010-06-16",
                    "location": "Orchard Road",
                    "region": "Central",
                    "flood_type": "flash_flood",
                    "primary_cause": "extreme_rainfall",
                    "rainfall_mm": 100.0,
                    "flood_depth_mm": "300",
                    "damage": "Basement flooding",
                    "deaths": 0,
                    "injuries": 0,
                    "notes": "Test",
                    "source": "PUB",
                    "confidence": "high",
                }
            ],
            primary_risk_factors=["Extreme 1h rainfall: 60.0mm", "PUB HIGH alert(s): 1"],
            affected_zones=["Central South"],
            data_sources=["singapore_rainfall:live_api:NEA_rainfall_5min", "malaysia_rainfall:live_api:MetMalaysia_rainfall"],
            errors=[],
            warnings=[],
        )
        
        result = build_report(state)
        
        assert result.report is not None
        assert isinstance(result.report, FloodReport)
        assert result.report.risk_level == FloodRiskLevel.HIGH
        assert result.report.risk_score == 0.85
        assert result.report.active_alert_count == 1
        assert len(result.report.active_alerts) == 1
        assert result.report.singapore_rainfall is not None
        assert result.report.singapore_rainfall.max_1h_mm == 60.0
        assert result.report.malaysia_rainfall is not None
        assert result.report.malaysia_rainfall.max_1h_mm == 40.0
        assert result.report.sumatra_rainfall is not None
        assert result.report.regional_weather is not None
        assert result.report.regional_weather.singapore_forecast_code == "SQ"
        assert len(result.report.past_flood_events) == 1
        assert result.report.is_ml_prediction is False
    
    def test_build_report_low_risk(self):
        """Test building report with LOW risk."""
        state = FloodAgentState(
            risk_level=FloodRiskLevel.LOW,
            risk_score=0.1,
            pub_alerts=[],
            singapore_evidence={
                "available": True,
                "source": "live_api:NEA_rainfall_5min",
                "max_1h_mm": 5.0,
                "max_3h_mm": 10.0,
                "max_6h_mm": 15.0,
                "max_24h_mm": 20.0,
                "max_15m_mm": 2.0,
                "peak_5m_mm": 1.0,
                "stations_reporting": 60,
                "stations_with_rain": 5,
            },
            malaysia_evidence={"available": False, "source": "unavailable"},
            sumatra_evidence={"available": False, "source": "unavailable"},
            regional_weather_status={"available": True, "forecast_code": "FW", "wind_direction": "NE"},
            past_flood_events=[],
            primary_risk_factors=["Moderate 1h rainfall: 5.0mm"],
            affected_zones=[],
            data_sources=["singapore_rainfall:live_api:NEA_rainfall_5min"],
            errors=[],
            warnings=[],
        )
        
        result = build_report(state)
        
        assert result.report is not None
        assert result.report.risk_level == FloodRiskLevel.LOW
        assert result.report.risk_score == 0.1
        assert result.report.active_alert_count == 0
        assert len(result.report.recommendations) > 0
        assert any("No significant flood risk" in r for r in result.report.recommendations)


class TestFloodAgentV3Integration:
    """Integration tests for Flood Agent V3."""
    
    def _mock_setup(self):
        mock_df = pd.DataFrame({
            "event_id": ["SG_FLD_2010_01"],
            "date_start": ["2010-01-01"],
            "date_end": ["2010-01-02"],
            "location": ["Orchard Road"],
            "region": ["Central"],
            "flood_type": ["flash_flood"],
            "primary_cause": ["extreme_rainfall"],
            "confidence": ["high"],
            "rainfall_mm": [100.0],
        })
        
        return mock_df
    
    def test_v3_langgraph_executes(self):
        """Test V3 LangGraph workflow executes."""
        mock_df = self._mock_setup()
        
        with patch("backend.app.environment.flood.agent.pd.read_csv", return_value=mock_df), \
             patch("backend.app.environment.flood.agent.RainfallApiClient") as mock_sg, \
             patch("backend.app.environment.flood.agent.MalaysiaRainfallApiClient") as mock_my, \
             patch("backend.app.environment.flood.agent.SumatraForecastApiClient") as mock_su, \
             patch("backend.app.environment.flood.agent.FloodAlertsApiClient") as mock_pub, \
             patch("backend.app.environment.flood.agent.WeatherApiClient") as mock_nea:
            
            # Setup mocks
            for mock_class, is_live, source in [
                (mock_sg, False, "offline_fixture:NEA_rainfall_5min"),
                (mock_my, False, "offline_fixture:MetMalaysia_rainfall"),
                (mock_su, False, "offline_fixture:BMKG_rainfall"),
                (mock_pub, False, "offline_fixture:PUB_flood_alerts"),
                (mock_nea, False, "offline_fixture:NEA_24h_weather"),
            ]:
                mock_client = MagicMock()
                mock_snapshot = MagicMock()
                mock_snapshot.is_live = is_live
                mock_snapshot.source = source
                if mock_class == mock_sg:
                    mock_snapshot.readings = {}
                elif mock_class == mock_pub:
                    mock_snapshot.to_dict.return_value = {"alerts": [], "is_live": is_live, "source": source}
                elif mock_class == mock_nea:
                    mock_snapshot.general = MagicMock(forecast_code="FW", forecast_text="Fair", wind_direction="NE")
                mock_client.fetch.return_value = mock_snapshot
                mock_class.return_value = mock_client
            
            graph = create_flood_agent_v3()
            result = graph.invoke(FloodAgentState())
        
        assert result.get("report") is not None
        assert isinstance(result["report"], FloodReport)
        assert result["report"].risk_level in [FloodRiskLevel.LOW, FloodRiskLevel.MODERATE, FloodRiskLevel.HIGH, FloodRiskLevel.CRITICAL, FloodRiskLevel.UNKNOWN]
    
    def test_v3_report_schema(self):
        """Test V3 report has all required fields."""
        mock_df = self._mock_setup()
        
        with patch("backend.app.environment.flood.agent.pd.read_csv", return_value=mock_df), \
             patch("backend.app.environment.flood.agent.RainfallApiClient") as mock_sg, \
             patch("backend.app.environment.flood.agent.MalaysiaRainfallApiClient") as mock_my, \
             patch("backend.app.environment.flood.agent.SumatraForecastApiClient") as mock_su, \
             patch("backend.app.environment.flood.agent.FloodAlertsApiClient") as mock_pub, \
             patch("backend.app.environment.flood.agent.WeatherApiClient") as mock_nea:
            
            for mock_class, is_live, source in [
                (mock_sg, False, "offline_fixture:NEA_rainfall_5min"),
                (mock_my, False, "offline_fixture:MetMalaysia_rainfall"),
                (mock_su, False, "offline_fixture:BMKG_rainfall"),
                (mock_pub, False, "offline_fixture:PUB_flood_alerts"),
                (mock_nea, False, "offline_fixture:NEA_24h_weather"),
            ]:
                mock_client = MagicMock()
                mock_snapshot = MagicMock()
                mock_snapshot.is_live = is_live
                mock_snapshot.source = source
                if mock_class == mock_sg:
                    mock_snapshot.readings = {}
                elif mock_class == mock_pub:
                    mock_snapshot.to_dict.return_value = {"alerts": [], "is_live": is_live, "source": source}
                elif mock_class == mock_nea:
                    mock_snapshot.general = MagicMock(forecast_code="FW", forecast_text="Fair", wind_direction="NE")
                mock_client.fetch.return_value = mock_snapshot
                mock_class.return_value = mock_client
            
            graph = create_flood_agent_v3()
            result = graph.invoke(FloodAgentState())
            report = result["report"]
        
        # Check all V3 fields
        assert hasattr(report, "generated_at")
        assert hasattr(report, "risk_level")
        assert hasattr(report, "risk_score")
        assert hasattr(report, "active_alert_count")
        assert hasattr(report, "active_alerts")
        assert hasattr(report, "affected_zones")
        assert hasattr(report, "primary_risk_factors")
        assert hasattr(report, "singapore_rainfall")
        assert hasattr(report, "malaysia_rainfall")
        assert hasattr(report, "sumatra_rainfall")
        assert hasattr(report, "regional_weather")
        assert hasattr(report, "past_flood_events")
        assert hasattr(report, "data_sources")
        assert hasattr(report, "recommendations")
        assert hasattr(report, "confidence")
        assert hasattr(report, "limitations")
        assert hasattr(report, "is_ml_prediction")
        assert hasattr(report, "errors")
        
        # Check types
        assert isinstance(report.risk_level, FloodRiskLevel)
        assert isinstance(report.risk_score, float)
        assert isinstance(report.singapore_rainfall, (SingaporeRainfallEvidence, type(None)))
        assert isinstance(report.malaysia_rainfall, (MalaysiaRainfallEvidence, type(None)))
        assert isinstance(report.sumatra_rainfall, (SumatraRainfallEvidence, type(None)))
        assert isinstance(report.regional_weather, (RegionalWeatherStatus, type(None)))
    
    def test_v3_distinguishes_live_vs_reference(self):
        """Test V3 report distinguishes live evidence from reference."""
        mock_df = self._mock_setup()
        
        with patch("backend.app.environment.flood.agent.pd.read_csv", return_value=mock_df), \
             patch("backend.app.environment.flood.agent.RainfallApiClient") as mock_sg, \
             patch("backend.app.environment.flood.agent.MalaysiaRainfallApiClient") as mock_my, \
             patch("backend.app.environment.flood.agent.SumatraForecastApiClient") as mock_su, \
             patch("backend.app.environment.flood.agent.FloodAlertsApiClient") as mock_pub, \
             patch("backend.app.environment.flood.agent.WeatherApiClient") as mock_nea:
            
            for mock_class, is_live, source in [
                (mock_sg, True, "live_api:NEA_rainfall_5min"),
                (mock_my, False, "offline_fixture:MetMalaysia_rainfall"),
                (mock_su, False, "offline_fixture:BMKG_rainfall"),
                (mock_pub, False, "offline_fixture:PUB_flood_alerts"),
                (mock_nea, True, "live_api:NEA_24h_weather"),
            ]:
                mock_client = MagicMock()
                mock_snapshot = MagicMock()
                mock_snapshot.is_live = is_live
                mock_snapshot.source = source
                if mock_class == mock_sg:
                    mock_snapshot.readings = {"S90": MagicMock(value_mm=5.0)}
                elif mock_class == mock_pub:
                    mock_snapshot.to_dict.return_value = {"alerts": [], "is_live": is_live, "source": source}
                elif mock_class == mock_nea:
                    mock_snapshot.general = MagicMock(forecast_code="FW", forecast_text="Fair", wind_direction="NE")
                mock_client.fetch.return_value = mock_snapshot
                mock_class.return_value = mock_client
            
            graph = create_flood_agent_v3()
            result = graph.invoke(FloodAgentState())
            report = result["report"]
        
        # Live evidence should be marked available
        assert report.singapore_rainfall is not None
        assert report.singapore_rainfall.available is True
        assert report.singapore_rainfall.source == "live_api:NEA_rainfall_5min"
        
        # Unavailable evidence should be marked
        assert report.malaysia_rainfall is not None
        assert report.malaysia_rainfall.available is False
        
        # Past events are reference
        assert len(report.past_flood_events) >= 0
        assert report.is_ml_prediction is False
    
    def test_v3_no_historical_rainfall_in_current(self):
        """Test that historical CSV data is NOT used for current risk."""
        # The V3 agent should NOT use flood/data/raw/rainfall/*.csv for current risk
        # Those files are only for offline rule calibration (flood/config/risk_rules.py)
        mock_df = self._mock_setup()
        
        with patch("backend.app.environment.flood.agent.pd.read_csv", return_value=mock_df), \
             patch("backend.app.environment.flood.agent.RainfallApiClient") as mock_sg, \
             patch("backend.app.environment.flood.agent.MalaysiaRainfallApiClient") as mock_my, \
             patch("backend.app.environment.flood.agent.SumatraForecastApiClient") as mock_su, \
             patch("backend.app.environment.flood.agent.FloodAlertsApiClient") as mock_pub, \
             patch("backend.app.environment.flood.agent.WeatherApiClient") as mock_nea:
            
            for mock_class, is_live, source in [
                (mock_sg, True, "live_api:NEA_rainfall_5min"),
                (mock_my, False, "offline_fixture:MetMalaysia_rainfall"),
                (mock_su, False, "offline_fixture:BMKG_rainfall"),
                (mock_pub, False, "offline_fixture:PUB_flood_alerts"),
                (mock_nea, True, "live_api:NEA_24h_weather"),
            ]:
                mock_client = MagicMock()
                mock_snapshot = MagicMock()
                mock_snapshot.is_live = is_live
                mock_snapshot.source = source
                if mock_class == mock_sg:
                    mock_snapshot.readings = {"S90": MagicMock(value_mm=5.0)}
                elif mock_class == mock_pub:
                    mock_snapshot.to_dict.return_value = {"alerts": [], "is_live": is_live, "source": source}
                elif mock_class == mock_nea:
                    mock_snapshot.general = MagicMock(forecast_code="FW", forecast_text="Fair", wind_direction="NE")
                mock_client.fetch.return_value = mock_snapshot
                mock_class.return_value = mock_client
            
            graph = create_flood_agent_v3()
            result = graph.invoke(FloodAgentState())
            
            # Data sources should NOT include historical CSV paths
            for src in result["report"].data_sources:
                assert "flood/data/raw/rainfall" not in src
                assert "nea_rainfall_2020.csv" not in src
                assert "nea_rainfall_2021.csv" not in src
                assert "nea_rainfall_2024.csv" not in src


class TestRiskRulesConfig:
    """Test risk rules configuration is properly structured."""
    
    def test_risk_rules_import(self):
        """Test risk_rules module imports correctly."""
        from backend.app.environment.flood.config.risk_rules import (
            SINGAPORE_1H_MODERATE, SINGAPORE_1H_HEAVY, SINGAPORE_1H_EXTREME,
            SINGAPORE_3H_HEAVY, SINGAPORE_6H_HEAVY, SINGAPORE_24H_HEAVY,
            SINGAPORE_STATIONS_WIDESPREAD, SINGAPORE_STATIONS_EXTENSIVE,
            MALAYSIA_WEIGHT, SUMATRA_WEIGHT, SUMATRA_SQUALL_WEIGHT,
            PUB_ALERT_HIGH_WEIGHT, RISK_THRESHOLDS,
            CALIBRATION_METADATA, RULE_DOCUMENTATION,
        )
        
        # Check thresholds are reasonable
        assert SINGAPORE_1H_MODERATE < SINGAPORE_1H_HEAVY < SINGAPORE_1H_EXTREME
        assert SINGAPORE_3H_HEAVY > SINGAPORE_1H_HEAVY
        assert SINGAPORE_24H_HEAVY > SINGAPORE_6H_HEAVY
        
        # Check weights
        assert 0 < MALAYSIA_WEIGHT < 1
        assert 0 < SUMATRA_WEIGHT < 1
        assert 0 < SUMATRA_SQUALL_WEIGHT < 1
        assert 0 < PUB_ALERT_HIGH_WEIGHT <= 1
        
        # Check risk thresholds
        assert RISK_THRESHOLDS["LOW"] < RISK_THRESHOLDS["MODERATE"] < RISK_THRESHOLDS["HIGH"] < RISK_THRESHOLDS["CRITICAL"]
        
        # Check calibration metadata
        assert "limitations" in CALIBRATION_METADATA
        assert "recommendations" in CALIBRATION_METADATA
        assert "sample_sizes" in CALIBRATION_METADATA
        
        # Check rule documentation
        assert "SINGAPORE_1H_HEAVY" in RULE_DOCUMENTATION
        doc = RULE_DOCUMENTATION["SINGAPORE_1H_HEAVY"]
        assert "threshold" in doc
        assert "evidence" in doc
        assert "limitations" in doc


class TestAPIAdapters:
    """Test the new API adapters."""
    
    def test_singapore_rainfall_adapter_offline(self):
        """Test Singapore rainfall adapter offline fixture."""
        client = RainfallApiClient(offline=True)
        snapshot = client.fetch()
        
        assert snapshot.is_live is False
        assert snapshot.source == "offline_fixture:NEA_rainfall_5min"
        assert snapshot.unit == "mm"
        assert len(snapshot.readings) == 5
    
    def test_malaysia_rainfall_adapter_offline(self):
        """Test Malaysia rainfall adapter offline."""
        client = MalaysiaRainfallApiClient(offline=True)
        snapshot = client.fetch()
        
        assert snapshot.is_live is False
        assert snapshot.source == "offline_fixture:MetMalaysia_rainfall"
        assert snapshot.credentials_configured is False
    
    def test_sumatra_rainfall_adapter_offline(self):
        """Test Sumatra forecast adapter offline."""
        client = SumatraForecastApiClient(offline=True)
        snapshot = client.fetch()
        
        assert snapshot.is_live is False
        assert snapshot.source == "offline_fixture:BMKG_forecast"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])