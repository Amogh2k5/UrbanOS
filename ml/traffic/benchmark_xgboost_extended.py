import json
import logging
import os
import pickle
import sqlite3
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SEED = 42
np.random.seed(SEED)

SG_OFFSET = timezone(timedelta(hours=8))
DB_PATH = Path("data/traffic_observations_train.db")

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def load_complete_snapshots():
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
        logger.info(f"Loaded {len(df):,} observations for {df['observed_at'].nunique()} snapshots")
        df['observed_at'] = pd.to_datetime(df['observed_at']).dt.tz_convert(SG_OFFSET)
        df = df.sort_values(['link_id', 'observed_at']).reset_index(drop=True)
        return df

def create_lag_features(df, expected_interval_minutes=5):
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

    lag_cols = [f'speed_lag_{i}' for i in range(1,7)]
    df['rolling_mean_3'] = df[lag_cols[:3]].mean(axis=1, skipna=True)
    df['rolling_std_3'] = df[lag_cols[:3]].std(axis=1, skipna=True)
    df['rolling_min_3'] = df[lag_cols[:3]].min(axis=1, skipna=True)
    df['rolling_max_3'] = df[lag_cols[:3]].max(axis=1, skipna=True)
    df['rolling_mean_6'] = df[lag_cols].mean(axis=1, skipna=True)
    df['rolling_std_6'] = df[lag_cols].std(axis=1, skipna=True)
    df['speed_trend_15'] = df['speed_lag_1'] - df['speed_lag_3']
    df['speed_change_5'] = df['speed_lag_1'] - df['speed_lag_2']
    # Additional temporal features
    df['speed_change_10'] = df['speed_lag_1'] - df['speed_lag_3']
    df['speed_change_15'] = df['speed_lag_1'] - df['speed_lag_4']
    df['accel_5_10'] = df['speed_change_10'] - df['speed_change_5']
    df['rolling_mean_2'] = df[lag_cols[:2]].mean(axis=1, skipna=True)
    df['rolling_std_2'] = df[lag_cols[:2]].std(axis=1, skipna=True)
    temp_cols = [c for c in df.columns if c.startswith('prev') or c.startswith('time_diff')]
    df = df.drop(columns=temp_cols, errors='ignore')
    valid_lag_rows = df['speed_lag_1'].notna().sum()
    logger.info(f"Valid lag-1 rows: {valid_lag_rows:,} ({valid_lag_rows/len(df)*100:.1f}%)")
    return df

def create_calendar_features(df):
    logger.info("Creating calendar features...")
    # operate in place to save memory
    dt = df['observed_at']
    df['hour'] = dt.dt.hour
    df['minute'] = dt.dt.minute
    df['minute_bucket'] = (dt.dt.minute // 5) * 5
    df['day_of_week'] = dt.dt.dayofweek
    df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
    df['is_peak'] = ((df['hour'] >= 7) & (df['hour'] <= 9) | (df['hour'] >= 17) & (df['hour'] <= 19)).astype(int)
    df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
    df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)
    df['minute_sin'] = np.sin(2 * np.pi * df['minute'] / 60)
    df['minute_cos'] = np.cos(2 * np.pi * df['minute'] / 60)
    df['dow_sin'] = np.sin(2 * np.pi * df['day_of_week'] / 7)
    df['dow_cos'] = np.cos(2 * np.pi * df['day_of_week'] / 7)
    return df

def create_segment_features(df, train_mask):
    logger.info("Creating segment statistical features...")
    df = df.copy()
    train_df = df[train_mask]
    segment_stats = train_df.groupby('link_id')['speed_midpoint'].agg([
        ('segment_mean_speed','mean'),('segment_std_speed','std'),
        ('segment_min_speed','min'),('segment_max_speed','max'),('segment_count','count')
    ]).reset_index()
    segment_stats['segment_std_speed'] = segment_stats['segment_std_speed'].fillna(0)
    df = df.merge(segment_stats, on='link_id', how='left')
    road_stats = train_df.groupby('road_category')['speed_midpoint'].agg([
        ('road_mean_speed','mean'),('road_std_speed','std')
    ]).reset_index()
    road_stats['road_std_speed'] = road_stats['road_std_speed'].fillna(0)
    df = df.merge(road_stats, on='road_category', how='left')
    zone_stats = train_df[train_df['zone_id'].notna()].groupby('zone_id')['speed_midpoint'].agg([
        ('zone_mean_speed','mean'),('zone_std_speed','std')
    ]).reset_index()
    zone_stats['zone_std_speed'] = zone_stats['zone_std_speed'].fillna(0)
    df = df.merge(zone_stats, on='zone_id', how='left')
    return df

