"""Traffic XGBoost Inference Module.

Loads the production XGBoost model and generates predictions in the format
expected by the Traffic Agent:
- timestamp, entity_id, traffic_speed, predicted_speed, persistence_prediction, absolute_error, persistence_absolute_error

Includes persistence fallback for runtime resilience.
"""

from __future__ import annotations

import json
import logging
import pickle
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import xgboost as xgb

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))

# Production model paths
MODEL_DIR = Path("ml/traffic/models/production")
MODEL_JSON = MODEL_DIR / "traffic_xgboost_model.json"
MODEL_PKL = MODEL_DIR / "traffic_xgboost_model.pkl"
FEATURE_CONFIG = MODEL_DIR / "traffic_xgboost_feature_config.json"

# Database path
DB_PATH = Path("data/traffic_observations_train.db")

# Output path for Traffic Agent
OUTPUT_PATH = Path("traffic/data/processed/real_day_predictions.csv")

# Feature columns (from feature_config_real.json)
FEATURE_COLUMNS = [
    "speed_lag_1", "speed_lag_2", "speed_lag_3", "speed_lag_4", "speed_lag_5", "speed_lag_6",
    "rolling_mean_3", "rolling_std_3", "rolling_min_3", "rolling_max_3",
    "rolling_mean_6", "rolling_std_6",
    "speed_trend_15", "speed_change_5",
    "segment_mean_speed", "segment_std_speed", "segment_min_speed", "segment_max_speed", "segment_count",
    "road_mean_speed", "road_std_speed",
    "zone_mean_speed", "zone_std_speed",
    "hour", "minute_bucket", "day_of_week", "is_weekend", "is_peak",
    "hour_sin", "hour_cos", "minute_sin", "minute_cos", "dow_sin", "dow_cos",
]

CAT_FEATURES = ["road_category"]

TARGET_HORIZON_MINUTES = 5
EXPECTED_INTERVAL_MINUTES = 5
N_LINKS = 143787


