"""Traffic XGBoost real-time predictor.

Loads the production XGBoost model and feature config, builds the same
feature vector used during training from live/recent LTA observations,
and returns per-link next-5-minute speed predictions.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb

from backend.app.mobility.traffic.data import TrafficObservationStore

log = logging.getLogger(__name__)

SG_OFFSET = "Asia/Singapore"
MODEL_PATH = Path("ml/traffic/models/production/traffic_xgboost_model.json")
CONFIG_PATH = Path("ml/traffic/models/production/traffic_xgboost_feature_config.json")


@dataclass
class LinkPrediction:
    link_id: str
    road_name: str
    road_category: str
    zone_id: Optional[str]
    zone_name: Optional[str]
    current_speed: float
    predicted_speed: float
    speed_change: float
    prediction_timestamp: str   # when prediction was made (t0)
    target_timestamp: str       # t0 + 5 min


class TrafficPredictor:
    def __init__(
        self,
        model_path: Path = MODEL_PATH,
        config_path: Path = CONFIG_PATH,
    ) -> None:
        self.model_path = model_path
        self.config_path = config_path
        self._model: Optional[xgb.XGBRegressor] = None
        self._feature_cols: List[str] = []
        self._cat_features: List[str] = []

    def _load_artifacts(self) -> None:
        if hasattr(self, "_booster") and self._booster is not None:
            return
        # Load feature config
        with open(self.config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self._feature_cols = cfg["feature_columns"]
        self._cat_features = cfg.get("categorical_features", [])
        # Load XGBoost model as raw Booster (artifact saved via xgb.train)
        self._booster = xgb.Booster()
        self._booster.load_model(str(self.model_path))
        log.info("Loaded Traffic XGBoost model (Booster) and feature config")

    # ------------------------------------------------------------------ public
    def predict_latest(self, store: TrafficObservationStore) -> Tuple[pd.DataFrame, List[LinkPrediction], Dict]:
        """Build features for the latest complete snapshot and predict.

        Returns:
            features_df: DataFrame with feature columns for each link (one row per link)
            predictions: list of LinkPrediction
            diagnostics: dict with metadata
        """
        self._load_artifacts()

        # 1. Get latest snapshot timestamp
        latest_snapshot = store.get_latest_snapshot(limit=1000000)  # No artificial cap; fetch all links in latest snapshot
        if not latest_snapshot:
            raise ValueError("No traffic observations available")
        latest_ts = latest_snapshot[0].observed_at
        log.info("Latest observation timestamp: %s, snapshot size: %d", latest_ts, len(latest_snapshot))

        # 2. Fetch last 7 observations per link in a single query using window function
        link_ids = [obs.link_id for obs in latest_snapshot]
        placeholders = ','.join('?' for _ in link_ids)
        query = f"""
            WITH ranked AS (
                SELECT observed_at, link_id, road_name, road_category, speed_band,
                       minimum_speed, maximum_speed, speed_midpoint,
                       start_latitude, start_longitude, end_latitude, end_longitude,
                       zone_id, zone_name,
                       ROW_NUMBER() OVER (PARTITION BY link_id ORDER BY observed_at DESC) as rn
                FROM traffic_observations
                WHERE link_id IN ({placeholders}) AND observed_at <= ?
            )
            SELECT observed_at, link_id, road_name, road_category, speed_band,
                   minimum_speed, maximum_speed, speed_midpoint,
                   start_latitude, start_longitude, end_latitude, end_longitude,
                   zone_id, zone_name
            FROM ranked WHERE rn <= 7
            ORDER BY link_id, observed_at DESC
        """
        params = link_ids + [latest_ts]
        with store._conn() as conn:
            all_rows = conn.execute(query, params).fetchall()

        # Convert to DataFrame
        df = pd.DataFrame([dict(r) for r in all_rows])
        if df.empty:
            raise ValueError("No recent history for links")
        df["observed_at"] = pd.to_datetime(df["observed_at"]).dt.tz_convert(SG_OFFSET)
        df = df.sort_values(["link_id", "observed_at"]).reset_index(drop=True)

        # Keep only last 7 per link (already limited by query, but double-check)
        df = df.groupby("link_id").head(7).copy()

        # 3. Feature engineering matching training (speed_lag_1..6, rolling, calendar, segment/road/zone stats)
        # We'll compute per-link features using the same logic as train.py
        # Ensure required columns exist
        df["speed_midpoint"] = pd.to_numeric(df["speed_midpoint"], errors="coerce")
        # Clip unrealistic speeds (km/h)
        df["speed_midpoint"] = df["speed_midpoint"].clip(0, 120)
        df["road_category"] = pd.to_numeric(df["road_category"], errors="coerce")

        # Create lag features (need at least 6 previous rows) - match feature config names
        df = df.sort_values(["link_id", "observed_at"]).reset_index(drop=True)
        df["speed_lag_1"] = df.groupby("link_id")["speed_midpoint"].shift(1)
        df["speed_lag_2"] = df.groupby("link_id")["speed_midpoint"].shift(2)
        df["speed_lag_3"] = df.groupby("link_id")["speed_midpoint"].shift(3)
        df["speed_lag_4"] = df.groupby("link_id")["speed_midpoint"].shift(4)
        df["speed_lag_5"] = df.groupby("link_id")["speed_midpoint"].shift(5)
        df["speed_lag_6"] = df.groupby("link_id")["speed_midpoint"].shift(6)

        # Rolling stats on available lags
        lag_cols = ["speed_lag_1", "speed_lag_2", "speed_lag_3", "speed_lag_4", "speed_lag_5", "speed_lag_6"]
        df["rolling_mean_3"] = df[lag_cols[:3]].mean(axis=1, skipna=True)
        df["rolling_std_3"] = df[lag_cols[:3]].std(axis=1, skipna=True)
        df["rolling_min_3"] = df[lag_cols[:3]].min(axis=1, skipna=True)
        df["rolling_max_3"] = df[lag_cols[:3]].max(axis=1, skipna=True)
        df["rolling_mean_6"] = df[lag_cols].mean(axis=1, skipna=True)
        df["rolling_std_6"] = df[lag_cols].std(axis=1, skipna=True)

        df["speed_trend_15"] = df["speed_lag_1"] - df["speed_lag_3"]
        df["speed_change_5"] = df["speed_lag_1"] - df["speed_lag_2"]

        # Calendar features (use latest timestamp per link = current row)
        df["hour"] = df["observed_at"].dt.hour
        df["minute"] = df["observed_at"].dt.minute
        df["minute_bucket"] = (df["minute"] // 5) * 5
        df["day_of_week"] = df["observed_at"].dt.dayofweek
        df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
        df["is_peak"] = ((df["hour"] >= 7) & (df["hour"] <= 9) | (df["hour"] >= 17) & (df["hour"] <= 19)).astype(int)
        df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
        df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
        df["minute_sin"] = np.sin(2 * np.pi * df["minute"] / 60)
        df["minute_cos"] = np.cos(2 * np.pi * df["minute"] / 60)
        df["dow_sin"] = np.sin(2 * np.pi * df["day_of_week"] / 7)
        df["dow_cos"] = np.cos(2 * np.pi * df["day_of_week"] / 7)

        # Segment/road/zone stats: compute from the recent history (use all rows per link in df)
        # For simplicity compute on the fly from the same recent window (last up to 7 obs)
        seg_stats = df.groupby("link_id")["speed_midpoint"].agg(
            segment_mean_speed="mean",
            segment_std_speed="std",
            segment_min_speed="min",
            segment_max_speed="max",
            segment_count="count",
        ).reset_index()
        seg_stats["segment_std_speed"] = seg_stats["segment_std_speed"].fillna(0)
        df = df.merge(seg_stats, on="link_id", how="left", suffixes=("", "_seg"))

        road_stats = df.groupby("road_category")["speed_midpoint"].agg(
            road_mean_speed="mean",
            road_std_speed="std",
        ).reset_index()
        road_stats["road_std_speed"] = road_stats["road_std_speed"].fillna(0)
        df = df.merge(road_stats, on="road_category", how="left", suffixes=("", "_road"))

        zone_stats = df[df["zone_id"].notna()].groupby("zone_id")["speed_midpoint"].agg(
            zone_mean_speed="mean",
            zone_std_speed="std",
        ).reset_index()
        zone_stats["zone_std_speed"] = zone_stats["zone_std_speed"].fillna(0)
        df = df.merge(zone_stats, on="zone_id", how="left", suffixes=("", "_zone"))

        # Keep only the latest row per link (the one at latest_ts)
        latest_rows = df[df["observed_at"] == pd.Timestamp(latest_ts).tz_convert(SG_OFFSET)].copy()
        # Clip speed_midpoint to realistic range (km/h)
        if "speed_midpoint" in latest_rows.columns:
            latest_rows.loc[:, "speed_midpoint"] = latest_rows["speed_midpoint"].clip(0, 120)
        # Also clip lag columns used for features if they exist
        for lag in ["speed_lag_1","speed_lag_2","speed_lag_3","speed_lag_4","speed_lag_5","speed_lag_6"]:
            if lag in latest_rows.columns:
                latest_rows.loc[:, lag] = latest_rows[lag].clip(0, 120)
        if latest_rows.empty:
            # fallback: take the most recent per link
            latest_rows = df.sort_values("observed_at").groupby("link_id").tail(1)

        # Prepare feature matrix in correct order
        missing_cols = [c for c in self._feature_cols if c not in latest_rows.columns]
        if missing_cols:
            log.warning("Missing feature columns, filling with 0: %s", missing_cols)
            for c in missing_cols:
                latest_rows.loc[:, c] = 0.0

        X = latest_rows[self._feature_cols].fillna(0.0)

        # 4. Predict
        dmatrix = xgb.DMatrix(X)
        preds = self._booster.predict(dmatrix)
        # preds are predicted speed_midpoint at t+5min (target_speed)
        # current speed is speed_midpoint at latest_ts (latest_rows["speed_midpoint"])
        current_speeds = latest_rows["speed_midpoint"].clip(0, 120).values

        predictions = []
        for i, (idx, row) in enumerate(latest_rows.iterrows()):
            pred_speed = float(preds[i])
            # Clip predictions to realistic range
            pred_speed = max(0.0, min(pred_speed, 120.0))
            cur_speed = float(row["speed_midpoint"])
            # Clip current speed as safety
            cur_speed = max(0.0, min(cur_speed, 120.0))
            # Guard: limit unrealistic drop in 5 minutes (max 30% drop)
            max_drop = 0.30 * cur_speed
            if cur_speed - pred_speed > max_drop:
                pred_speed = cur_speed - max_drop
            predictions.append(LinkPrediction(
                link_id=row["link_id"],
                road_name=row["road_name"],
                road_category=str(row["road_category"]),
                zone_id=row.get("zone_id"),
                zone_name=row.get("zone_name"),
                current_speed=cur_speed,
                predicted_speed=pred_speed,
                speed_change=pred_speed - cur_speed,
                prediction_timestamp=latest_ts,
                target_timestamp=(pd.Timestamp(latest_ts) + pd.Timedelta(minutes=5)).isoformat(),
            ))

        diagnostics = {
            "links_predicted": len(predictions),
            "latest_observation_timestamp": latest_ts,
            "model": "xgboost",
            "feature_count": len(self._feature_cols),
        }

        # Return feature df for possible further use
        return latest_rows, predictions, diagnostics