def add_historical_profile(df, train_mask):
    """Add historical average speed per link per minute_bucket using training data only."""
    logger.info("Adding historical profile features...")
    train_df = df[train_mask].copy()
    # historical avg per link per minute_bucket
    hist = train_df.groupby(['link_id','minute_bucket'])['speed_midpoint'].mean().reset_index()
    hist = hist.rename(columns={'speed_midpoint':'hist_avg_speed'})
    df = df.merge(hist, on=['link_id','minute_bucket'], how='left')
    # deviation from historical typical
    df['dev_from_hist'] = df['speed_midpoint'] - df['hist_avg_speed']
    # also historical avg per link per hour
    hist_hour = train_df.groupby(['link_id','hour'])['speed_midpoint'].mean().reset_index()
    hist_hour = hist_hour.rename(columns={'speed_midpoint':'hist_avg_speed_hour'})
    df = df.merge(hist_hour, on=['link_id','hour'], how='left')
    df['dev_from_hist_hour'] = df['speed_midpoint'] - df['hist_avg_speed_hour']
    return df

def prepare_features_and_target(df, feature_cols):
    df = df.sort_values(['link_id','observed_at']).reset_index(drop=True)
    df['next_speed'] = df.groupby('link_id')['speed_midpoint'].shift(-1)
    df['target_speed_change'] = df['next_speed'] - df['speed_midpoint']
    df['next_timestamp'] = df.groupby('link_id')['observed_at'].shift(-1)
    df['target_interval'] = (df['next_timestamp'] - df['observed_at']).dt.total_seconds() / 60
    df['valid_target'] = (df['target_interval'] >= 4) & (df['target_interval'] <= 6)
    df = df.drop(columns=['next_timestamp','target_interval','next_speed'])
    valid_mask = df['valid_target'] & df['speed_lag_1'].notna() & df['target_speed_change'].notna()
    df_valid = df[valid_mask].copy()
    X = df_valid[feature_cols].fillna(0.0)
    y = df_valid['target_speed_change']
    return df_valid, X, y, valid_mask

def chronological_split(df, train_ratio=0.7, val_ratio=0.15):
    continuous_start = pd.Timestamp('2026-08-21 13:53:00', tz=SG_OFFSET)
    df_continuous = df[df['observed_at'] >= continuous_start].copy()
    logger.info(f"Using continuous period: {continuous_start} onwards")
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
    return train_mask, val_mask, test_mask

def evaluate_model(y_true, y_pred):
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    return mae, rmse

