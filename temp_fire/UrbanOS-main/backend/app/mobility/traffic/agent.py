"""Traffic Agent - LangGraph workflow for combining ML predictions, live incidents, and zones."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from langgraph.graph import END, StateGraph

# Local imports (new location)
from backend.app.mobility.traffic.data import TrafficReport, ZoneReport, IncidentReport
from backend.app.mobility.traffic.geo_zones import get_all_zones
from backend.app.mobility.traffic.predictor import TrafficPredictor, LinkPrediction

log = logging.getLogger(__name__)

# Prediction data path (relative to project root)
_PREDICTIONS_PATH = Path("traffic/data/processed/real_day_predictions.csv")
# Default prediction horizon (10 minutes - matching the data interval)
_PREDICTION_HORIZON_MINUTES = 10

# Congestion thresholds (km/h)
CONGESTION_THRESHOLDS = {
    "free_flow": 70,
    "moderate": 50,
    "heavy": 30,
    "severe": 0,
}


@dataclass
class TrafficAgentState:
    """LangGraph state for Traffic Agent."""
    # Raw/summarized data
    predictions_df: Optional[pd.DataFrame] = None
    predictions_summary: Dict[str, Any] = field(default_factory=dict)
    
    # Zone aggregation
    zone_predictions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Live incidents
    live_incidents: List[Dict[str, Any]] = field(default_factory=list)
    incidents_by_zone: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    
    # Live speeds (from LTA speed bands)
    live_zone_speeds: Dict[str, float] = field(default_factory=dict)
    
    # Analysis
    overall_stats: Dict[str, Any] = field(default_factory=dict)
    zone_reports: List[ZoneReport] = field(default_factory=list)
    
    # Final report
    report: Optional[TrafficReport] = None
    
    # Error tracking
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def classify_congestion(speed: Optional[float]) -> str:
    """Classify congestion level based on speed."""
    if speed is None:
        return "unknown"
    if speed >= CONGESTION_THRESHOLDS["free_flow"]:
        return "free_flow"
    elif speed >= CONGESTION_THRESHOLDS["moderate"]:
        return "moderate"
    elif speed >= CONGESTION_THRESHOLDS["heavy"]:
        return "heavy"
    else:
        return "severe"


def classify_overall_status(avg_speed: Optional[float], incident_count: int = 0) -> str:
    """Classify overall traffic status based on speed only (incidents are informational)."""
    if avg_speed is None:
        return "unknown"
    if avg_speed >= 60:
        return "normal"
    elif avg_speed >= 40:
        return "elevated"
    else:
        return "disrupted"


# ============================================================
# NODE 1: LOAD_PREDICTIONS
# ============================================================
def load_predictions(state: TrafficAgentState) -> TrafficAgentState:
    """Load real-time XGBoost predictions from live traffic observations."""
    log.info("Loading real-time traffic predictions via TrafficPredictor (CSV-backed)...")
    
    try:
        # Consume the shared PredictionBundle from TrafficPredictionService:
        # one XGBoost computation per new snapshot, computed in the background
        # by the service — this node never runs predict_latest() itself.
        from backend.app.mobility.traffic.prediction_service import (
            get_traffic_prediction_service,
        )
        bundle = get_traffic_prediction_service().get_bundle()
        if bundle is None or not bundle.link_preds:
            # Preserve the historical no-data behaviour (fallback below).
            raise ValueError("No traffic observations available (prediction bundle not found)")
        link_preds = bundle.link_preds
        diagnostics = bundle.diagnostics

        # Convert LinkPrediction list to DataFrame compatible with downstream nodes
        pred_rows = []
        for lp in link_preds:
            pred_rows.append({
                "entity_id": lp.link_id,
                "road_name": lp.road_name,
                "road_category": lp.road_category,
                "zone_id": lp.zone_id,
                "zone_name": lp.zone_name,
                "traffic_speed": lp.current_speed,
                "predicted_speed": lp.predicted_speed,
                "timestamp": lp.prediction_timestamp,
                "target_timestamp": lp.target_timestamp,
            })
        df = pd.DataFrame(pred_rows)
        
        if df.empty:
            state.errors.append("No predictions generated")
            return state
        
        state.predictions_df = df
        state.predictions_summary = {
            "total_rows": len(df),
            "unique_segments": df["entity_id"].nunique(),
            "timestamp_range": {
                "min": df["timestamp"].min(),
                "max": df["timestamp"].max(),
            },
            "overall_actual_avg": float(df["traffic_speed"].mean()),
            "overall_predicted_avg": float(df["predicted_speed"].mean()),
            "overall_mae": float((df["traffic_speed"] - df["predicted_speed"]).abs().mean()),
            "diagnostics": diagnostics,
        }
        
        log.info(f"Generated {len(df)} real-time predictions for {df['entity_id'].nunique()} segments")
        
    except Exception as e:
        state.errors.append(f"Failed to load predictions: {str(e)}")
        log.exception("Error generating real-time predictions")
        # Fallback to static CSV if available
        try:
            if _PREDICTIONS_PATH.exists():
                df = pd.read_csv(_PREDICTIONS_PATH)
                if not df.empty:
                    state.predictions_df = df
                    state.warnings.append("Fell back to static CSV predictions")
                    # Summarize the fallback frame defensively (columns vary).
                    try:
                        cols = set(df.columns)
                        state.predictions_summary = {
                            "total_rows": len(df),
                            "unique_segments": int(df["entity_id"].nunique()) if "entity_id" in cols else 0,
                            "timestamp_range": {
                                "min": df["timestamp"].min() if "timestamp" in cols else None,
                                "max": df["timestamp"].max() if "timestamp" in cols else None,
                            },
                            "overall_actual_avg": float(df["traffic_speed"].mean()) if "traffic_speed" in cols else None,
                            "overall_predicted_avg": float(df["predicted_speed"].mean()) if "predicted_speed" in cols else None,
                            "overall_mae": (
                                float((df["traffic_speed"] - df["predicted_speed"]).abs().mean())
                                if {"traffic_speed", "predicted_speed"} <= cols else None
                            ),
                            "diagnostics": {"fallback": "static_csv"},
                        }
                    except Exception:
                        log.exception("Failed to summarize fallback predictions")
                    log.warning("Using static CSV predictions as fallback")
        except Exception:
            pass
    
    return state


# ============================================================
# NODE 2: AGGREGATE_ZONES
# ============================================================
def aggregate_zones(state: TrafficAgentState) -> TrafficAgentState:
    """Aggregate segment-level predictions into geographic zones using real zone_id."""
    log.info("Aggregating real-time predictions to zones...")
    
    if state.predictions_df is None:
        state.warnings.append("No predictions data available for zone aggregation")
        return state
    
    try:
        df = state.predictions_df
        
        # Ensure zone_id column exists (from real-time predictor)
        if "zone_id" not in df.columns:
            state.warnings.append("Predictions missing zone_id; cannot aggregate to zones")
            return state
        
        # Drop rows without zone mapping
        df_mapped = df[df["zone_id"].notna()].copy()
        if df_mapped.empty:
            state.warnings.append("No segments mapped to zones")
            return state
        
        zones = get_all_zones()
        zone_lookup = {z["zone_id"]: z["zone_name"] for z in zones}
        
        for zone in zones:
            zone_id = zone["zone_id"]
            zone_name = zone["zone_name"]
            zone_df = df_mapped[df_mapped["zone_id"] == zone_id]
            
            if zone_df.empty:
                # No segments in this zone
                state.zone_predictions[zone_id] = {
                    "zone_id": zone_id,
                    "zone_name": zone_name,
                    "current_average_speed": None,
                    "predicted_average_speed": None,
                    "speed_change": None,
                    "speed_change_percent": None,
                    "congestion_level": "unknown",
                    "segment_count": 0,
                    "is_demo_zone": False,
                }
                continue
            
            actual_avg = float(zone_df["traffic_speed"].mean())
            pred_avg = float(zone_df["predicted_speed"].mean())
            change = pred_avg - actual_avg
            change_pct = (change / actual_avg * 100) if actual_avg != 0 else 0
            
            state.zone_predictions[zone_id] = {
                "zone_id": zone_id,
                "zone_name": zone_name,
                "current_average_speed": round(actual_avg, 1),
                "predicted_average_speed": round(pred_avg, 1),
                "speed_change": round(change, 1),
                "speed_change_percent": round(change_pct, 1),
                "congestion_level": classify_congestion(actual_avg),
                "segment_count": int(len(zone_df)),
                "is_demo_zone": False,
            }
        
        log.info(f"Aggregated predictions for {len(state.zone_predictions)} zones with real mapping")
        
    except Exception as e:
        state.errors.append(f"Failed to aggregate zones: {str(e)}")
        log.exception("Error aggregating zones")
    
    return state


# ============================================================
# NODE 3: LOAD_LIVE_INCIDENTS
# ============================================================
def load_live_incidents(state: TrafficAgentState) -> TrafficAgentState:
    """Fetch live LTA traffic incidents."""
    log.info("Loading live traffic incidents...")
    
    # Import here to ensure runtime path resolution
    try:
        from backend.app.mobility.traffic.api import TrafficIncidentsApiClient
    except Exception as e:
        state.errors.append(f"Failed to load live incidents: TrafficIncidentsApiClient not available ({e})")
        log.exception("TrafficIncidentsApiClient import failed")
        return state
    
    try:
        # Use offline mode for testing, live for production
        offline = os.getenv("TRAFFIC_AGENT_OFFLINE", "false").lower() == "true"
        
        client = TrafficIncidentsApiClient(offline=offline, allow_fallback_fixture=True)
        snapshot = client.fetch()
        
        state.live_incidents = snapshot.to_dict()["incidents"]
        
        # Group incidents by zone
        incidents_by_zone: Dict[str, List[Dict[str, Any]]] = {}
        for inc in state.live_incidents:
            zone_id = inc.get("zone_id")
            if zone_id:
                incidents_by_zone.setdefault(zone_id, []).append(inc)
        
        state.incidents_by_zone = incidents_by_zone
        
        log.info(f"Loaded {len(state.live_incidents)} live incidents (is_live={snapshot.is_live})")
        
    except Exception as e:
        state.errors.append(f"Failed to load live incidents: {str(e)}")
        log.exception("Error loading live incidents")
    
    return state


# ============================================================
# NODE 3b: LOAD_LIVE_SPEEDS
# ============================================================
def load_live_speeds(state: TrafficAgentState) -> TrafficAgentState:
    """Fetch live LTA traffic speed bands and aggregate per zone."""
    log.info("Loading live traffic speeds...")
    
    try:
        from backend.app.mobility.traffic.api import TrafficSpeedBandsV2ApiClient
    except Exception as e:
        state.errors.append(f"Failed to load live speeds: TrafficSpeedBandsV2ApiClient not available ({e})")
        log.exception("TrafficSpeedBandsV2ApiClient import failed")
        return state
    
    try:
        client = TrafficSpeedBandsV2ApiClient()
        snapshot = client.fetch()
        
        # Aggregate speed_midpoint per zone
        zone_speeds: Dict[str, List[float]] = {}
        for seg in snapshot.segments:
            zone_id = seg.zone_id
            if zone_id and seg.speed_midpoint is not None:
                zone_speeds.setdefault(zone_id, []).append(seg.speed_midpoint)
        
        live_zone_speeds = {}
        for zone_id, speeds in zone_speeds.items():
            if speeds:
                live_zone_speeds[zone_id] = round(sum(speeds) / len(speeds), 1)
        
        state.live_zone_speeds = live_zone_speeds
        log.info(f"Computed live zone speeds for {len(live_zone_speeds)} zones")
        
    except Exception as e:
        state.errors.append(f"Failed to load live speeds: {str(e)}")
        log.exception("Error loading live speeds")
    
    return state


# ============================================================
# NODE 4: ANALYZE_TRAFFIC
# ============================================================
def analyze_traffic(state: TrafficAgentState) -> TrafficAgentState:
    """Analyze traffic combining zone predictions, live incidents, and live speeds."""
    log.info("Analyzing traffic...")
    
    try:
        # Build zone reports
        zone_reports: List[ZoneReport] = []
        
        for zone_id, zone_pred in state.zone_predictions.items():
            incidents_in_zone = state.incidents_by_zone.get(zone_id, [])
            
            # Prefer live observed speed for current conditions
            current_speed = state.live_zone_speeds.get(zone_id, zone_pred.get("current_average_speed"))
            predicted_speed = zone_pred.get("predicted_average_speed")
            
            zone_report = ZoneReport(
                zone_id=zone_id,
                zone_name=zone_pred["zone_name"],
                is_demo_zone=zone_pred.get("is_demo_zone", True),
                current_average_speed=current_speed,
                predicted_average_speed=predicted_speed,
                speed_change=zone_pred.get("speed_change"),
                speed_change_percent=zone_pred.get("speed_change_percent"),
                congestion_level=zone_pred.get("congestion_level", "unknown"),
                segment_count=zone_pred.get("segment_count", 0),
                incident_count=len(incidents_in_zone),
            )
            zone_reports.append(zone_report)
        
        # Sort by zone_id for consistent ordering
        zone_reports.sort(key=lambda z: z.zone_id)
        
        state.zone_reports = zone_reports
        
        # Calculate overall stats using live speeds where available
        live_speeds = [v for v in state.live_zone_speeds.values() if v is not None]
        if live_speeds:
            overall_avg = sum(live_speeds) / len(live_speeds)
        else:
            valid_speeds = [z.current_average_speed for z in zone_reports if z.current_average_speed is not None]
            overall_avg = sum(valid_speeds) / len(valid_speeds) if valid_speeds else None
        
        valid_predicted = [z.predicted_average_speed for z in zone_reports if z.predicted_average_speed is not None]
        overall_pred = sum(valid_predicted) / len(valid_predicted) if valid_predicted else None
        overall_pred = sum(valid_predicted) / len(valid_predicted) if valid_predicted else None
        overall_change_pct = ((overall_pred - overall_avg) / overall_avg * 100) if overall_avg and overall_avg != 0 else None
        total_incidents = sum(z.incident_count for z in zone_reports)
        
        state.overall_stats = {
            "overall_average_speed": round(overall_avg, 1) if overall_avg else None,
            "overall_predicted_speed": round(overall_pred, 1) if overall_pred else None,
            "overall_speed_change_percent": round(overall_change_pct, 1) if overall_change_pct else None,
            "overall_congestion_level": classify_congestion(overall_avg),
            "overall_status": classify_overall_status(overall_avg, total_incidents),
            "total_incidents": total_incidents,
        }
        
        log.info(f"Analysis complete: overall_avg={overall_avg}, total_incidents={total_incidents}")
        
    except Exception as e:
        state.errors.append(f"Failed to analyze traffic: {str(e)}")
        log.exception("Error analyzing traffic")
    
    return state


# ============================================================
# NODE 5: BUILD_REPORT
# ============================================================
def build_report(state: TrafficAgentState) -> TrafficAgentState:
    """Build the final TrafficReport."""
    log.info("Building traffic report...")
    
    try:
        if not state.zone_reports:
            state.errors.append("No zone reports available")
            return state
        
        # Build incident reports
        incident_reports: List[IncidentReport] = []
        for inc in state.live_incidents:
            incident_reports.append(IncidentReport(
                type=inc.get("type", ""),
                message=inc.get("message", ""),
                latitude=inc.get("coordinates", {}).get("lat") if inc.get("coordinates") else inc.get("latitude"),
                longitude=inc.get("coordinates", {}).get("lon") if inc.get("coordinates") else inc.get("longitude"),
                zone_id=inc.get("zone_id"),
                zone_name=inc.get("zone_name"),
            ))
        
        # Compile limitations
        limitations = list(state.warnings)
        limitations.extend([
            "Historical ML segments do not contain geographic coordinates; "
            "zone-level ML aggregation is currently limited.",
            "Zone-level speed predictions use demo values with synthetic variation.",
            "Live incidents are sourced from LTA DataMall Traffic Incidents API.",
        ])
        
        # Add errors as limitations if any
        for err in state.errors:
            limitations.append(f"Error: {err}")
        
        report = TrafficReport(
            generated_at=datetime.now(),
            prediction_horizon_minutes=_PREDICTION_HORIZON_MINUTES,
            overall_status=state.overall_stats.get("overall_status", "unknown"),
            overall_average_speed=state.overall_stats.get("overall_average_speed"),
            overall_predicted_speed=state.overall_stats.get("overall_predicted_speed"),
            overall_speed_change_percent=state.overall_stats.get("overall_speed_change_percent"),
            overall_congestion_level=state.overall_stats.get("overall_congestion_level", "unknown"),
            zones=state.zone_reports,
            incidents=incident_reports,
            limitations=limitations,
        )
        
        state.report = report
        log.info("Traffic report built successfully")
        
    except Exception as e:
        state.errors.append(f"Failed to build report: {str(e)}")
        log.exception("Error building report")
    
    return state


# ============================================================
# BUILD LANGGRAPH WORKFLOW
# ============================================================
def create_traffic_agent() -> StateGraph:
    """Create the Traffic Agent LangGraph workflow."""
    
    workflow = StateGraph(TrafficAgentState)
    
    # Add nodes
    workflow.add_node("LOAD_PREDICTIONS", load_predictions)
    workflow.add_node("AGGREGATE_ZONES", aggregate_zones)
    workflow.add_node("LOAD_LIVE_INCIDENTS", load_live_incidents)
    workflow.add_node("LOAD_LIVE_SPEEDS", load_live_speeds)
    workflow.add_node("ANALYZE_TRAFFIC", analyze_traffic)
    workflow.add_node("BUILD_REPORT", build_report)
    
    # Add edges
    workflow.set_entry_point("LOAD_PREDICTIONS")
    workflow.add_edge("LOAD_PREDICTIONS", "AGGREGATE_ZONES")
    workflow.add_edge("AGGREGATE_ZONES", "LOAD_LIVE_INCIDENTS")
    workflow.add_edge("LOAD_LIVE_INCIDENTS", "LOAD_LIVE_SPEEDS")
    workflow.add_edge("LOAD_LIVE_SPEEDS", "ANALYZE_TRAFFIC")
    workflow.add_edge("ANALYZE_TRAFFIC", "BUILD_REPORT")
    workflow.add_edge("BUILD_REPORT", END)
    
    return workflow.compile()


# Global compiled graph
_traffic_agent_graph = None


def get_traffic_agent():
    """Get or create the compiled Traffic Agent graph."""
    global _traffic_agent_graph
    if _traffic_agent_graph is None:
        _traffic_agent_graph = create_traffic_agent()
    return _traffic_agent_graph


def run_traffic_agent(offline: bool = False) -> TrafficReport:
    """Run the Traffic Agent and return a TrafficReport.
    
    Args:
        offline: If True, use offline mode for LTA incidents (deterministic fixture).
    
    Returns:
        TrafficReport with combined ML predictions, live incidents, and zone analysis.
    """
    # Set offline mode env var for the agent run
    prev_offline = os.getenv("TRAFFIC_AGENT_OFFLINE")
    os.environ["TRAFFIC_AGENT_OFFLINE"] = "true" if offline else "false"
    
    try:
        graph = get_traffic_agent()
        initial_state = TrafficAgentState()
        result = graph.invoke(initial_state)
        
        if result.get("report") is None:
            raise RuntimeError("Traffic agent failed to produce report: " + "; ".join(result.get("errors", ["Unknown error"])))
        
        return result["report"]
    finally:
        if prev_offline is not None:
            os.environ["TRAFFIC_AGENT_OFFLINE"] = prev_offline
        else:
            os.environ.pop("TRAFFIC_AGENT_OFFLINE", None)