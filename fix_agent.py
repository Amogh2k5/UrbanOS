import re

# Read the file
with open(r'C:\projects\UrbanOS\backend\app\mobility\traffic\agent.py', 'r') as f:
    content = f.read()

# Replace the load_predictions function
old_function = '''# ============================================================
# NODE 1: LOAD_PREDICTIONS
# ============================================================
def load_predictions(state: TrafficAgentState) -> TrafficAgentState:
    """Load real-time XGBoost predictions from live traffic observations."""
    log.info("Loading real-time traffic predictions via TrafficPredictor...")
    
    try:
        from backend.app.mobility.traffic.data import TrafficObservationStore
        store = TrafficObservationStore()
        predictor = TrafficPredictor()
        features_df, link_preds, diagnostics = predictor.predict_latest(store)
        
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
        
        log.info(f"Generated {len(df)} real-time predictions for {df['entity_id'].nunique()} segments")
        
    except Exception as e:
        state.errors.append(f"Failed to generate real-time predictions: {str(e)}")
        log.exception("Error generating real-time predictions")
        # Fallback to static CSV if available
        try:
            if _PREDICTIONS_PATH.exists():
                df = pd.read_csv(_PREDICTIONS_PATH)
                if not df.empty:
                    state.predictions_df = df
                    state.warnings.append("Fell back to static CSV predictions")
                    log.warning("Using static CSV predictions as fallback")
        except Exception:
            pass
    
    return state

# ============================================================
# NODE 2: AGGREGATE_ZONES
'''

new_function = '''# ============================================================
# NODE 1: LOAD_PREDICTIONS
# ============================================================
def load_predictions(state: TrafficAgentState) -> TrafficAgentState:
    """Load real-time XGBoost predictions from live traffic observations.
    
    In offline mode (TRAFFIC_AGENT_OFFLINE=true), falls back to static CSV predictions.
    """
    import os
    offline = os.getenv("TRAFFIC_AGENT_OFFLINE", "false").lower() == "true"
    
    if offline:
        log.info("Offline mode: loading static CSV predictions")
        try:
            if _PREDICTIONS_PATH.exists():
                df = pd.read_csv(_PREDICTIONS_PATH)
                if not df.empty:
                    state.predictions_df = df
                    state.warnings.append("Using static CSV predictions (offline mode)")
                    log.warning("Using static CSV predictions (offline mode)")
                else:
                    state.errors.append("Static CSV predictions file is empty")
            else:
                state.errors.append("Static CSV predictions file not found")
            return state
    
    log.info("Loading real-time traffic predictions via TrafficPredictor...")
    
    try:
        from backend.app.mobility.traffic.data import TrafficObservationStore
        store = TrafficObservationStore()
        predictor = TrafficPredictor()
        features_df, link_preds, diagnostics = predictor.predict_latest(store)
        
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
        state.errors.append(f"Failed to generate real-time predictions: {str(e)}")
        log.exception("Error generating real-time predictions")
        # Fallback to static CSV if available
        try:
            if _PREDICTIONS_PATH.exists():
                df = pd.read_csv(_PREDICTIONS_PATH)
                if not df.empty:
                    state.predictions_df = df
                    state.warnings.append("Fell back to static CSV predictions")
                    log.warning("Using static CSV predictions as fallback")
        except Exception:
            pass
    
    return state

# ============================================================
# NODE 2: AGGREGATE_ZONES
'''

# Read the file
with open(r'C:\projects\UrbanOS\backend\app\mobility\traffic\agent.py', 'r') as f:
    content = f.read()

