"""UrbanOS Traffic ML — Full Real Dataset Training Pipeline (v3).

Attempts residual learning (speed change prediction) to beat persistence.
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SEED = 42
np.random.seed(SEED)

SG_OFFSET = timezone(timedelta(hours=8))

DB_PATH = Path("data/traffic_observations_train.db")
MODEL_DIR = Path("traffic/models")
PROCESSED_DIR = Path("traffic/data/processed")

os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)


@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def audit_database() -> Dict[str, Any]:
    logger.info("Auditing collector database...")
    
    with get_db_connection() as conn:
        total_obs = conn.execute("SELECT COUNT(*) FROM traffic_observations").fetchone()[0]
        unique_links = conn.execute("SELECT COUNT(DISTINCT link_id) FROM traffic_observations").fetchone()[0]
        unique_zones = conn.execute("SELECT COUNT(DISTINCT zone_id) FROM traffic_observations WHERE zone_id IS NOT NULL").fetchone()[0]
        earliest = conn.execute("SELECT MIN(observed_at) FROM traffic_observations").fetchone()[0]
        latest = conn.execute("SELECT MAX(observed_at) FROM traffic_observations").fetchone()[0]
        
        snapshots = conn.execute("""
            SELECT observed_at, COUNT(*) as cnt
            FROM traffic_observations
            GROUP BY observed_at
            ORDER BY observed_at
        """).fetchall()
        
        snapshot_counts = [r[1] for r in snapshots]
        expected_per_snapshot = unique_links
        complete_snapshots = sum(1 for c in snapshot_counts if c == expected_per_snapshot)
        incomplete_snapshots = len(snapshots) - complete_snapshots
        
        intervals = []
        for i in range(1, len(snapshots)):
            try:
                t1 = datetime.fromisoformat(snapshots[i-1][0].replace('Z', '+00:00'))
                t2 = datetime.fromisoformat(snapshots[i][0].replace('Z', '+00:00'))
                delta = (t2 - t1).total_seconds() / 60
                intervals.append(delta)
            except Exception:
                pass
        
        null_counts = {}
        for col in ['minimum_speed', 'maximum_speed', 'start_latitude', 'end_latitude', 'zone_id', 'zone_name']:
            cnt = conn.execute(f"SELECT COUNT(*) FROM traffic_observations WHERE {col} IS NULL").fetchone()[0]
            null_counts[col] = cnt
        
        dup_count = conn.execute("""
            SELECT COUNT(*) FROM (
                SELECT observed_at, link_id, COUNT(*) as c
                FROM traffic_observations
                GROUP BY observed_at, link_id
                HAVING c > 1
            )
        """).fetchone()[0]
        
        zone_rows = conn.execute("""
            SELECT zone_id, zone_name, COUNT(DISTINCT link_id) as links, COUNT(*) as obs
            FROM traffic_observations
            WHERE zone_id IS NOT NULL
            GROUP BY zone_id, zone_name
            ORDER BY zone_id
        """).fetchall()
        
        road_rows = conn.execute("""
            SELECT road_category, COUNT(*) as cnt
            FROM traffic_observations
            GROUP BY road_category
            ORDER BY cnt DESC
        """).fetchall()
        
        stats = {
            "total_observations": total_obs,
            "unique_link_ids": unique_links,
            "unique_zones": unique_zones,
            "earliest_observation": earliest,
            "latest_observation": latest,
            "total_snapshots": len(snapshots),
            "complete_snapshots": complete_snapshots,
            "incomplete_snapshots": incomplete_snapshots,
            "expected_per_snapshot": expected_per_snapshot,
            "snapshot_sizes": sorted(set(snapshot_counts)),
            "cadence_intervals_minutes": intervals,
            "mean_cadence_minutes": np.mean(intervals) if intervals else None,
            "null_counts": null_counts,
            "duplicate_pairs": dup_count,
            "zone_coverage": [dict(r) for r in zone_rows],
            "road_categories": [dict(r) for r in road_rows],
        }
        
        logger.info(f"Total observations: {total_obs:,}")
        logger.info(f"Unique LinkIDs: {unique_links:,}")
        logger.info(f"Complete snapshots: {complete_snapshots}/{len(snapshots)}")
        logger.info(f"Incomplete snapshots: {incomplete_snapshots}")
        logger.info(f"Time range: {earliest} to {latest}")
        logger.info(f"Mean cadence: {stats['mean_cadence_minutes']:.2f} minutes")
        logger.info(f"Duplicate (observed_at, link_id) pairs: {dup_count}")
        
        return stats


def load_complete_snapshots() -> pd.DataFrame:
    logger.info("Loading complete snapshots from database...")
    
    with get_db_connection() as conn:
        complete_timestamps = conn.execute("""
            SELECT observed_at FROM (
                SELECT observed_at, COUNT(*) as cnt
                FROM traffic_observations
                GROUP BY observed_at
                HAVING cnt = 143787
            )
            ORDER BY observed_at
        """).fetchall()
        
        timestamps = [r[0] for r in complete_timestamps]
        logger.info(f"Found {len(timestamps)} complete snapshots")
        
        if not timestamps:
            raise ValueError("No complete snapshots found")
        
        placeholders = ','.join(['?' for _ in timestamps])
        query = f"""
            SELECT observed_at, link_id, road_name, road_category, speed_band,
                   minimum_speed, maximum_speed, speed_midpoint,
                   start_latitude, start_longitude, end_latitude, end_longitude,
                   zone_id, zone_name
            FROM traffic_observations
            WHERE observed_at IN ({placeholders})
              AND road_category IN (2,3,4,5,6)
              AND speed_midpoint >= 0
              AND speed_midpoint <= 120
            ORDER BY observed_at, link_id
        """
        
        df = pd.read_sql_query(query, conn, params=timestamps)
        logger.info(f"Loaded {len(df):,} observations for {df['observed_at'].nunique()} snapshots (filtered)")
        
        df['observed_at'] = pd.to_datetime(df['observed_at']).dt.tz_convert(SG_OFFSET)
        df = df.sort_values(['link_id', 'observed_at']).reset_index(drop=True)
        
        return df


def create_lag_features(df: pd.DataFrame, expected_interval_minutes: int = 5) -> pd.DataFrame:
    logger.info("Creating temporal lag features...")
    
    df = df.copy()
    df['observed_at'] = pd.to_datetime(df['observed_at'])
    
    df['prev_timestamp'] = df.groupby('link_id')['observed_at'].shift(1)
    df['time_diff_minutes'] = (df['observed_at'] - df['prev_timestamp']).dt.total_seconds() / 60
    
    tolerance = 1.0
    valid_interval = (df['time_diff_minutes'] >= expected_interval_minutes - tolerance) & \
                     (df['time_diff_minutes'] <= expected_interval_minutes + tolerance)
    
    df['speed_lag_1'] = np.where(valid_interval, df.groupby('link_id')['speed_midpoint'].shift(1), np.nan)
    
    df['prev2_timestamp'] = df.groupby('link_id')['observed_at'].shift(2)
    df['time_diff_2'] = (df['prev_timestamp'] - df['prev2_timestamp']).dt.total_seconds() / 60
    valid_interval_2 = (df['time_diff_2'] >= expected_interval_minutes - tolerance) & \
                       (df['time_diff_2'] <= expected_interval_minutes + tolerance)
    df['speed_lag_2'] = np.where(valid_interval & valid_interval_2, 
                                  df.groupby('link_id')['speed_midpoint'].shift(2), np.nan)
    
    df['prev3_timestamp'] = df.groupby('link_id')['observed_at'].shift(3)
    df['time_diff_3'] = (df['prev2_timestamp'] - df['prev3_timestamp']).dt.total_seconds() / 60
    valid_interval_3 = (df['time_diff_3'] >= expected_interval_minutes - tolerance) & \
                       (df['time_diff_3'] <= expected_interval_minutes + tolerance)
    df['speed_lag_3'] = np.where(valid_interval & valid_interval_2 & valid_interval_3, 
                                  df.groupby('link_id')['speed_midpoint'].shift(3), np.nan)
    
    df['prev4_timestamp'] = df.groupby('link_id')['observed_at'].shift(4)
    df['time_diff_4'] = (df['prev3_timestamp'] - df['prev4_timestamp']).dt.total_seconds() / 60
    valid_interval_4 = (df['time_diff_4'] >= expected_interval_minutes - tolerance) & \
                       (df['time_diff_4'] <= expected_interval_minutes + tolerance)
    df['speed_lag_4'] = np.where(valid_interval & valid_interval_2 & valid_interval_3 & valid_interval_4, 
                                  df.groupby('link_id')['speed_midpoint'].shift(4), np.nan)
    
    df['prev5_timestamp'] = df.groupby('link_id')['observed_at'].shift(5)
    df['time_diff_5'] = (df['prev4_timestamp'] - df['prev5_timestamp']).dt.total_seconds() / 60
    valid_interval_5 = (df['time_diff_5'] >= expected_interval_minutes - tolerance) & \
                       (df['time_diff_5'] <= expected_interval_minutes + tolerance)
    df['speed_lag_5'] = np.where(valid_interval & valid_interval_2 & valid_interval_3 & valid_interval_4 & valid_interval_5, 
                                  df.groupby('link_id')['speed_midpoint'].shift(5), np.nan)
    
    df['prev6_timestamp'] = df.groupby('link_id')['observed_at'].shift(6)
    df['time_diff_6'] = (df['prev5_timestamp'] - df['prev6_timestamp']).dt.total_seconds() / 60
    valid_interval_6 = (df['time_diff_6'] >= expected_interval_minutes - tolerance) & \
                       (df['time_diff_6'] <= expected_interval_minutes + tolerance)
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
    
    temp_cols = ['prev_timestamp', 'time_diff_minutes', 'prev2_timestamp', 'time_diff_2',
                 'prev3_timestamp', 'time_diff_3', 'prev4_timestamp', 'time_diff_4',
                 'prev5_timestamp', 'time_diff_5', 'prev6_timestamp', 'time_diff_6']
    df = df.drop(columns=temp_cols, errors='ignore')
    
    valid_lag_rows = df['speed_lag_1'].notna().sum()
    logger.info(f"Valid lag-1 rows: {valid_lag_rows:,} ({valid_lag_rows/len(df)*100:.1f}%)")
    
    return df


def create_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    logger.info("Creating calendar features...")
    
    df = df.copy()
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


def create_segment_features(df: pd.DataFrame, train_mask: pd.Series) -> pd.DataFrame:
    logger.info("Creating segment statistical features...")
    
    df = df.copy()
    
    train_df = df[train_mask]
    segment_stats = train_df.groupby('link_id')['speed_midpoint'].agg([
        ('segment_mean_speed', 'mean'),
        ('segment_std_speed', 'std'),
        ('segment_min_speed', 'min'),
        ('segment_max_speed', 'max'),
        ('segment_count', 'count'),
    ]).reset_index()
    
    segment_stats['segment_std_speed'] = segment_stats['segment_std_speed'].fillna(0)
    df = df.merge(segment_stats, on='link_id', how='left')
    
    road_stats = train_df.groupby('road_category')['speed_midpoint'].agg([
        ('road_mean_speed', 'mean'),
        ('road_std_speed', 'std'),
    ]).reset_index()
    road_stats['road_std_speed'] = road_stats['road_std_speed'].fillna(0)
    df = df.merge(road_stats, on='road_category', how='left')
    
    zone_stats = train_df[train_df['zone_id'].notna()].groupby('zone_id')['speed_midpoint'].agg([
        ('zone_mean_speed', 'mean'),
        ('zone_std_speed', 'std'),
    ]).reset_index()
    zone_stats['zone_std_speed'] = zone_stats['zone_std_speed'].fillna(0)
    df = df.merge(zone_stats, on='zone_id', how='left')
    
    return df


def prepare_features_and_target(df: pd.DataFrame, target_type: str = 'speed') -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, List[str]]:
    df = df.sort_values(['link_id', 'observed_at']).reset_index(drop=True)
    
    if target_type == 'speed':
        df['target_speed'] = df.groupby('link_id')['speed_midpoint'].shift(-1)
        target_col = 'target_speed'
    elif target_type == 'speed_change':
        df['next_speed'] = df.groupby('link_id')['speed_midpoint'].shift(-1)
        df['target_speed_change'] = df['next_speed'] - df['speed_midpoint']
        target_col = 'target_speed_change'
    elif target_type == 'speed_band':
        df['target_band'] = df.groupby('link_id')['speed_band'].shift(-1)
        target_col = 'target_band'
    else:
        raise ValueError(f"Unknown target_type: {target_type}")
    
    df['next_timestamp'] = df.groupby('link_id')['observed_at'].shift(-1)
    df['target_interval'] = (df['next_timestamp'] - df['observed_at']).dt.total_seconds() / 60
    df['valid_target'] = (df['target_interval'] >= 4) & (df['target_interval'] <= 6)
    df = df.drop(columns=['next_timestamp', 'target_interval'])
    
    feature_cols = [
        'speed_lag_1', 'speed_lag_2', 'speed_lag_3', 'speed_lag_4', 'speed_lag_5', 'speed_lag_6',
        'rolling_mean_3', 'rolling_std_3', 'rolling_min_3', 'rolling_max_3',
        'rolling_mean_6', 'rolling_std_6',
        'speed_trend_15', 'speed_change_5',
        'segment_mean_speed', 'segment_std_speed', 'segment_min_speed', 'segment_max_speed', 'segment_count',
        'road_mean_speed', 'road_std_speed',
        'zone_mean_speed', 'zone_std_speed',
        'hour', 'minute_bucket', 'day_of_week', 'is_weekend', 'is_peak',
        'hour_sin', 'hour_cos', 'minute_sin', 'minute_cos', 'dow_sin', 'dow_cos',
    ]
    
    valid_mask = df['valid_target'] & df['speed_lag_1'].notna()
    if target_type == 'speed':
        valid_mask = valid_mask & df['target_speed'].notna()
    elif target_type == 'speed_change':
        valid_mask = valid_mask & df['target_speed_change'].notna()
    elif target_type == 'speed_band':
        valid_mask = valid_mask & df['target_band'].notna()
    
    df_valid = df[valid_mask].copy()
    
    logger.info(f"Valid training rows ({target_type}): {len(df_valid):,} ({len(df_valid)/len(df)*100:.1f}%)")
    
    X = df_valid[feature_cols]
    if target_type == 'speed':
        y = df_valid['target_speed']
    elif target_type == 'speed_change':
        y = df_valid['target_speed_change']
    elif target_type == 'speed_band':
        y = df_valid['target_band']
    
    return df_valid, X, y, feature_cols


def chronological_split(df: pd.DataFrame, train_ratio: float = 0.7, val_ratio: float = 0.15) -> Tuple[pd.Series, pd.Series, pd.Series]:
    continuous_start = pd.Timestamp('2026-08-21 13:53:00', tz=SG_OFFSET)
    df_continuous = df[df['observed_at'] >= continuous_start].copy()
    
    logger.info(f"Using continuous period: {continuous_start} onwards")
    logger.info(f"Continuous data: {len(df_continuous):,} rows, {df_continuous['observed_at'].nunique()} snapshots")
    
    unique_timestamps = sorted(df_continuous['observed_at'].unique())
    n = len(unique_timestamps)
    
    train_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))
    
    train_timestamps = set(unique_timestamps[:train_end])
    val_timestamps = set(unique_timestamps[train_end:val_end])
    test_timestamps = set(unique_timestamps[val_end:])
    
    train_mask = df['observed_at'].isin(train_timestamps)
    val_mask = df['observed_at'].isin(val_timestamps)
    test_mask = df['observed_at'].isin(test_timestamps)
    
    logger.info(f"Train snapshots: {len(train_timestamps)} ({train_mask.sum():,} rows)")
    logger.info(f"Val snapshots: {len(val_timestamps)} ({val_mask.sum():,} rows)")
    logger.info(f"Test snapshots: {len(test_timestamps)} ({test_mask.sum():,} rows)")
    logger.info(f"Train time range: {min(train_timestamps)} to {max(train_timestamps)}")
    logger.info(f"Val time range: {min(val_timestamps)} to {max(val_timestamps)}")
    logger.info(f"Test time range: {min(test_timestamps)} to {max(test_timestamps)}")
    
    return train_mask, val_mask, test_mask


def evaluate_model(y_true: np.ndarray, y_pred: np.ndarray) -> Tuple[float, float]:
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    return mae, rmse


def evaluate_by_zone(df: pd.DataFrame, y_true_col: str, y_pred_col: str) -> Dict[str, Dict[str, float]]:
    results = {}
    for zone in sorted(df['zone_id'].dropna().unique()):
        zone_df = df[df['zone_id'] == zone]
        if len(zone_df) > 10:
            mae = mean_absolute_error(zone_df[y_true_col], zone_df[y_pred_col])
            rmse = np.sqrt(mean_squared_error(zone_df[y_true_col], zone_df[y_pred_col]))
            results[zone] = {'mae': float(mae), 'rmse': float(rmse), 'n': int(len(zone_df))}
    return results


def evaluate_by_road_category(df: pd.DataFrame, y_true_col: str, y_pred_col: str) -> Dict[str, Dict[str, float]]:
    results = {}
    for cat in sorted(df['road_category'].dropna().unique()):
        cat_df = df[df['road_category'] == cat]
        if len(cat_df) > 10:
            mae = mean_absolute_error(cat_df[y_true_col], cat_df[y_pred_col])
            rmse = np.sqrt(mean_squared_error(cat_df[y_true_col], cat_df[y_pred_col]))
            results[str(cat)] = {'mae': float(mae), 'rmse': float(rmse), 'n': int(len(cat_df))}
    return results


def train_and_evaluate_model(
    model_name: str,
    model,
    X_train, y_train, X_val, y_val, X_test, y_test,
    df_valid, train_mask_valid, val_mask_valid, test_mask_valid,
    baseline_mae, baseline_rmse,
    is_lgb: bool = False
) -> Dict[str, Any]:
    
    logger.info(f"\n{'=' * 60}")
    logger.info(f"{model_name.upper()} TRAINING")
    logger.info(f"{'=' * 60}")
    
    if is_lgb:
        pass
    else:
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=100)
    
    if is_lgb:
        val_pred = model.predict(X_val, num_iteration=model.best_iteration)
        test_pred = model.predict(X_test, num_iteration=model.best_iteration)
    else:
        val_pred = model.predict(X_val)
        test_pred = model.predict(X_test)
    
    val_mae, val_rmse = evaluate_model(y_val.values, val_pred)
    logger.info(f"Val MAE: {val_mae:.4f}, RMSE: {val_rmse:.4f}")
    
    test_mae, test_rmse = evaluate_model(y_test.values, test_pred)
    logger.info(f"Test MAE: {test_mae:.4f}, RMSE: {test_rmse:.4f}")
    
    test_df = df_valid[test_mask_valid].copy()
    test_df['predicted'] = test_pred
    test_df['target'] = y_test.values
    
    zone_metrics = evaluate_by_zone(test_df, 'target', 'predicted')
    road_metrics = evaluate_by_road_category(test_df, 'target', 'predicted')
    
    macro_mae = test_df.groupby('link_id', observed=False).apply(
        lambda g: mean_absolute_error(g['target'], g['predicted'])
    ).mean()
    macro_rmse = test_df.groupby('link_id', observed=False).apply(
        lambda g: np.sqrt(mean_squared_error(g['target'], g['predicted']))
    ).mean()
    
    peak_df = test_df[test_df['is_peak'] == 1]
    peak_mae = mean_absolute_error(peak_df['target'], peak_df['predicted']) if len(peak_df) > 0 else None
    
    improvement_pct = (baseline_mae - test_mae) / baseline_mae * 100
    
    logger.info(f"\n--- {model_name} Results ---")
    logger.info(f"Persistence: MAE={baseline_mae:.4f}, RMSE={baseline_rmse:.4f}")
    logger.info(f"{model_name}:     MAE={test_mae:.4f}, RMSE={test_rmse:.4f}")
    logger.info(f"Improvement: {improvement_pct:.2f}%")
    logger.info(f"Macro MAE: {macro_mae:.4f}, Macro RMSE: {macro_rmse:.4f}")
    logger.info(f"Peak MAE: {peak_mae:.4f}" if peak_mae else "Peak MAE: N/A")
    
    logger.info("\n--- Zone Metrics ---")
    for zone, m in zone_metrics.items():
        logger.info(f"  {zone}: MAE={m['mae']:.4f}, RMSE={m['rmse']:.4f}, n={m['n']:,}")
    
    logger.info("\n--- Road Category Metrics ---")
    for cat, m in road_metrics.items():
        logger.info(f"  {cat}: MAE={m['mae']:.4f}, RMSE={m['rmse']:.4f}, n={m['n']:,}")
    
    return {
        'model_name': model_name,
        'model': model,
        'val_mae': float(val_mae), 'val_rmse': float(val_rmse),
        'test_mae': float(test_mae), 'test_rmse': float(test_rmse),
        'macro_mae': float(macro_mae), 'macro_rmse': float(macro_rmse),
        'peak_mae': float(peak_mae) if peak_mae else None,
        'improvement_pct': float(improvement_pct),
        'zone_metrics': zone_metrics,
        'road_metrics': road_metrics,
        'beats_persistence': test_mae < baseline_mae,
        'predictions': test_pred,
    }


def main():
    logger.info("=" * 60)
    logger.info("URBANOS TRAFFIC ML — RESIDUAL LEARNING (SPEED CHANGE)")
    logger.info("=" * 60)
    
    # 1. Audit database
    db_stats = audit_database()
    
    # 2. Load complete snapshots
    df = load_complete_snapshots()
    
    # 3. Create features
    df = create_lag_features(df)
    df = create_calendar_features(df)
    
    # 4. Chronological split
    train_mask, val_mask, test_mask = chronological_split(df)
    
    # 5. Create segment features
    df = create_segment_features(df, train_mask)
    
    # 6. Prepare features and target (SPEED CHANGE / RESIDUAL)
    df_valid, X, y, feature_cols = prepare_features_and_target(df, target_type='speed_change')
    
    train_mask_valid = train_mask[df_valid.index]
    val_mask_valid = val_mask[df_valid.index]
    test_mask_valid = test_mask[df_valid.index]
    
    X_train = X[train_mask_valid]
    y_train = y[train_mask_valid]
    X_val = X[val_mask_valid]
    y_val = y[val_mask_valid]
    X_test = X[test_mask_valid]
    y_test = y[test_mask_valid]
    
    logger.info(f"Train: {len(X_train):,}, Val: {len(X_val):,}, Test: {len(X_test):,}")
    logger.info(f"Features: {len(feature_cols)}")
    logger.info(f"Target (speed_change) range: {y.min():.2f} to {y.max():.2f}")
    logger.info(f"Target mean: {y.mean():.4f}, std: {y.std():.4f}")
    
    # 7. Persistence baseline for speed change (predict 0 change)
    baseline_mae, baseline_rmse = evaluate_model(y_test.values, np.zeros_like(y_test.values))
    logger.info(f"Test Baseline MAE: {baseline_mae:.4f}, RMSE: {baseline_rmse:.4f}")
    
    # 8. Train LightGBM
    lgb_params = {
        'objective': 'regression',
        'metric': 'mae',
        'boosting_type': 'gbdt',
        'num_leaves': 63,
        'learning_rate': 0.05,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'min_child_samples': 50,
        'verbosity': -1,
        'random_state': SEED,
        'n_jobs': -1,
        'force_col_wise': True,
    }
    
    lgb_train = lgb.Dataset(X_train, label=y_train)
    lgb_val = lgb.Dataset(X_val, label=y_val, reference=lgb_train)
    
    lgb_model = lgb.train(
        lgb_params,
        lgb_train,
        valid_sets=[lgb_val],
        num_boost_round=1000,
        callbacks=[lgb.early_stopping(100), lgb.log_evaluation(100)]
    )
    
    lgb_result = train_and_evaluate_model(
        'LightGBM', lgb_model, X_train, y_train, X_val, y_val, X_test, y_test,
        df_valid, train_mask_valid, val_mask_valid, test_mask_valid,
        baseline_mae, baseline_rmse,
        is_lgb=True
    )
    
    # 9. Train XGBoost
    xgb_params = {
        'objective': 'reg:squarederror',
        'eval_metric': 'mae',
        'max_depth': 8,
        'learning_rate': 0.03,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'min_child_weight': 20,
        'random_state': SEED,
        'n_jobs': -1,
        'verbosity': 0,
        'reg_alpha': 0.1,
        'reg_lambda': 1.0,
    }
    
    xgb_model = xgb.XGBRegressor(**xgb_params, n_estimators=1000, early_stopping_rounds=100)
    xgb_model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=100)
    
    xgb_result = train_and_evaluate_model(
        'XGBoost', xgb_model, X_train, y_train, X_val, y_val, X_test, y_test,
        df_valid, train_mask_valid, val_mask_valid, test_mask_valid,
        baseline_mae, baseline_rmse,
        is_lgb=False
    )
    
    # 10. Select best model
    models = {'LightGBM': lgb_result, 'XGBoost': xgb_result}
    best_name = min(models.keys(), key=lambda k: models[k]['val_mae'])
    best = models[best_name]
    
    logger.info("\n" + "=" * 60)
    logger.info("FINAL MODEL COMPARISON")
    logger.info("=" * 60)
    logger.info(f"Persistence (0 change): MAE={baseline_mae:.4f}, RMSE={baseline_rmse:.4f}")
    for name, res in models.items():
        logger.info(f"{name}: Val MAE={res['val_mae']:.4f}, Val RMSE={res['val_rmse']:.4f}, Test MAE={res['test_mae']:.4f}, Test RMSE={res['test_rmse']:.4f}, Beats persistence: {res['beats_persistence']}")
    
    logger.info(f"\nBEST MODEL: {best_name}")
    logger.info(f"Beats persistence: {best['beats_persistence']}")
    
    # Save best model
    best_model = best['model']
    if best_name == 'LightGBM':
        best_model.save_model(MODEL_DIR / "traffic_speed_change_predictor_lgb.txt")
        with open(MODEL_DIR / "traffic_speed_change_predictor_lgb.pkl", 'wb') as f:
            pickle.dump({'model_type': 'LightGBM', 'model': best_model, 'best_iteration': best_model.best_iteration}, f)
    else:
        best_model.save_model(MODEL_DIR / "traffic_speed_change_predictor_xgb.json")
        with open(MODEL_DIR / "traffic_speed_change_predictor_xgb.pkl", 'wb') as f:
            pickle.dump({'model_type': 'XGBoost', 'model': best_model}, f)
    
    # Save feature config
    cat_features = ['road_category']
    feature_config = {
        'feature_columns': feature_cols,
        'categorical_features': cat_features,
        'target': 'target_speed_change (speed_midpoint change at t+5min)',
        'prediction_horizon_minutes': 5,
        'lags': [1, 2, 3, 4, 5, 6],
        'segment_stats': ['segment_mean_speed', 'segment_std_speed', 'segment_min_speed', 'segment_max_speed', 'segment_count'],
        'road_stats': ['road_mean_speed', 'road_std_speed'],
        'zone_stats': ['zone_mean_speed', 'zone_std_speed'],
        'rolling_features': ['rolling_mean_3', 'rolling_std_3', 'rolling_min_3', 'rolling_max_3', 'rolling_mean_6', 'rolling_std_6'],
        'trend_features': ['speed_trend_15', 'speed_change_5'],
        'calendar_features': ['hour', 'minute_bucket', 'day_of_week', 'is_weekend', 'is_peak',
                              'hour_sin', 'hour_cos', 'minute_sin', 'minute_cos', 'dow_sin', 'dow_cos'],
        'model_type': best_name,
    }
    
    with open(MODEL_DIR / "feature_config_speed_change.json", 'w') as f:
        json.dump(feature_config, f, indent=2)
    
    # Save predictions sample
    test_df = df_valid[test_mask_valid].copy()
    test_df['predicted_change'] = best['predictions']
    test_df['target_change'] = y_test.values
    test_df['error'] = test_df['predicted_change'] - test_df['target_change']
    
    sample_cols = ['observed_at', 'link_id', 'target_change', 'predicted_change', 'error']
    test_df[sample_cols].to_csv(PROCESSED_DIR / 'traffic_speed_change_predictions_sample.csv', index=False)
    
    # Save metrics
    metrics = {
        'selected_model': best_name,
        'target_type': 'speed_change',
        'beats_persistence': best['beats_persistence'],
        'improvement_pct': best['improvement_pct'],
        'test_mae': best['test_mae'],
        'test_rmse': best['test_rmse'],
        'val_mae': best['val_mae'],
        'val_rmse': best['val_rmse'],
        'baseline_mae': baseline_mae,
        'baseline_rmse': baseline_rmse,
        'peak_mae': best['peak_mae'],
        'macro_mae': best['macro_mae'],
        'macro_rmse': best['macro_rmse'],
        'train_samples': int(len(X_train)),
        'val_samples': int(len(X_val)),
        'test_samples': int(len(X_test)),
        'n_linkids': int(df_valid['link_id'].nunique()),
        'n_snapshots': int(df_valid['observed_at'].nunique()),
        'feature_list': feature_cols,
        'zone_metrics': best['zone_metrics'],
        'road_category_metrics': best['road_metrics'],
        'database_stats': db_stats,
        'excluded_rows': int(len(df) - len(df_valid)),
        'exclusion_reason': 'Missing lag history (first 5 snapshots per LinkID) or invalid target interval',
        'total_raw_observations': int(len(df)),
        'valid_ml_rows': int(len(df_valid)),
        'all_models': {k: {kk: vv for kk, vv in v.items() if kk != 'model' and kk != 'predictions'} for k, v in models.items()},
    }
    
    with open(MODEL_DIR / "model_metrics_speed_change.json", 'w') as f:
        json.dump(metrics, f, indent=2)
    
    logger.info(f"\nBest model saved: {best_name}")
    logger.info(f"Feature config: {MODEL_DIR}/feature_config_speed_change.json")
    logger.info(f"Metrics: {MODEL_DIR}/model_metrics_speed_change.json")
    logger.info(f"Predictions sample: {PROCESSED_DIR}/traffic_speed_change_predictions_sample.csv")
    
    return metrics


if __name__ == '__main__':
    metrics = main()