class TrafficXGBoostPredictor:
    """XGBoost predictor for traffic speed with persistence fallback."""
    
    def __init__(self):
        self.model: Optional[xgb.XGBRegressor] = None
        self.feature_columns: List[str] = []
        self.cat_features: List[str] = []
        self._load_model()
    
    def _load_model(self) -> None:
        """Load the XGBoost model from production artifacts."""
        logger.info("Loading XGBoost model from %s", MODEL_PKL)
        
        # Load model from pickle (contains the full XGBRegressor object)
        try:
            with open(MODEL_PKL, 'rb') as f:
                artifact = pickle.load(f)
            
            if isinstance(artifact, dict) and 'model' in artifact:
                self.model = artifact['model']
            else:
                self.model = artifact
            
            # Load feature config
            with open(FEATURE_CONFIG, 'r') as f:
                config = json.load(f)
            self.feature_columns = config.get('feature_columns', [])
            self.cat_features = config.get('categorical_features', [])
            
            logger.info("Loaded XGBoost model with %d features", len(self.feature_columns))
            
        except Exception as e:
            logger.error("Failed to load XGBoost model: %s", e)
            raise
    
    def _load_latest_snapshot(self) -> pd.DataFrame:
        """Load the latest complete snapshot from the training database."""
        logger.info("Loading latest complete snapshot from %s", DB_PATH)
        
        with sqlite3.connect(DB_PATH) as conn:
            latest_complete = conn.execute("""
                SELECT observed_at FROM (
                    SELECT observed_at, COUNT(*) as cnt
                    FROM traffic_observations
                    GROUP BY observed_at
                    HAVING cnt = ?
                )
                ORDER BY observed_at DESC
                LIMIT 1
            """, (N_LINKS,)).fetchone()
            
            if not latest_complete:
                raise ValueError("No complete snapshots found in database")
            
            latest_ts = latest_complete[0]
            logger.info("Latest complete snapshot: %s", latest_ts)
            
            df = pd.read_sql_query("""
                SELECT observed_at, link_id, road_name, road_category, speed_band,
                       minimum_speed, maximum_speed, speed_midpoint,
                       start_latitude, start_longitude, end_latitude, end_longitude,
                       zone_id, zone_name
                FROM traffic_observations
                WHERE observed_at = ?
                  AND speed_midpoint >= 0
                  AND speed_midpoint <= 120
                ORDER BY link_id
            """, conn, params=[latest_ts])
            
            logger.info("Loaded %d observations for %s", len(df), latest_ts)
            
            # Convert observed_at to datetime with timezone
            df['observed_at'] = pd.to_datetime(df['observed_at']).dt.tz_convert(SG_OFFSET)
            return df
    
    def _create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create features matching the training pipeline."""
        logger.info("Creating features for inference...")
        
        df = df.copy()
        df['observed_at'] = pd.to_datetime(df['observed_at']).dt.tz_convert(SG_OFFSET)
        df = df.sort_values(['link_id', 'observed_at']).reset_index(drop=True)
        
        # Create lag features
        df['prev_timestamp'] = df.groupby('link_id')['observed_at'].shift(1)
        df['time_diff_minutes'] = (df['observed_at'] - df['prev_timestamp']).dt.total_seconds() / 60
        
        tolerance = 1.0
        valid_interval = (df['time_diff_minutes'] >= EXPECTED_INTERVAL_MINUTES - tolerance) & \
                         (df['time_diff_minutes'] <= EXPECTED_INTERVAL_MINUTES + tolerance)
        
        df['speed_lag_1'] = np.where(valid_interval, df.groupby('link_id')['speed_midpoint'].shift(1), np.nan)
        
        df['prev2_timestamp'] = df.groupby('link_id')['observed_at'].shift(2)
        df['time_diff_2'] = (df['prev_timestamp'] - df['prev2_timestamp']).dt.total_seconds() / 60
        valid_interval_2 = (df['time_diff_2'] >= EXPECTED_INTERVAL_MINUTES - tolerance) & \
                           (df['time_diff_2'] <= EXPECTED_INTERVAL_MINUTES + tolerance)
        df['speed_lag_2'] = np.where(valid_interval & valid_interval_2, 
                                      df.groupby('link_id')['speed_midpoint'].shift(2), np.nan)
        
        df['prev3_timestamp'] = df.groupby('link_id')['observed_at'].shift(3)
        df['time_diff_3'] = (df['prev2_timestamp'] - df['prev3_timestamp']).dt.total_seconds() / 60
        valid_interval_3 = (df['time_diff_3'] >= EXPECTED_INTERVAL_MINUTES - tolerance) & \
                           (df['time_diff_3'] <= EXPECTED_INTERVAL_MINUTES + tolerance)
        df['speed_lag_3'] = np.where(valid_interval & valid_interval_2 & valid_interval_3, 
                                      df.groupby('link_id')['speed_midpoint'].shift(3), np.nan)
        
        df['prev4_timestamp'] = df.groupby('link_id')['observed_at'].shift(4)
        df['time_diff_4'] = (df['prev3_timestamp'] - df['prev4_timestamp']).dt.total_seconds() / 60
        valid_interval_4 = (df['time_diff_4'] >= EXPECTED_INTERVAL_MINUTES - tolerance) & \
                           (df['time_diff_4'] <= EXPECTED_INTERVAL_MINUTES + tolerance)
        df['speed_lag_4'] = np.where(valid_interval & valid_interval_2 & valid_interval_3 & valid_interval_4, 
                                      df.groupby('link_id')['speed_midpoint'].shift(4), np.nan)
        
        df['prev5_timestamp'] = df.groupby('link_id')['observed_at'].shift(5)
        df['time_diff_5'] = (df['prev4_timestamp'] - df['prev5_timestamp']).dt.total_seconds() / 60
        valid_interval_5 = (df['time_diff_5'] >= EXPECTED_INTERVAL_MINUTES - tolerance) & \
                           (df['time_diff_5'] <= EXPECTED_INTERVAL_MINUTES + tolerance)
        df['speed_lag_5'] = np.where(valid_interval & valid_interval_2 & valid_interval_3 & valid_interval_4 & valid_interval_5, 
                                      df.groupby('link_id')['speed_midpoint'].shift(5), np.nan)
        
        df['prev6_timestamp'] = df.groupby('link_id')['observed_at'].shift(6)
        df['time_diff_6'] = (df['prev5_timestamp'] - df['prev6_timestamp']).dt.total_seconds() / 60
        valid_interval_6 = (df['time_diff_6'] >= EXPECTED_INTERVAL_MINUTES - tolerance) & \
                           (df['time_diff_6'] <= EXPECTED_INTERVAL_MINUTES + tolerance)
        df['speed_lag_6'] = np.where(valid_interval & valid_interval_2 & valid_interval_3 & valid_interval_4 & valid_interval_5 & valid_interval_6, 
                                      df.groupby('link_id')['speed_midpoint'].shift(6), np.nan)
        
        lag_cols = ['speed_lag_1', 'speed_lag_2', 'speed_lag_3', 'speed_lag_4', 'speed_lag_5', 'speed_lag_6']
        
        df['rolling_mean_3'] = df[lag_cols[:3]].mean(axis=1, skipna=True)
        df['rolling_std_3'] = df[lag_cols[:3]].std(axis=1, skipna=True)
        df['rolling_min_3'] = df[lag_cols[:3]].min(axis=1, skipna=True)
        df['rolling_max_3'] = df[lag_cols[:3]].max(axis=1, skipna=True)
        
        df['rolling_mean_6'] = df[lag_cols].mean(axis=1, skipna=True)
        df['rolling_std_6'] = df[lag_cols].std(axis=1, skipna=True)
        
        df['speed_trend_15'] = df['speed_lag_1'] - df['speed_lag_3']
        df['speed_change_5'] = df['speed_lag_1'] - df['speed_lag_2']
        
        # Clean up temp columns
        temp_cols = ['prev_timestamp', 'time_diff_minutes', 'prev2_timestamp', 'time_diff_2',
                     'prev3_timestamp', 'time_diff_3', 'prev4_timestamp', 'time_diff_4',
                     'prev5_timestamp', 'time_diff_5', 'prev6_timestamp', 'time_diff_6']
        df = df.drop(columns=temp_cols, errors='ignore')
        
        # Segment statistics (computed from current snapshot)
        segment_stats = df.groupby('link_id')['speed_midpoint'].agg([
            ('segment_mean_speed', 'mean'),
            ('segment_std_speed', 'std'),
            ('segment_min_speed', 'min'),
            ('segment_max_speed', 'max'),
            ('segment_count', 'count'),
        ]).reset_index()
        segment_stats['segment_std_speed'] = segment_stats['segment_std_speed'].fillna(0)
        df = df.merge(segment_stats, on='link_id', how='left')
        
        # Road category statistics
        road_stats = df.groupby('road_category')['speed_midpoint'].agg([
            ('road_mean_speed', 'mean'),
            ('road_std_speed', 'std'),
        ]).reset_index()
        road_stats['road_std_speed'] = road_stats['road_std_speed'].fillna(0)
        df = df.merge(road_stats, on='road_category', how='left')
        
        # Zone statistics
        zone_stats = df[df['zone_id'].notna()].groupby('zone_id')['speed_midpoint'].agg([
            ('zone_mean_speed', 'mean'),
            ('zone_std_speed', 'std'),
        ]).reset_index()
        zone_stats['zone_std_speed'] = zone_stats['zone_std_speed'].fillna(0)
        df = df.merge(zone_stats, on='zone_id', how='left')
        
        # Calendar features
        df['observed_at'] = pd.to_datetime(df['observed_at'])
        df['hour'] = df['observed_at'].dt.hour
        df['minute'] = df['observed_at'].dt.minute
        df['minute_bucket'] = (df['minute'] // 5) * 5
        df['day_of_week'] = df['observed_at'].dt.dayofweek
        df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
        df['is_peak'] = ((df['hour'] >= 7) & (df['hour'] <= 9) | 
                         (df['hour'] >= 17) & (df['hour'] <= 19)).astype(int)
        
        df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
        df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)
        df['minute_sin'] = np.sin(2 * np.pi * df['minute'] / 60)
        df['minute_cos'] = np.cos(2 * np.pi * df['minute'] / 60)
        df['dow_sin'] = np.sin(2 * np.pi * df['day_of_week'] / 7)
        df['dow_cos'] = np.cos(2 * np.pi * df['day_of_week'] / 7)
        
        return df
    
    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate predictions for all links in the dataframe."""
        logger.info("Generating XGBoost predictions for %d links", len(df))
        
        # Create features
        df_features = self._create_features(df)
        
        # Check for missing features
        missing_features = set(self.feature_columns) - set(df_features.columns)
        if missing_features:
            logger.warning("Missing features: %s", missing_features)
            # Fill missing with 0
            for f in missing_features:
                df_features[f] = 0.0
        
        # Prepare feature matrix
        X = df_features[self.feature_columns].copy()
        
        # Handle categorical features
        for cat in self.cat_features:
            if cat in X.columns:
                X[cat] = X[cat].astype('category')
        
        # Fill NaN with 0 for inference (model should handle missing)
        X = X.fillna(0.0)
        
        # Make predictions
        logger.info("Running XGBoost inference on %d samples", len(X))
        predicted_change = self.model.predict(X[self.feature_columns])
        
        # Clip predicted change to training distribution range
        # Training data (with speed_midpoint <= 120) had speed_change range [-60, 60]
        # Clip to prevent extrapolation beyond training distribution
        predicted_change = np.clip(predicted_change, -60.0, 60.0)
        
        # Convert speed change to absolute predicted speed
        # Model predicts speed change at t+5min: predicted_speed = current_speed + predicted_change
        predicted_speed = df['speed_midpoint'] + predicted_change
        
        # Clip final predicted speed to training data maximum (120 km/h)
        # Training data was filtered to speed_midpoint <= 120, so model was never trained on higher speeds
        predicted_speed = np.clip(predicted_speed, 0.0, 120.0)
        
        # Prepare output in Traffic Agent format
        timestamp_str = df['observed_at'].dt.strftime('%Y-%m-%d %H:%M:%S%z').str[:-2] + ':' + df['observed_at'].dt.strftime('%z').str[-2:]
        
        # Map link_id to entity_id (sequential integer for compatibility)
        link_to_entity = {link: idx for idx, link in enumerate(sorted(df['link_id'].unique()))}
        
        predictions_df = pd.DataFrame({
            'timestamp': timestamp_str,
            'entity_id': df['link_id'].map(link_to_entity),
            'traffic_speed': df['speed_midpoint'].round(2),
            'predicted_speed': np.round(predicted_speed, 2),
            'persistence_prediction': df['speed_midpoint'].round(2),  # persistence baseline
            'absolute_error': np.round(np.abs(df['speed_midpoint'] - predicted_speed), 4),
            'persistence_absolute_error': 0.0,  # persistence error is 0 at t0
        })
        
        logger.info("Generated %d predictions", len(predictions_df))
        return predictions_df
    
    def predict_with_fallback(self) -> pd.DataFrame:
        """Generate predictions with persistence fallback on failure."""
        try:
            # Load latest snapshot
            df = self._load_latest_snapshot()
            
            # Generate XGBoost predictions
            return self.predict(df)
            
        except Exception as e:
            logger.error("XGBoost prediction failed: %s; falling back to persistence", e)
            # Fallback to persistence
            return self._generate_persistence_predictions()
    
    def _generate_persistence_predictions(self) -> pd.DataFrame:
        """Generate persistence baseline predictions."""
        logger.info("Generating persistence fallback predictions...")
        
        df = self._load_latest_snapshot()
        timestamp_str = df['observed_at'].dt.strftime('%Y-%m-%d %H:%M:%S%z').str[:-2] + ':' + df['observed_at'].dt.strftime('%z').str[-2:]
        
        link_to_entity = {link: idx for idx, link in enumerate(sorted(df['link_id'].unique()))}
        
        predictions_df = pd.DataFrame({
            'timestamp': timestamp_str,
            'entity_id': df['link_id'].map(link_to_entity),
            'traffic_speed': df['speed_midpoint'].round(2),
            'predicted_speed': df['speed_midpoint'].round(2),  # persistence = current speed
            'persistence_prediction': df['speed_midpoint'].round(2),
            'absolute_error': 0.0,
            'persistence_absolute_error': 0.0,
        })
        
        logger.info("Generated %d persistence predictions", len(predictions_df))
        return predictions_df


def main():
    """Main entry point for Traffic XGBoost inference."""
    logger.info("=" * 60)
    logger.info("TRAFFIC XGBOOST INFERENCE")
    logger.info("=" * 60)
    
    predictor = TrafficXGBoostPredictor()
    
    # Generate predictions with fallback
    predictions = predictor.predict_with_fallback()
    
    # Save to output path
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(OUTPUT_PATH, index=False)
    logger.info("Saved predictions to %s", OUTPUT_PATH)
    
    # Log summary
    logger.info("Summary:")
    logger.info("  Timestamp range: %s to %s", predictions['timestamp'].min(), predictions['timestamp'].max())
    logger.info("  Unique entities: %d", predictions['entity_id'].nunique())
    logger.info("  Traffic speed range: %.2f to %.2f", predictions['traffic_speed'].min(), predictions['traffic_speed'].max())
    logger.info("  Predicted speed range: %.2f to %.2f", predictions['predicted_speed'].min(), predictions['predicted_speed'].max())
    
    return predictions


if __name__ == '__main__':
    main()