# Replace the load_predictions function
old_pattern = r'# ============================================================\n# NODE 1: LOAD_PREDICTIONS\n# ============================================================\ndef load_predictions\(state: TrafficAgentState\) -> TrafficAgentState:\n    """Load real-time XGBoost predictions from live traffic observations\."""\n    log\.info\("Loading real-time traffic predictions via TrafficPredictor\.\.\."\)\n    
    try:
        from backend\.app\.mobility\.traffic\.data import TrafficObservationStore
        store = TrafficObservationStore\(\)
        predictor = TrafficPredictor\(\)
        features_df, link_preds, diagnostics = predictor\.predict_latest\(store\)
        
        # Convert LinkPrediction list to DataFrame compatible with downstream nodes
        pred_rows = \[\]
        for lp in link_preds:
            pred_rows\.append\(\{
                "entity_id": lp\.link_id,
                "road_name": lp\.road_name,
                "road_category": lp\.road_category,
                "zone_id": lp\.zone_id,
                "zone_name": lp\.zone_name,
                "traffic_speed": lp\.current_speed,
                "predicted_speed": lp\.predicted_speed,
                "timestamp": lp\.prediction_timestamp,
                "target_timestamp": lp\.target_timestamp,
            \}\)
        df = pd\.DataFrame\(pred_rows\)
        
        if df\.empty:
            state\.errors\.append\("No predictions generated"\)
            return state
        
        state\.predictions_df = df
        state\.predictions_summary = \{
            "total_rows": len\(df\),
            "unique_segments": df\["entity_id"\]\.nunique\(\),
            "timestamp_range": \{
                "min": df\["timestamp"\]\.min\(\),
                "max": df\["timestamp"\]\.max\(\)
            \},
            "overall_actual_avg": float\(df\["traffic_speed"\]\.mean\(\)\),
            "overall_predicted_avg": float\(df\["predicted_speed"\]\.mean\(\)\),
            "overall_mae": float\(\(df\["traffic_speed"\] - df\["predicted_speed"\]\)\.abs\(\)\.mean\(\)\),
            "diagnostics": diagnostics,
        \}
        
        log\.info\(f"Generated \{len\(df\)\} real-time predictions for \{df\['entity_id'\]\.nunique\(\)\} segments"\)
        
        log\.info\(f"Generated \{len\(df\)\} real-time predictions for \{df\['entity_id'\]\.nunique\(\)\} segments"\)
        
    except Exception as e:
        state\.errors\.append\(f"Failed to generate real-time predictions: \{str\(e\)\}"\)
        log\.exception\("Error generating real-time predictions"\)
        # Fallback to static CSV if available
        try:
            if _PREDICTIONS_PATH\.exists\(\):
                df = pd\.read_csv\(_PREDICTIONS_PATH\)
                if not df\.empty:
                    state\.predictions_df = df
                    state\.warnings\.append\("Fell back to static CSV predictions"\)
                    log\.warning\("Using static CSV predictions as fallback"\)
        except Exception:
            pass
    
    return state

# ============================================================
# NODE 2: AGGREGATE_ZONES'''

new_content = '''# ============================================================
# NODE 1: LOAD_PREDICTIONS
# ============================================================
def load_predictions(state: TrafficAgentState) -> TrafficAgentState:
    """Load real-time XGBoost predictions from live traffic observations.
    
    In offline mode (TRAFFIC_AGENT_OFFLINE=true), falls back to static CSV predictions.
    """
    import os
    offline = os.getenv("TRAFFIC_AGENT_OFFLINE", "false").lower() == "true"
    
    if offline:
        log.info("Offline mode: loading static CSV predictions")
        try:
            if _PREDICTIONS_PATH.exists():
                df = pd.read_csv(_PREDICTIONS_PATH)
                if not df.empty:
                    state.predictions_df = df
                    state.warnings.append("Using static CSV predictions (offline mode)")
                    log.warning("Using static CSV predictions (offline mode)")
                else:
                    state.errors.append("Static CSV predictions file is empty")
            else:
                state.errors.append("Static CSV predictions file not found")
            return state
    
    log.info("Loading real-time traffic predictions via TrafficPredictor...")
    
    try:
        from backend.app.mobility.traffic.data import TrafficObservationStore
        store = TrafficObservationStore()
        predictor = TrafficPredictor()
        features_df, link_preds, diagnostics = predictor.predict_latest(store)
        
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
        state.errors.append(f"Failed to generate real-time predictions: {str(e)}")
        log.exception("Error generating real-time predictions")
        # Fallback to static CSV if available
        try:
            if _PREDICTIONS_PATH.exists():
                df = pd.read_csv(_PREDICTIONS_PATH)
                if not df.empty:
                    state.predictions_df = df
                    state.warnings.append("Fell back to static CSV predictions")
                    log.warning("Using static CSV predictions as fallback")
        except Exception:
            pass
    
    return state

# ============================================================
# NODE 2: AGGREGATE_ZONES
'''

