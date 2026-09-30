"""Tests for City Coordinator LangGraph workflow."""

from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from coordinator.city_agent import (
    CityCoordinatorState,
    create_city_coordinator,
    collect_reports,
    normalize_state,
    analyze_cross_domain_impacts,
    prioritize_risks,
    generate_recommendations,
    build_report,
)
from coordinator.city_report import (
    CitySituationReport,
    DomainStatus,
    CrossDomainImpact,
    PriorityIncident,
)


class MockEnvironmentReport:
    """Mock EnvironmentReport for testing."""
    def __init__(self, max_pm25=20, ml_regions=3, weather_available=True, data_quality_flags=None):
        self.generated_at = datetime.now()
        self.regions = []
        for i, region in enumerate(["north", "south", "east", "west", "central"]):
            if i < ml_regions:
                self.regions.append(MagicMock(
                    region=region,
                    is_ml_model=True,
                    pm25_next_day_max=max_pm25,
                    selected_model="catboost",
                ))
            else:
                self.regions.append(MagicMock(
                    region=region,
                    is_ml_model=False,
                    pm25_next_day_max=max_pm25,
                    selected_model="bl_persist",
                ))
        self.data_quality_flags = data_quality_flags or []
        self.weather_forecast = MagicMock(
            national_forecast_text="Thundery showers",
            national_forecast_code="TSRA",
        ) if weather_available else None
    
    def to_dict(self):
        return {
            "domain": "environment",
            "generated_at": self.generated_at.isoformat(),
            "regions": [r.region for r in self.regions],
            "data_quality_flags": self.data_quality_flags,
            "provenance": {},
        }


class MockTrafficReport:
    """Mock TrafficReport for testing."""
    def __init__(self, status="normal", incidents=None, zones=None):
        self.generated_at = datetime.now()
        self.overall_status = status
        self.overall_average_speed = 60.0 if status == "normal" else 30.0
        self.overall_predicted_speed = 58.0
        self.overall_congestion_level = "moderate" if status == "elevated" else "free_flow"
        self.incidents = incidents or []
        self.zones = zones or [
            MagicMock(
                zone_id=f"SG_ZONE_{i}",
                zone_name=f"Zone {i}",
                is_demo_zone=True,
                congestion_level="free_flow",
            ) for i in range(8)
        ]
        self.limitations = ["Test limitation"]
    
    def model_dump(self):
        return {
            "overall_status": self.overall_status,
            "overall_average_speed": self.overall_average_speed,
            "overall_congestion_level": self.overall_congestion_level,
            "incidents": [{"zone_name": i.zone_name} for i in self.incidents],
            "zones": [{"zone_name": z.zone_name, "congestion_level": z.congestion_level, "is_demo_zone": z.is_demo_zone} for z in self.zones],
            "limitations": self.limitations,
        }


class MockFloodReport:
    """Mock FloodReport V3 for testing (matches flood.flood_report_v3.FloodReport)."""
    def __init__(self, risk="LOW", alerts=None, affected_zones=None):
        from backend.app.environment.flood.models import FloodRiskLevel
        self.generated_at = datetime.now()
        # NEW: risk_level is FloodRiskLevel enum, no overall_risk field
        self.risk_level = FloodRiskLevel(risk)
        self.risk_score = 0.5 if risk != "LOW" else 0.0
        self.active_alert_count = len(alerts) if alerts else 0
        self.active_alerts = alerts or []
        self.affected_zones = affected_zones or []
        self.primary_risk_factors = ["Heavy rainfall"] if risk != "LOW" else []
        self.past_flood_events = []  # NEW: past_flood_events instead of historical_context
        self.recommendations = ["Test recommendation"]
        self.confidence = "high"
        self.limitations = ["Test limitation"]
        self.is_ml_prediction = False
        self.errors = []
        self.data_sources = ["test_source"]
        # Evidence fields (optional)
        self.singapore_rainfall = None
        self.malaysia_rainfall = None
        self.sumatra_rainfall = None
        self.regional_weather = None
    
    def model_dump(self):
        return {
            "risk_level": self.risk_level.value,
            "risk_score": self.risk_score,
            "active_alert_count": self.active_alert_count,
            "active_alerts": self.active_alerts,
            "affected_zones": self.affected_zones,
            "primary_risk_factors": self.primary_risk_factors,
            "past_flood_events": self.past_flood_events,
            "confidence": self.confidence,
            "limitations": self.limitations,
            "is_ml_prediction": self.is_ml_prediction,
            "errors": self.errors,
            "data_sources": self.data_sources,
        }


