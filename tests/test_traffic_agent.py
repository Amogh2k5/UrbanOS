"""Tests for Traffic Agent LangGraph workflow."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Import the traffic agent components (production backend)
from backend.app.mobility.traffic.agent import (
    TrafficAgentState,
    create_traffic_agent,
    classify_congestion,
    classify_overall_status,
    load_predictions,
    aggregate_zones,
    load_live_incidents,
    analyze_traffic,
    build_report,
    _PREDICTIONS_PATH,
)
from backend.app.mobility.traffic.data import TrafficReport, ZoneReport, IncidentReport
from backend.app.mobility.traffic.geo_zones import get_all_zones, get_zone
from backend.app.mobility.traffic.predictor import LinkPrediction
from backend.app.mobility.traffic.prediction_service import PredictionBundle

# ---------------------------------------------------------------------------
# Prediction bundle fixtures
# ---------------------------------------------------------------------------
# load_predictions reads the shared TrafficPredictionService bundle. These
# helpers build a valid bundle so the tests exercise the real contract
# instead of the removed CSV read.

def _link(link_id, zone_id, zone_name, current, predicted):
    return LinkPrediction(
        link_id=link_id, road_name=f"Road {link_id}", road_category="highway",
        zone_id=zone_id, zone_name=zone_name,
        current_speed=current, predicted_speed=predicted,
        speed_change=predicted - current,
        prediction_timestamp="2022-03-25 00:00:00",
        target_timestamp="2022-03-25 00:05:00",
    )


def _bundle(links, diagnostics=None):
    """A PredictionBundle carrying LinkPrediction rows."""
    return PredictionBundle(
        observed_at="2022-03-25 00:00:00",
        features_df=pd.DataFrame(),
        link_preds=list(links),
        diagnostics=diagnostics or {},
        computed_at_epoch=0.0,
        compute_seconds=0.0,
    )


def _patch_bundle(bundle):
    """Patch the prediction service that load_predictions imports at call time."""
    service = MagicMock()
    service.get_bundle.return_value = bundle
    return patch(
        "backend.app.mobility.traffic.prediction_service.get_traffic_prediction_service",
        return_value=service,
    )


def _zone_links():
    """One prediction per real zone, so all 8 zones aggregate."""
    return [_link(str(i), z["zone_id"], z["zone_name"], 50.0 + i, 52.0 + i)
            for i, z in enumerate(get_all_zones())]



class TestTrafficAgentNodes:
    """Test individual nodes of the Traffic Agent."""
    
    def test_classify_congestion(self):
        assert classify_congestion(80) == "free_flow"
        assert classify_congestion(60) == "moderate"
        assert classify_congestion(40) == "heavy"
        assert classify_congestion(20) == "severe"
        assert classify_congestion(None) == "unknown"
    
    def test_classify_overall_status(self):
        assert classify_overall_status(70, 0) == "normal"
        assert classify_overall_status(50, 0) == "elevated"
        assert classify_overall_status(30, 0) == "disrupted"
        assert classify_overall_status(60, 5) == "normal"
        assert classify_overall_status(40, 5) == "elevated"
        assert classify_overall_status(None, 0) == "unknown"
    
    def test_load_predictions_success(self):
        """Test loading predictions with mocked data."""
        # Create mock predictions data
        mock_df = pd.DataFrame({
            "entity_id": [0, 0, 1, 1],
            "timestamp": ["2022-03-25 00:00:00", "2022-03-25 00:10:00", "2022-03-25 00:00:00", "2022-03-25 00:10:00"],
            "traffic_speed": [60.0, 55.0, 50.0, 45.0],
            "predicted_speed": [58.0, 56.0, 52.0, 44.0],
            "error": [-2.0, 1.0, 2.0, -1.0],
        })
        
        bundle = _bundle([
            _link("0", "SG_NORTH", "North", 60.0, 58.0),
            _link("0", "SG_NORTH", "North", 55.0, 56.0),
            _link("1", "SG_EAST", "East", 50.0, 52.0),
            _link("1", "SG_EAST", "East", 45.0, 44.0),
        ])
        with _patch_bundle(bundle):
            state = TrafficAgentState()
            result = load_predictions(state)

        assert result.predictions_df is not None
        assert len(result.predictions_df) == 4
        assert "total_rows" in result.predictions_summary
        assert result.predictions_summary["unique_segments"] == 2
    
    def test_load_predictions_file_not_found(self):
        """Test loading predictions when file doesn't exist."""
        # No bundle available: the node must record an error, not invent data.
        with _patch_bundle(None):
            state = TrafficAgentState()
            result = load_predictions(state)

        assert len(result.errors) > 0
        assert result.predictions_df is None
        assert "no traffic observations" in result.errors[0].lower()
    
    def test_aggregate_zones_refuses_to_invent_demo_zones(self):
        """Predictions without a zone_id must NOT produce fabricated zones.

        Demo-zone synthesis was deliberately removed: the agent refuses to
        invent geographic data rather than fabricating it.
        """
        mock_df = pd.DataFrame({
            "entity_id": [0, 1, 2],
            "traffic_speed": [50.0, 55.0, 60.0],
            "predicted_speed": [52.0, 53.0, 58.0],
        })

        state = TrafficAgentState(predictions_df=mock_df)
        result = aggregate_zones(state)

        assert result.zone_predictions == {}
        assert len(result.warnings) > 0
        assert "zone_id" in result.warnings[0]

    def test_aggregate_zones_maps_real_zone_ids(self):
        """With real zone_ids every zone aggregates without fabrication."""
        state = TrafficAgentState()
        state.predictions_df = pd.DataFrame([
            {"entity_id": i, "zone_id": z["zone_id"], "zone_name": z["zone_name"],
             "traffic_speed": 50.0 + i, "predicted_speed": 52.0 + i,
             "timestamp": "2022-03-25 00:00:00"}
            for i, z in enumerate(get_all_zones())
        ])
        result = aggregate_zones(state)

        assert len(result.zone_predictions) == 8
        for zone_id, pred in result.zone_predictions.items():
            assert pred["is_demo_zone"] is False
            assert pred["segment_count"] == 1
            assert pred["current_average_speed"] is not None
            assert pred["congestion_level"] != "unknown"

    def test_load_live_incidents_offline(self):
        """Test loading live incidents in offline mode."""
        with patch("backend.app.mobility.traffic.api.TrafficIncidentsApiClient") as mock_client_class:
            mock_client = MagicMock()
            mock_snapshot = MagicMock()
            mock_snapshot.to_dict.return_value = {
                "incidents": [
                    {"type": "Accident", "message": "Test", "latitude": 1.3, "longitude": 103.8, "zone_id": "SG_CENTRAL_SOUTH", "zone_name": "Central South"},
                    {"type": "Roadwork", "message": "Test 2", "latitude": 1.35, "longitude": 103.9, "zone_id": "SG_EAST", "zone_name": "East"},
                ],
                "is_live": False,
            }
            mock_client.fetch.return_value = mock_snapshot
            mock_client_class.return_value = mock_client
            
            state = TrafficAgentState()
            os.environ["TRAFFIC_AGENT_OFFLINE"] = "true"
            result = load_live_incidents(state)
        
        assert len(result.live_incidents) == 2
        assert "SG_CENTRAL_SOUTH" in result.incidents_by_zone
        assert "SG_EAST" in result.incidents_by_zone
    
    def test_load_live_incidents_error_handling(self):
        """Test error handling when LTA API fails."""
        with patch("backend.app.mobility.traffic.api.TrafficIncidentsApiClient") as mock_client_class:
            mock_client_class.side_effect = Exception("Network error")
            
            state = TrafficAgentState()
            os.environ["TRAFFIC_AGENT_OFFLINE"] = "true"
            result = load_live_incidents(state)
        
        assert len(result.errors) > 0
        assert "Network error" in result.errors[0] or "live incidents" in result.errors[0].lower()
    
    def test_analyze_traffic(self):
        """Test traffic analysis combines predictions and incidents."""
        state = TrafficAgentState(
            zone_predictions={
                "SG_CENTRAL_SOUTH": {
                    "zone_id": "SG_CENTRAL_SOUTH",
                    "zone_name": "Central South",
                    "current_average_speed": 50.0,
                    "predicted_average_speed": 48.0,
                    "speed_change": -2.0,
                    "speed_change_percent": -4.0,
                    "congestion_level": "moderate",
                    "segment_count": 0,
                    "is_demo_zone": True,
                },
                "SG_EAST": {
                    "zone_id": "SG_EAST",
                    "zone_name": "East",
                    "current_average_speed": 60.0,
                    "predicted_average_speed": 58.0,
                    "speed_change": -2.0,
                    "speed_change_percent": -3.3,
                    "congestion_level": "moderate",
                    "segment_count": 0,
                    "is_demo_zone": True,
                },
            },
            incidents_by_zone={
                "SG_CENTRAL_SOUTH": [{"type": "Accident", "message": "Test"}],
            }
        )
        
        result = analyze_traffic(state)
        
        assert len(result.zone_reports) == 2
        assert result.overall_stats["total_incidents"] == 1
        assert result.overall_stats["overall_average_speed"] is not None
    
    def test_build_report(self):
        """Test building final TrafficReport."""
        
        state = TrafficAgentState(
            zone_reports=[
                ZoneReport(
                    zone_id="SG_CENTRAL_SOUTH",
                    zone_name="Central South",
                    is_demo_zone=True,
                    current_average_speed=50.0,
                    predicted_average_speed=48.0,
                    speed_change=-2.0,
                    speed_change_percent=-4.0,
                    congestion_level="moderate",
                    segment_count=0,
                    incident_count=1,
                )
            ],
            live_incidents=[
                {"type": "Accident", "message": "Test accident", "latitude": 1.3, "longitude": 103.8, "zone_id": "SG_CENTRAL_SOUTH", "zone_name": "Central South"},
            ],
            overall_stats={
                "overall_average_speed": 50.0,
                "overall_predicted_speed": 48.0,
                "overall_speed_change_percent": -4.0,
                "overall_congestion_level": "moderate",
                "overall_status": "elevated",
                "total_incidents": 1,
            },
            warnings=["Test warning"],
            errors=[],
        )
        
        result = build_report(state)
        
        assert result.report is not None
        assert isinstance(result.report, TrafficReport)
        assert len(result.report.zones) == 1
        assert len(result.report.incidents) == 1
        assert result.report.overall_status == "elevated"
        assert len(result.report.limitations) > 0
        assert any("geographic coordinates" in lim for lim in result.report.limitations)