import re
content = re.sub(r'# ============================================================\n# NODE 1: LOAD_PREDICTIONS\n# ============================================================\ndef load_predictions\(state: TrafficAgentState\) -> TrafficAgentState:\n    """Load real-time XGBoost predictions from live traffic observations\."""\n    log\.info\("Loading real-time traffic predictions via TrafficPredictor\.\.\."\)\n    
    try:
        from backend\.app\.mobility\.traffic\.data import TrafficObservationStore
        store = TrafficObservationStore\(\)
        predictor = TrafficPredictor\(\)
        features_df, link_preds, diagnostics = predictor\.predict_latest\(store\)
        
        # Convert LinkPrediction list to DataFrame compatible with downstream nodes
        pred_rows = \[\]
        for lp in link_preds:
            pred_rows\.append\(\{
                "entity_id": lp\.link_id,
                "road_name": lp\.road_name,
                "road_category": lp\.road_category,
                "zone_id": lp\.zone_id,
                "zone_name": lp\.zone_name,
                "traffic_speed": lp\.current_speed,
                "predicted_speed": lp\.predicted_speed,
                "timestamp": lp\.prediction_timestamp,
                "target_timestamp": lp\.target_timestamp,
            \}\)
        df = pd\.DataFrame\(pred_rows\)
        
        if df\.empty:
            state\.errors\.append\("No predictions generated"\)
            return state
        
        state\.predictions_df = df
        state\.predictions_summary = \{
            "total_rows": len\(df\),
            "unique_segments": df\["entity_id"\]\.nunique\(\),
            "timestamp_range": \{
                "min": df\["timestamp"\]\.min\(\),
                "max": df\["timestamp"\]\.max\(\)
            \},
            "overall_actual_avg": float\(df\["traffic_speed"\]\.mean\(\)\),
            "overall_predicted_avg": float\(df\["predicted_speed"\]\.mean\(\)\),
            "overall_mae": float\(\(df\["traffic_speed"\] - df\["predicted_speed"\]\)\.abs\(\)\.mean\(\)\),
            "diagnostics": diagnostics,
        \}
        
        log\.info\(f"Generated \{len\(df\)\} real-time predictions for \{df\['entity_id'\]\.nunique\(\)\} segments"\)
        
        log\.info\(f"Generated \{len\(df\)\} real-time predictions for \{df\['entity_id'\]\.nunique\(\)\} segments"\)
        
    except Exception as e:
        state\.errors\.append\(f"Failed to generate real-time predictions: \{str\(e\)\}"\)
        log\.exception\("Error generating real-time predictions"\)
        # Fallback to static CSV if available
        try:
            if _PREDICTIONS_PATH\.exists\(\):
                df = pd\.read_csv\(_PREDICTIONS_PATH\)
                if not df\.empty:
                    state\.predictions_df = df
                    state\.warnings\.append\("Fell back to static CSV predictions"\)
                    log\.warning\("Using static CSV predictions as fallback"\)
        except Exception:
            pass
    
    return state

# ============================================================
# NODE 2: AGGREGATE_ZONES''', new_content, content, flags=re.DOTALL)

# Write the file
with open(r'C:\projects\UrbanOS\backend\app\mobility\traffic\agent.py', 'w') as f:
    f.write(content)

print("Done")