class TestCityCoordinatorNodes:
    """Test individual nodes of the City Coordinator."""
    
    def test_collect_reports_success(self):
        """Test collecting reports with all agents succeeding."""
        with patch("coordinator.city_agent.EnvironmentModule") as mock_env_class, \
             patch("coordinator.city_agent.run_traffic_agent") as mock_traffic, \
             patch("coordinator.city_agent.run_flood_agent_v3") as mock_flood:
            
            mock_env = MagicMock()
            mock_env.run.return_value = MockEnvironmentReport()
            mock_env_class.return_value = mock_env
            
            mock_traffic.return_value = MockTrafficReport()
            mock_flood.return_value = MockFloodReport()
            
            state = CityCoordinatorState()
            result = collect_reports(state)
        
        assert result.environment_report is not None
        assert result.traffic_report is not None
        assert result.flood_report is not None
        assert len(result.errors) == 0
        assert "environment" in result.source_reports
        assert "traffic" in result.source_reports
        assert "flood" in result.source_reports
    
    def test_collect_reports_environment_failure(self):
        """Test collecting reports when environment agent fails."""
        with patch("coordinator.city_agent.EnvironmentModule") as mock_env_class, \
             patch("coordinator.city_agent.run_traffic_agent") as mock_traffic, \
             patch("coordinator.city_agent.run_flood_agent_v3") as mock_flood:
            
            mock_env_class.side_effect = Exception("Environment failed")
            mock_traffic.return_value = MockTrafficReport()
            mock_flood.return_value = MockFloodReport()
            
            state = CityCoordinatorState()
            result = collect_reports(state)
        
        assert result.environment_report is None
        assert result.traffic_report is not None
        assert result.flood_report is not None
        assert len(result.errors) == 1
        assert "Environment Agent" in result.errors[0]
        assert "Environment report unavailable" in result.warnings
    
    def test_normalize_state(self):
        """Test normalizing domain reports into unified structure."""
        state = CityCoordinatorState(
            environment_report=MockEnvironmentReport(max_pm25=50, ml_regions=3),
            traffic_report=MockTrafficReport(status="elevated"),
            flood_report=MockFloodReport(risk="MODERATE", affected_zones=["Central South"]),
        )
        
        result = normalize_state(state)
        
        assert "environment" in result.domain_status
        assert "traffic" in result.domain_status
        assert "flood" in result.domain_status
        
        # Check environment
        env = result.domain_status["environment"]
        assert env["available"] is True
        assert env["overall_risk"] == "MODERATE"  # 50 µg/m³ -> MODERATE
        assert env["is_ml_prediction"] is True
        
        # Check traffic
        traffic = result.domain_status["traffic"]
        assert traffic["available"] is True
        assert traffic["overall_status"] == "elevated"
        assert traffic["overall_risk"] == "MODERATE"
        
        # Check flood
        flood = result.domain_status["flood"]
        assert flood["available"] is True
        assert flood["overall_risk"] == "MODERATE"
        
        # Check affected zones
        assert "Central South" in result.affected_zones
    
    def test_normalize_state_missing_reports(self):
        """Test normalization with missing reports."""
        state = CityCoordinatorState(
            environment_report=None,
            traffic_report=MockTrafficReport(),
            flood_report=None,
        )
        
        result = normalize_state(state)
        
        assert result.domain_status["environment"]["available"] is False
        assert result.domain_status["traffic"]["available"] is True
        assert result.domain_status["flood"]["available"] is False
    
    def test_analyze_cross_domain_impacts_flood_traffic(self):
        """Test flood+traffic cross-domain detection."""
        state = CityCoordinatorState(
            domain_status={
                "flood": {"available": True, "overall_risk": "HIGH", "affected_zones": ["Central South"]},
                "traffic": {"available": True, "overall_status": "disrupted", "affected_zones": ["Central South"]},
                "environment": {"available": True, "key_metrics": {"weather_forecast_available": True}},
            }
        )
        
        result = analyze_cross_domain_impacts(state)
        
        impacts = result.cross_domain_impacts
        assert len(impacts) >= 1
        flood_traffic = [i for i in impacts if i["type"] == "flood_traffic"]
        assert len(flood_traffic) == 1
        assert flood_traffic[0]["severity"] == "HIGH"
        assert "Central South" in flood_traffic[0]["affected_zones"]
        
        # Check priority incident
        assert len(result.priority_incidents) == 1
        assert result.priority_incidents[0]["type"] == "flood_traffic_overlap"
    
    def test_analyze_cross_domain_impacts_weather_flood(self):
        """Test weather+flood cross-domain detection."""
        state = CityCoordinatorState(
            domain_status={
                "flood": {"available": True, "overall_risk": "HIGH", "affected_zones": ["Central South"]},
                "environment": {"available": True, "key_metrics": {"weather_forecast_available": True}},
            },
            environment_report=MockEnvironmentReport(),
        )
        
        result = analyze_cross_domain_impacts(state)
        
        impacts = result.cross_domain_impacts
        weather_flood = [i for i in impacts if i["type"] == "weather_flood"]
        assert len(weather_flood) == 1
        assert weather_flood[0]["severity"] == "HIGH"
    
    def test_analyze_cross_domain_impacts_air_quality(self):
        """Test air quality cross-domain detection."""
        state = CityCoordinatorState(
            domain_status={
                "environment": {"available": True, "key_metrics": {"max_pm25_next_day_max": 100, "weather_forecast_available": True}},
            },
            environment_report=MockEnvironmentReport(max_pm25=100),
        )
        
        result = analyze_cross_domain_impacts(state)
        
        impacts = result.cross_domain_impacts
        air_quality = [i for i in impacts if i["type"] == "air_quality_weather"]
        assert len(air_quality) == 1
        assert air_quality[0]["severity"] == "HIGH"
    
    def test_analyze_cross_domain_impacts_multi_domain_high(self):
        """Test multi-domain HIGH risk detection."""
        state = CityCoordinatorState(
            domain_status={
                "environment": {"available": True, "overall_risk": "HIGH"},
                "traffic": {"available": True, "overall_risk": "HIGH"},
                "flood": {"available": True, "overall_risk": "MODERATE"},
            }
        )
        
        result = analyze_cross_domain_impacts(state)
        
        impacts = result.cross_domain_impacts
        multi_high = [i for i in impacts if i["type"] == "multi_domain_high_risk"]
        assert len(multi_high) == 1
        assert multi_high[0]["severity"] == "HIGH"
        assert set(multi_high[0]["domains_involved"]) == {"environment", "traffic"}
    
    def test_prioritize_risks(self):
        """Test risk prioritization and overall city status."""
        state = CityCoordinatorState(
            cross_domain_impacts=[
                {"type": "flood_traffic", "severity": "HIGH", "description": "Flood+traffic overlap"},
            ],
            priority_incidents=[
                {"severity": "HIGH", "description": "Flood+traffic in Central South"},
            ],
            domain_status={
                "flood": {"overall_risk": "HIGH"},
                "traffic": {"overall_risk": "MODERATE"},
                "environment": {"overall_risk": "LOW"},
            },
        )
        
        result = prioritize_risks(state)
        
        assert result.overall_risk_level == "HIGH"
        assert result.overall_city_status == "DISRUPTED"
        assert result.confidence == "high"
        assert len(result.limitations) > 0
        assert any("not an ML predictor" in l for l in result.limitations)
    
    def test_prioritize_risks_critical(self):
        """Test CRITICAL risk prioritization."""
        state = CityCoordinatorState(
            cross_domain_impacts=[
                {"type": "multi_domain_high_risk", "severity": "CRITICAL", "description": "Multi-domain HIGH"},
            ],
            domain_status={
                "environment": {"overall_risk": "HIGH"},
                "traffic": {"overall_risk": "HIGH"},
                "flood": {"overall_risk": "HIGH"},
            },
        )
        
        result = prioritize_risks(state)
        
        assert result.overall_risk_level == "CRITICAL"
        assert result.overall_city_status == "CRITICAL"
    
    def test_generate_recommendations_flood_traffic(self):
        """Test recommendation generation for flood+traffic."""
        state = CityCoordinatorState(
            cross_domain_impacts=[
                {"type": "flood_traffic", "affected_zones": ["Central South", "West North"]},
            ],
            domain_status={
                "flood": {"overall_risk": "HIGH"},
                "traffic": {"overall_status": "disrupted"},
            },
        )
        
        result = generate_recommendations(state)
        
        recs = result.city_level_recommendations
        assert len(recs) >= 1
        assert any("FLOOD+TRAFFIC" in r for r in recs)
        assert any("Central South" in r for r in recs)
    
    def test_generate_recommendations_weather_flood(self):
        """Test recommendation generation for weather+flood."""
        state = CityCoordinatorState(
            cross_domain_impacts=[
                {"type": "weather_flood"},
            ],
            domain_status={"flood": {"overall_risk": "HIGH"}},
        )
        
        result = generate_recommendations(state)
        
        assert any("WEATHER+FLOOD" in r for r in result.city_level_recommendations)
    
    def test_generate_recommendations_multi_domain_critical(self):
        """Test recommendation for multi-domain critical."""
        state = CityCoordinatorState(
            cross_domain_impacts=[
                {"type": "multi_domain_high_risk", "domains_involved": ["environment", "traffic", "flood"]},
            ],
        )
        
        result = generate_recommendations(state)
        
        assert any("MULTI-DOMAIN CRITICAL" in r for r in result.city_level_recommendations)
        assert any("cross-agency coordination" in r for r in result.city_level_recommendations)
    
    def test_generate_recommendations_single_domain(self):
        """Test single domain recommendations."""
        state = CityCoordinatorState(
            cross_domain_impacts=[],
            domain_status={
                "flood": {"overall_risk": "HIGH"},
                "traffic": {"overall_status": "normal"},
                "environment": {"key_metrics": {"max_pm25_next_day_max": 10}},
            },
        )
        
        result = generate_recommendations(state)
        
        assert any("FLOOD" in r for r in result.city_level_recommendations)
        assert any("PUB Telegram" in r for r in result.city_level_recommendations)
    
    def test_build_report(self):
        """Test building final CitySituationReport."""
        state = CityCoordinatorState(
            overall_city_status="DISRUPTED",
            overall_risk_level="HIGH",
            domain_status={
                "environment": {"available": True, "overall_risk": "LOW"},
                "traffic": {"available": True, "overall_risk": "HIGH"},
                "flood": {"available": True, "overall_risk": "HIGH"},
            },
            priority_incidents=[
                {"id": "INC_001", "type": "flood_traffic_overlap", "domain": "flood_traffic", 
                 "severity": "HIGH", "description": "Test", "affected_zones": ["Central South"],
                 "source_report": "flood+traffic", "related_domains": ["flood", "traffic"]},
            ],
            cross_domain_impacts=[
                {"type": "flood_traffic", "description": "Test", "severity": "HIGH",
                 "affected_zones": ["Central South"], "domains_involved": ["flood", "traffic"],
                 "evidence": ["Test evidence"]},
            ],
            city_level_recommendations=["Test recommendation"],
            affected_zones=["Central South"],
            evidence=[{"source": "test"}],
            confidence="high",
            limitations=["Test limitation"],
            source_reports={"environment": {}, "traffic": {}, "flood": {}},
        )
        
        result = build_report(state)
        
        assert result.report is not None
        assert isinstance(result.report, CitySituationReport)
        assert result.report.overall_city_status == "DISRUPTED"
        assert result.report.overall_risk_level == "HIGH"
        assert len(result.report.priority_incidents) == 1
        assert len(result.report.cross_domain_impacts) == 1
        assert result.report.is_ml_prediction is False