class TestTrafficAgentIntegration:
    """Integration tests for the full Traffic Agent workflow."""
    
    def _mock_setup(self):
        """Common mock setup for integration tests."""
        bundle = _bundle(_zone_links())

        mock_client = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.to_dict.return_value = {"incidents": [], "is_live": False}
        mock_client.fetch.return_value = mock_snapshot

        return bundle, mock_client
    
    def test_langgraph_executes_successfully(self):
        """Test that LangGraph workflow runs without errors."""
        bundle, mock_client = self._mock_setup()
        
        with _patch_bundle(bundle), \
             patch("backend.app.mobility.traffic.api.TrafficIncidentsApiClient", return_value=mock_client):
            
            graph = create_traffic_agent()
            initial_state = TrafficAgentState()
            result = graph.invoke(initial_state)
        
        assert result.get("report") is not None
        assert isinstance(result["report"], TrafficReport)
    
    def test_traffic_report_schema_valid(self):
        """Test that TrafficReport has all required fields."""
        bundle, mock_client = self._mock_setup()
        
        with _patch_bundle(bundle), \
             patch("backend.app.mobility.traffic.api.TrafficIncidentsApiClient", return_value=mock_client):
            
            graph = create_traffic_agent()
            result = graph.invoke(TrafficAgentState())
            report = result["report"]
        
        # Check all required fields exist
        assert hasattr(report, "generated_at")
        assert hasattr(report, "prediction_horizon_minutes")
        assert hasattr(report, "overall_status")
        assert hasattr(report, "overall_average_speed")
        assert hasattr(report, "overall_predicted_speed")
        assert hasattr(report, "overall_speed_change_percent")
        assert hasattr(report, "overall_congestion_level")
        assert hasattr(report, "zones")
        assert hasattr(report, "incidents")
        assert hasattr(report, "limitations")
        
        # Check zones structure
        assert len(report.zones) == 8
        for zone in report.zones:
            assert hasattr(zone, "zone_id")
            assert hasattr(zone, "zone_name")
            assert hasattr(zone, "is_demo_zone")
            assert hasattr(zone, "current_average_speed")
            assert hasattr(zone, "predicted_average_speed")
            assert hasattr(zone, "speed_change")
            assert hasattr(zone, "speed_change_percent")
            assert hasattr(zone, "congestion_level")
            assert hasattr(zone, "segment_count")
            assert hasattr(zone, "incident_count")
    
    def test_empty_incidents_handled(self):
        """Test that empty incident list is handled gracefully."""
        bundle, mock_client = self._mock_setup()
        
        with _patch_bundle(bundle), \
             patch("backend.app.mobility.traffic.api.TrafficIncidentsApiClient", return_value=mock_client):
            
            graph = create_traffic_agent()
            result = graph.invoke(TrafficAgentState())
            report = result["report"]
        
        assert report.incidents == []
        assert report.overall_status in ["normal", "elevated", "disrupted", "unknown"]
    
    def test_lta_failure_handled_gracefully(self):
        """Test that LTA API failure is handled gracefully."""
        bundle = _bundle([_link("0", "SG_NORTH", "North", 50.0, 52.0)])

        with _patch_bundle(bundle), \
             patch("backend.app.mobility.traffic.api.TrafficIncidentsApiClient", side_effect=Exception("LTA API unavailable")):
            
            graph = create_traffic_agent()
            result = graph.invoke(TrafficAgentState())
            
            # Should still produce a report, but with errors recorded
            assert result.get("report") is not None
            assert len(result.get("errors", [])) > 0
    
    def test_missing_ml_prediction_data_handled(self):
        """Test that a missing prediction bundle degrades without crashing."""
        mock_client = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.to_dict.return_value = {"incidents": [], "is_live": False}
        mock_client.fetch.return_value = mock_snapshot

        with _patch_bundle(None), \
             patch("backend.app.mobility.traffic.api.TrafficIncidentsApiClient", return_value=mock_client):

            graph = create_traffic_agent()
            result = graph.invoke(TrafficAgentState())
            report = result["report"]

        # Invariant: the graph completes and the failure is recorded, not hidden.
        # build_report deliberately emits no report when no zone data exists,
        # rather than fabricating one.
        assert report is None
        assert result["errors"], "missing prediction data must be recorded"
        assert any("prediction" in e.lower() or "zone" in e.lower()
                   for e in result["errors"] + result["warnings"])

    def test_zone_lookup_works(self):
        """Test that zone lookup works for known coordinates."""
        # get_zone imported from backend.app.mobility.traffic.geo_zones at top
        
        # Test known Singapore coordinates
        result = get_zone(1.291, 103.851)  # Marina Bay
        assert result["zone_id"] is not None
        assert result["zone_name"] != "unknown"
        
        # Test outside Singapore
        result = get_zone(0, 0)
        assert result["zone_id"] is None
        assert result["zone_name"] == "unknown"
    
    def test_no_fake_geographic_mapping_created(self):
        """Test that no fake segment-to-zone mapping is created."""
        zones = get_all_zones()
        bundle = _bundle([
            _link(str(i), zones[i % len(zones)]["zone_id"],
                  zones[i % len(zones)]["zone_name"], 50.0, 52.0)
            for i in range(100)
        ])

        mock_client = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.to_dict.return_value = {"incidents": [], "is_live": False}
        mock_client.fetch.return_value = mock_snapshot
        
        with _patch_bundle(bundle), \
             patch("backend.app.mobility.traffic.api.TrafficIncidentsApiClient", return_value=mock_client):
            
            graph = create_traffic_agent()
            result = graph.invoke(TrafficAgentState())
        
        # Check that zone reports are marked as demo (now real zones, so False)
        for zone in result["report"].zones:
            assert zone.is_demo_zone is False
        
        # Check limitations mention no geographic mapping
        limitations_text = " ".join(result["report"].limitations)
        assert "geographic coordinates" in limitations_text
        assert "limited" in limitations_text
    
    def test_report_contains_all_required_fields(self):
        """Test that the final report contains all required fields with valid values."""
        bundle, mock_client = self._mock_setup()
        mock_snapshot = MagicMock()
        mock_snapshot.to_dict.return_value = {
            "incidents": [
                {"type": "Accident", "message": "Test", "latitude": 1.3, "longitude": 103.8, "zone_id": "SG_CENTRAL_SOUTH", "zone_name": "Central South"},
            ],
            "is_live": False,
        }
        mock_client.fetch.return_value = mock_snapshot
        
        with _patch_bundle(bundle), \
             patch("backend.app.mobility.traffic.api.TrafficIncidentsApiClient", return_value=mock_client):
            
            graph = create_traffic_agent()
            result = graph.invoke(TrafficAgentState())
            report = result["report"]
        
        # Check zone fields
        for zone in report.zones:
            assert zone.zone_id is not None
            assert zone.zone_name is not None
            assert zone.is_demo_zone is False
            assert zone.congestion_level in ["free_flow", "moderate", "heavy", "severe", "unknown"]
            assert zone.incident_count >= 0
        
        # Check incident fields
        for inc in report.incidents:
            assert inc.type is not None
            assert inc.message is not None
            assert inc.zone_id is not None
            assert inc.zone_name is not None
    
    def test_numerical_values_deterministic(self):
        """Test that numerical values are deterministic across runs."""
        bundle, mock_client = self._mock_setup()
        
        with _patch_bundle(bundle), \
             patch("backend.app.mobility.traffic.api.TrafficIncidentsApiClient", return_value=mock_client), \
             patch("backend.app.mobility.traffic.agent.load_live_speeds",
                   side_effect=lambda state: state):
            # load_live_speeds calls the live LTA API, so without this stub the
            # two runs below see different input depending on network
            # conditions, which is not what this test is asserting.
            graph = create_traffic_agent()
            
            # Run twice
            result1 = graph.invoke(TrafficAgentState())
            result2 = graph.invoke(TrafficAgentState())
            
            # Compare zone values
            for z1, z2 in zip(result1["report"].zones, result2["report"].zones):
                assert z1.current_average_speed == z2.current_average_speed
                assert z1.predicted_average_speed == z2.predicted_average_speed
                assert z1.speed_change == z2.speed_change
                assert z1.speed_change_percent == z2.speed_change_percent
    
    def test_agent_does_not_modify_ml_model(self):
        """Test that the agent does not modify the ML model file."""
        # The old traffic_speed_predictor.pkl was replaced by the XGBoost
        # artifact resolved from the repo root, not from the current directory.
        from backend.app.mobility.traffic.predictor import MODEL_PATH
        model_path = Path(MODEL_PATH)
        if not model_path.is_absolute():
            model_path = Path(__file__).resolve().parents[1] / model_path
        assert model_path.exists(), f"model artifact missing: {model_path}"
        mtime_before = model_path.stat().st_mtime
        
        bundle, mock_client = self._mock_setup()
        
        with _patch_bundle(bundle), \
             patch("backend.app.mobility.traffic.api.TrafficIncidentsApiClient", return_value=mock_client):
            
            graph = create_traffic_agent()
            graph.invoke(TrafficAgentState())
        
        mtime_after = model_path.stat().st_mtime
        assert mtime_before == mtime_after, "ML model file was modified!"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])