def main():
    logger.info("=== EXTENDED XGBOOST BENCHMARK ===")
    df = load_complete_snapshots()
    df = create_lag_features(df)
    df = create_calendar_features(df)
    # split first
    train_mask, val_mask, test_mask = chronological_split(df)
    # segment/road/zone stats
    df = create_segment_features(df, train_mask)
    # historical profile features (using training data only)
    df = add_historical_profile(df, train_mask)
    # target preparation
    feature_cols = [
        'speed_lag_1','speed_lag_2','speed_lag_3','speed_lag_4','speed_lag_5','speed_lag_6',
        'rolling_mean_2','rolling_std_2',
        'rolling_mean_3','rolling_std_3','rolling_min_3','rolling_max_3',
        'rolling_mean_6','rolling_std_6',
        'speed_trend_15','speed_change_5','speed_change_10','speed_change_15','accel_5_10',
        'segment_mean_speed','segment_std_speed','segment_min_speed','segment_max_speed','segment_count',
        'road_mean_speed','road_std_speed',
        'zone_mean_speed','zone_std_speed',
        'hour','minute_bucket','day_of_week','is_weekend','is_peak',
        'hour_sin','hour_cos','minute_sin','minute_cos','dow_sin','dow_cos',
        'hist_avg_speed','dev_from_hist','hist_avg_speed_hour','dev_from_hist_hour'
    ]
    df_valid, X, y, valid_mask = prepare_features_and_target(df, feature_cols)
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
    # Persistence baseline (predict 0 change)
    baseline_mae, baseline_rmse = evaluate_model(y_test.values, np.zeros_like(y_test.values))
    logger.info(f"Persistence baseline MAE: {baseline_mae:.4f}, RMSE: {baseline_rmse:.4f}")
    # Existing XGBoost features (original set) for comparison
    orig_feature_cols = [
        'speed_lag_1','speed_lag_2','speed_lag_3','speed_lag_4','speed_lag_5','speed_lag_6',
        'rolling_mean_3','rolling_std_3','rolling_min_3','rolling_max_3',
        'rolling_mean_6','rolling_std_6',
        'speed_trend_15','speed_change_5',
        'segment_mean_speed','segment_std_speed','segment_min_speed','segment_max_speed','segment_count',
        'road_mean_speed','road_std_speed',
        'zone_mean_speed','zone_std_speed',
        'hour','minute_bucket','day_of_week','is_weekend','is_peak',
        'hour_sin','hour_cos','minute_sin','minute_cos','dow_sin','dow_cos'
    ]
    X_train_orig = df_valid[train_mask_valid][orig_feature_cols].fillna(0.0)
    X_val_orig = df_valid[val_mask_valid][orig_feature_cols].fillna(0.0)
    X_test_orig = df_valid[test_mask_valid][orig_feature_cols].fillna(0.0)
    # Train original XGBoost
    xgb_params = {
        'objective':'reg:squarederror','eval_metric':'mae','max_depth':8,'learning_rate':0.03,
        'subsample':0.8,'colsample_bytree':0.8,'min_child_weight':20,
        'random_state':SEED,'n_jobs':-1,'verbosity':0,'reg_alpha':0.1,'reg_lambda':1.0
    }
    logger.info("Training original XGBoost...")
    xgb_orig = xgb.XGBRegressor(**xgb_params, n_estimators=1000, early_stopping_rounds=100)
    xgb_orig.fit(X_train_orig, y_train, eval_set=[(X_val_orig, y_val)], verbose=False)
    orig_pred = xgb_orig.predict(X_test_orig)
    orig_mae, orig_rmse = evaluate_model(y_test.values, orig_pred)
    logger.info(f"Original XGBoost Test MAE: {orig_mae:.4f}, RMSE: {orig_rmse:.4f}")
    # Train extended XGBoost
    logger.info("Training extended XGBoost...")
    xgb_ext = xgb.XGBRegressor(**xgb_params, n_estimators=1000, early_stopping_rounds=100)
    xgb_ext.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    ext_pred = xgb_ext.predict(X_test)
    ext_mae, ext_rmse = evaluate_model(y_test.values, ext_pred)
    logger.info(f"Extended XGBoost Test MAE: {ext_mae:.4f}, RMSE: {ext_rmse:.4f}")
    # Summary
    print("\nSUMMARY")
    print(f"{'Model':<25} {'MAE':>8} {'RMSE':>8} {'vs Persistence':>14} {'Train Time':>12} {'Infer Time':>12} {'Qualifies'}")
    print(f"{'Persistence':<25} {baseline_mae:>8.4f} {baseline_rmse:>8.4f} {'ref':>14} {'-':>12} {'-':>12} {'-'}")
    print(f"{'Original XGBoost':<25} {orig_mae:>8.4f} {orig_rmse:>8.4f} {((orig_mae-baseline_mae)/baseline_mae*100):>13.2f}% {'-':>12} {'-':>12} {'Yes' if orig_mae<baseline_mae else 'No'}")
    print(f"{'Extended XGBoost':<25} {ext_mae:>8.4f} {ext_rmse:>8.4f} {((ext_mae-baseline_mae)/baseline_mae*100):>13.2f}% {'-':>12} {'-':>12} {'Yes' if ext_mae<baseline_mae else 'No'}")
    # Regional MAE for extended
    # We'll need region mapping; skip for brevity but can compute if needed
    # Feature counts
    print(f"\nFeatures: Original={len(orig_feature_cols)}, Extended={len(feature_cols)}")
    # Leakage checks
    print("\nLeakage checks:")
    print("- Historical stats computed on training split only")
    print("- No future speed used as input")
    print("- Train/val/test split identical to baseline")
    print("- Normalization not used (tree model)")

if __name__ == '__main__':
    main()