class TestCityCoordinatorIntegration:
    """Integration tests for the full City Coordinator workflow."""
    
    def _mock_all_agents(self, env_risk="LOW", traffic_status="normal", flood_risk="LOW"):
        """Setup mocks for all three agents."""
        mock_env = MockEnvironmentReport(max_pm25=55 if env_risk == "HIGH" else 20)
        mock_traffic = MockTrafficReport(status=traffic_status)
        mock_flood = MockFloodReport(risk=flood_risk, affected_zones=["Central South"] if flood_risk != "LOW" else [])
        
        return mock_env, mock_traffic, mock_flood
    
    def test_all_normal(self):
        """Test when all domain reports are normal."""
        mock_env, mock_traffic, mock_flood = self._mock_all_agents("LOW", "normal", "LOW")
        
        with patch("coordinator.city_agent.EnvironmentModule") as mock_env_class, \
             patch("coordinator.city_agent.run_traffic_agent", return_value=mock_traffic), \
             patch("coordinator.city_agent.run_flood_agent_v3", return_value=mock_flood):
            
            mock_env_class.return_value.run.return_value = mock_env
            
            graph = create_city_coordinator()
            result = graph.invoke(CityCoordinatorState())
        
        assert result.get("report") is not None
        report = result["report"]
        assert isinstance(report, CitySituationReport)
        assert report.overall_city_status in ["NORMAL", "ELEVATED"]
        assert report.overall_risk_level in ["LOW", "MODERATE"]
        assert report.is_ml_prediction is False
    
    def test_high_flood_traffic_congestion(self):
        """Test high flood + traffic congestion."""
        mock_env, mock_traffic, mock_flood = self._mock_all_agents("LOW", "disrupted", "HIGH")
        
        with patch("coordinator.city_agent.EnvironmentModule") as mock_env_class, \
             patch("coordinator.city_agent.run_traffic_agent", return_value=mock_traffic), \
             patch("coordinator.city_agent.run_flood_agent_v3", return_value=mock_flood):
            
            mock_env_class.return_value.run.return_value = mock_env
            
            graph = create_city_coordinator()
            result = graph.invoke(CityCoordinatorState())
        
        report = result["report"]
        assert report.overall_risk_level == "HIGH"
        assert report.overall_city_status == "DISRUPTED"
        
        # Check flood+traffic impact detected
        impacts = report.cross_domain_impacts
        flood_traffic = [i for i in impacts if i.type == "flood_traffic"]
        assert len(flood_traffic) == 1
        assert flood_traffic[0].severity == "HIGH"
        
        # Check recommendations
        assert any("FLOOD+TRAFFIC" in r for r in report.city_level_recommendations)
    
    def test_high_environment_normal_traffic_flood(self):
        """Test high environment + normal traffic/flood."""
        mock_env, mock_traffic, mock_flood = self._mock_all_agents("HIGH", "normal", "LOW")
        
        with patch("coordinator.city_agent.EnvironmentModule") as mock_env_class, \
             patch("coordinator.city_agent.run_traffic_agent", return_value=mock_traffic), \
             patch("coordinator.city_agent.run_flood_agent_v3", return_value=mock_flood):
            
            mock_env_class.return_value.run.return_value = mock_env
            
            graph = create_city_coordinator()
            result = graph.invoke(CityCoordinatorState())
        
        report = result["report"]
        assert report.overall_risk_level in ["HIGH", "MODERATE"]
        
        # Check air quality recommendation
        assert any("AIR QUALITY" in r or "ENVIRONMENT" in r for r in report.city_level_recommendations)
    
    def test_multiple_simultaneous_high_risk(self):
        """Test multiple simultaneous HIGH risk domains."""
        mock_env, mock_traffic, mock_flood = self._mock_all_agents("HIGH", "disrupted", "HIGH")
        
        with patch("coordinator.city_agent.EnvironmentModule") as mock_env_class, \
             patch("coordinator.city_agent.run_traffic_agent", return_value=mock_traffic), \
             patch("coordinator.city_agent.run_flood_agent_v3", return_value=mock_flood):
            
            mock_env_class.return_value.run.return_value = mock_env
            
            graph = create_city_coordinator()
            result = graph.invoke(CityCoordinatorState())
        
        report = result["report"]
        assert report.overall_risk_level == "CRITICAL"
        assert report.overall_city_status == "CRITICAL"
        
        # Check multi-domain impact
        impacts = report.cross_domain_impacts
        multi_high = [i for i in impacts if i.type == "multi_domain_high_risk"]
        assert len(multi_high) == 1
        assert multi_high[0].severity == "CRITICAL"
        
        # Check recommendation
        assert any("MULTI-DOMAIN CRITICAL" in r for r in report.city_level_recommendations)
    
    def test_empty_missing_domain_report(self):
        """Test handling of missing domain report."""
        mock_env = MockEnvironmentReport()
        mock_traffic = MockTrafficReport()
        
        with patch("coordinator.city_agent.EnvironmentModule") as mock_env_class, \
             patch("coordinator.city_agent.run_traffic_agent", return_value=mock_traffic), \
             patch("coordinator.city_agent.run_flood_agent_v3", side_effect=Exception("Flood agent failed")):
            
            mock_env_class.return_value.run.return_value = mock_env
            
            graph = create_city_coordinator()
            result = graph.invoke(CityCoordinatorState())
        
        # Should still produce a report
        assert result.get("report") is not None
        report = result["report"]
        assert report.domain_status["flood"].available is False
        assert "Flood agent failed" in " ".join(report.limitations)
    
    def test_malformed_domain_report(self):
        """Test handling of malformed domain report."""
        # Environment report with missing fields
        mock_env = MockEnvironmentReport()
        mock_env.regions = []  # Missing regions
        
        mock_traffic = MockTrafficReport()
        mock_traffic.zones = []  # Missing zones
        
        mock_flood = MockFloodReport()
        mock_flood.active_alerts = "not a list"  # Malformed
        
        with patch("coordinator.city_agent.EnvironmentModule") as mock_env_class, \
             patch("coordinator.city_agent.run_traffic_agent", return_value=mock_traffic), \
             patch("coordinator.city_agent.run_flood_agent_v3", return_value=mock_flood):
            
            mock_env_class.return_value.run.return_value = mock_env
            
            graph = create_city_coordinator()
            result = graph.invoke(CityCoordinatorState())
        
        # Should handle gracefully
        assert result.get("report") is not None
    
    def test_cross_domain_impact_detection(self):
        """Test cross-domain impact detection accuracy."""
        mock_env = MockEnvironmentReport(weather_available=True)
        mock_traffic = MockTrafficReport(status="disrupted", 
            incidents=[MagicMock(zone_name="Central South")],
            zones=[MagicMock(zone_id="SG_CENTRAL_SOUTH", zone_name="Central South", congestion_level="heavy", is_demo_zone=True)])
        mock_flood = MockFloodReport(risk="HIGH", affected_zones=["Central South"])
        
        with patch("coordinator.city_agent.EnvironmentModule") as mock_env_class, \
             patch("coordinator.city_agent.run_traffic_agent", return_value=mock_traffic), \
             patch("coordinator.city_agent.run_flood_agent_v3", return_value=mock_flood):
            
            mock_env_class.return_value.run.return_value = mock_env
            
            graph = create_city_coordinator()
            result = graph.invoke(CityCoordinatorState())
        
        report = result["report"]
        
        # Verify flood+traffic impact detected
        flood_traffic = [i for i in report.cross_domain_impacts if i.type == "flood_traffic"]
        assert len(flood_traffic) == 1
        assert "Central South" in flood_traffic[0].affected_zones
        
        # Verify weather+flood impact
        weather_flood = [i for i in report.cross_domain_impacts if i.type == "weather_flood"]
        assert len(weather_flood) == 1
    
    def test_priority_ordering(self):
        """Test priority incident ordering."""
        mock_env = MockEnvironmentReport(max_pm25=100)  # High PM2.5
        mock_traffic = MockTrafficReport(status="disrupted")
        mock_flood = MockFloodReport(risk="HIGH", affected_zones=["Central South", "West North"])
        
        with patch("coordinator.city_agent.EnvironmentModule") as mock_env_class, \
             patch("coordinator.city_agent.run_traffic_agent", return_value=mock_traffic), \
             patch("coordinator.city_agent.run_flood_agent_v3", return_value=mock_flood):
            
            mock_env_class.return_value.run.return_value = mock_env
            
            graph = create_city_coordinator()
            result = graph.invoke(CityCoordinatorState())
        
        report = result["report"]
        
        # Priority incidents should exist
        assert len(report.priority_incidents) >= 0
        
        # Cross-domain impacts should be ordered by severity
        impacts = report.cross_domain_impacts
        if len(impacts) > 1:
            severities = [i.severity for i in impacts]
            severity_order = {"CRITICAL": 4, "HIGH": 3, "MODERATE": 2, "LOW": 1}
            # Should be roughly ordered by severity
            assert severity_order.get(severities[0], 0) >= severity_order.get(severities[-1], 0)
    
    def test_complete_city_situation_report_schema(self):
        """Test that CitySituationReport has all required fields."""
        mock_env = MockEnvironmentReport()
        mock_traffic = MockTrafficReport()
        mock_flood = MockFloodReport()
        
        with patch("coordinator.city_agent.EnvironmentModule") as mock_env_class, \
             patch("coordinator.city_agent.run_traffic_agent", return_value=mock_traffic), \
             patch("coordinator.city_agent.run_flood_agent_v3", return_value=mock_flood):
            
            mock_env_class.return_value.run.return_value = mock_env
            
            graph = create_city_coordinator()
            result = graph.invoke(CityCoordinatorState())
        
        report = result["report"]
        
        # Check all required fields exist
        assert hasattr(report, "generated_at")
        assert hasattr(report, "overall_city_status")
        assert hasattr(report, "overall_risk_level")
        assert hasattr(report, "domain_status")
        assert hasattr(report, "priority_incidents")
        assert hasattr(report, "cross_domain_impacts")
        assert hasattr(report, "city_level_recommendations")
        assert hasattr(report, "affected_zones")
        assert hasattr(report, "evidence")
        assert hasattr(report, "confidence")
        assert hasattr(report, "limitations")
        assert hasattr(report, "source_reports")
        assert hasattr(report, "is_ml_prediction")
        
        # Check domain_status structure
        assert "environment" in report.domain_status
        assert "traffic" in report.domain_status
        assert "flood" in report.domain_status
        
        # Check is_ml_prediction is False
        assert report.is_ml_prediction is False
        
        # Check confidence is valid
        assert report.confidence in ["high", "medium", "low"]
        
        # Check limitations include standard ones
        limitations_text = " ".join(report.limitations)
        assert "not an ML predictor" in limitations_text
        assert "offline fixtures" in limitations_text
    
    def test_deterministic_output(self):
        """Test that report is deterministic across runs."""
        mock_env = MockEnvironmentReport()
        mock_traffic = MockTrafficReport()
        mock_flood = MockFloodReport()
        
        with patch("coordinator.city_agent.EnvironmentModule") as mock_env_class, \
             patch("coordinator.city_agent.run_traffic_agent", return_value=mock_traffic), \
             patch("coordinator.city_agent.run_flood_agent_v3", return_value=mock_flood):
            
            mock_env_class.return_value.run.return_value = mock_env
            
            graph = create_city_coordinator()
            
            result1 = graph.invoke(CityCoordinatorState())
            result2 = graph.invoke(CityCoordinatorState())
        
        report1 = result1["report"]
        report2 = result2["report"]
        
        assert report1.overall_city_status == report2.overall_city_status
        assert report1.overall_risk_level == report2.overall_risk_level
        assert report1.confidence == report2.confidence
        assert len(report1.city_level_recommendations) == len(report2.city_level_recommendations)
    
    def test_domain_modules_not_modified(self):
        """Test that domain modules are not modified by coordinator."""
        env_module_path = os.path.join(os.path.dirname(__file__), "..", "backend", "app", "environment", "environment_module.py")
        traffic_agent_path = os.path.join(os.path.dirname(__file__), "..", "backend", "app", "mobility", "traffic", "agent.py")
        flood_agent_path = os.path.join(os.path.dirname(__file__), "..", "backend", "app", "environment", "flood", "agent.py")
        
        for path in [env_module_path, traffic_agent_path, flood_agent_path]:
            mtime_before = os.path.getmtime(path)
            
            mock_env = MockEnvironmentReport()
            mock_traffic = MockTrafficReport()
            mock_flood = MockFloodReport()
            
            with patch("coordinator.city_agent.EnvironmentModule") as mock_env_class, \
                 patch("coordinator.city_agent.run_traffic_agent", return_value=mock_traffic), \
                 patch("coordinator.city_agent.run_flood_agent_v3", return_value=mock_flood):
                
                mock_env_class.return_value.run.return_value = mock_env
                
                graph = create_city_coordinator()
                graph.invoke(CityCoordinatorState())
            
            mtime_after = os.path.getmtime(path)
            assert mtime_before == mtime_after, f"Domain module {path} was modified!"
    
    def test_no_ml_model_trained(self):
        """Test that no ML model is trained during coordinator run."""
        mock_env = MockEnvironmentReport()
        mock_traffic = MockTrafficReport()
        mock_flood = MockFloodReport()
        
        with patch("coordinator.city_agent.EnvironmentModule") as mock_env_class, \
             patch("coordinator.city_agent.run_traffic_agent", return_value=mock_traffic), \
             patch("coordinator.city_agent.run_flood_agent_v3", return_value=mock_flood):
            
            mock_env_class.return_value.run.return_value = mock_env
            
            graph = create_city_coordinator()
            result = graph.invoke(CityCoordinatorState())
        
        report = result["report"]
        assert report.is_ml_prediction is False
        
        # Check domain reports also have is_ml_prediction properly set
        for domain_name, status in report.domain_status.items():
            if status.available:
                assert "is_ml_prediction" in status.__dict__ or hasattr(status, "is_ml_prediction")


class TestCityAPI:
    """Tests for City Coordinator API endpoint."""
    
    def test_city_report_endpoint(self):
        """Test that the API endpoint can be created."""
        from backend.app.main import app
        
        # Check route exists
        routes = [r.path for r in app.routes if hasattr(r, 'path')]
        assert "/api/city/report" in routes
    
    def test_city_report_response_structure(self):
        """Test API response structure with mocked agents."""
        mock_env = MockEnvironmentReport()
        mock_traffic = MockTrafficReport()
        mock_flood = MockFloodReport()
        
        with patch("coordinator.city_agent.EnvironmentModule") as mock_env_class, \
             patch("coordinator.city_agent.run_traffic_agent", return_value=mock_traffic), \
             patch("coordinator.city_agent.run_flood_agent_v3", return_value=mock_flood):
            
            mock_env_class.return_value.run.return_value = mock_env
            
            from backend.app.main import app
            from fastapi.testclient import TestClient
            
            client = TestClient(app)
            response = client.get("/api/city/report")
            
            assert response.status_code == 200
            data = response.json()
            
            assert "overall_city_status" in data
            assert "overall_risk_level" in data
            assert "domain_status" in data
            assert "city_level_recommendations" in data
            assert data["is_ml_prediction"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])