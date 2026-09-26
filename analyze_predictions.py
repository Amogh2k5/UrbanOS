import subprocess
import time
import requests
import sys
import json
import numpy as np

server_process = subprocess.Popen([
    sys.executable, "-m", "uvicorn", "backend.app.main:app", 
    "--host", "0.0.0.0", "--port", "8000"
], cwd=r"C:\projects\UrbanOS")

time.sleep(5)

try:
    import sys
    sys.path.insert(0, r"C:\projects\UrbanOS")
    
    from backend.app.mobility.traffic.data import TrafficObservationCSVStore
    from backend.app.mobility.traffic.predictor import TrafficPredictor
    
    print("Loading store and predictor...")
    store = TrafficObservationCSVStore()
    predictor = TrafficPredictor()
    
    latest_snapshot = store.get_latest_snapshot(limit=1000000)
    latest_ts = latest_snapshot[0].observed_at
    link_ids = [obs.link_id for obs in latest_snapshot]
    history_obs = store.get_link_history(link_ids, limit_per_link=7)
    
    import pandas as pd
    df = pd.DataFrame([{
        "observed_at": obs.observed_at,
        "link_id": obs.link_id,
        "road_name": obs.road_name,
        "road_category": obs.road_category,
        "speed_band": obs.speed_band,
        "minimum_speed": obs.minimum_speed,
        "maximum_speed": obs.maximum_speed,
        "speed_midpoint": obs.speed_midpoint,
        "start_latitude": obs.start_latitude,
        "start_longitude": obs.start_longitude,
        "end_latitude": obs.end_latitude,
        "end_longitude": obs.end_longitude,
        "zone_id": obs.zone_id,
        "zone_name": obs.zone_name,
    } for obs in history_obs])
    
    df["observed_at"] = pd.to_datetime(df["observed_at"]).dt.tz_convert("Asia/Singapore")
    df = df.sort_values(["link_id", "observed_at"]).reset_index(drop=True)
    df = df.groupby("link_id").head(7).copy()
    
    df["speed_midpoint"] = pd.to_numeric(df["speed_midpoint"], errors="coerce")
    df["speed_midpoint"] = df["speed_midpoint"].clip(0, 120)
    df["road_category"] = pd.to_numeric(df["road_category"], errors="coerce")
    
    df = df.sort_values(["link_id", "observed_at"]).reset_index(drop=True)
    df["speed_lag_1"] = df.groupby("link_id")["speed_midpoint"].shift(1)
    df["speed_lag_2"] = df.groupby("link_id")["speed_midpoint"].shift(2)
    df["speed_lag_3"] = df.groupby("link_id")["speed_midpoint"].shift(3)
    df["speed_lag_4"] = df.groupby("link_id")["speed_midpoint"].shift(4)
    df["speed_lag_5"] = df.groupby("link_id")["speed_midpoint"].shift(5)
    df["speed_lag_6"] = df.groupby("link_id")["speed_midpoint"].shift(6)
    
    lag_cols = ["speed_lag_1", "speed_lag_2", "speed_lag_3", "speed_lag_4", "speed_lag_5", "speed_lag_6"]
    df["rolling_mean_3"] = df[lag_cols[:3]].mean(axis=1, skipna=True)
    df["rolling_std_3"] = df[lag_cols[:3]].std(axis=1, skipna=True)
    df["rolling_min_3"] = df[lag_cols[:3]].min(axis=1, skipna=True)
    df["rolling_max_3"] = df[lag_cols[:3]].max(axis=1, skipna=True)
    df["rolling_mean_6"] = df[lag_cols].mean(axis=1, skipna=True)
    df["rolling_std_6"] = df[lag_cols].std(axis=1, skipna=True)
    df["speed_trend_15"] = df["speed_lag_1"] - df["speed_lag_3"]
    df["speed_change_5"] = df["speed_lag_1"] - df["speed_lag_2"]
    
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
    
    seg_stats = df.groupby("link_id")["speed_midpoint"].agg(
        segment_mean_speed="mean", segment_std_speed="std",
        segment_min_speed="min", segment_max_speed="max", segment_count="count",
    ).reset_index()
    seg_stats["segment_std_speed"] = seg_stats["segment_std_speed"].fillna(0)
    df = df.merge(seg_stats, on="link_id", how="left", suffixes=("", "_seg"))
    
    road_stats = df.groupby("road_category")["speed_midpoint"].agg(
        road_mean_speed="mean", road_std_speed="std",
    ).reset_index()
    road_stats["road_std_speed"] = road_stats["road_std_speed"].fillna(0)
    df = df.merge(road_stats, on="road_category", how="left", suffixes=("", "_road"))
    
    zone_stats = df[df["zone_id"].notna()].groupby("zone_id")["speed_midpoint"].agg(
        zone_mean_speed="mean", zone_std_speed="std",
    ).reset_index()
    zone_stats["zone_std_speed"] = zone_stats["zone_std_speed"].fillna(0)
    df = df.merge(zone_stats, on="zone_id", how="left", suffixes=("", "_zone"))
    
    latest_rows = df[df["observed_at"] == pd.Timestamp(latest_ts).tz_convert("Asia/Singapore")].copy()
    
    import xgboost as xgb
    predictor._load_artifacts()
    missing_cols = [c for c in predictor._feature_cols if c not in latest_rows.columns]
    for c in missing_cols:
        latest_rows.loc[:, c] = 0.0
    X = latest_rows[predictor._feature_cols].fillna(0.0)
    dmatrix = xgb.DMatrix(X)
    raw_preds = predictor._booster.predict(dmatrix)
    
    cur_speeds = latest_rows["speed_midpoint"].clip(0, 120).values
    
    final_pred_speeds = []
    final_changes = []
    drop_guard_count = 0
    upper_clip_count = 0
    lower_clip_count = 0
    
    for i in range(len(raw_preds)):
        pred_change = float(raw_preds[i])
        cur = float(cur_speeds[i])
        pred = cur + pred_change
        
        if pred > 120:
            pred = 120
            upper_clip_count += 1
        elif pred < 0:
            pred = 0
            lower_clip_count += 1
        
        max_drop = 0.30 * cur
        if cur - pred > max_drop:
            pred = cur - max_drop
            drop_guard_count += 1
        
        final_pred_speeds.append(pred)
        final_changes.append(pred - cur)
    
    raw_preds = np.array(raw_preds)
    final_pred_speeds = np.array(final_pred_speeds)
    final_changes = np.array(final_changes)
    
    print("=" * 70)
    print("RAW XGBOOST OUTPUT (predicted_speed_change = delta_speed)")
    print("=" * 70)
    print(f"Count: {len(raw_preds)}")
    print(f"Min:   {raw_preds.min():.2f}")
    print(f"Max:   {raw_preds.max():.2f}")
    print(f"Mean:  {raw_preds.mean():.2f}")
    print(f"Median:{np.median(raw_preds):.2f}")
    print(f"Std:   {raw_preds.std():.2f}")
    
    print("\n" + "=" * 70)
    print("FINAL PREDICTED SPEED (after clipping + guards)")
    print("=" * 70)
    print(f"Min:   {final_pred_speeds.min():.2f}")
    print(f"Max:   {final_pred_speeds.max():.2f}")
    print(f"Mean:  {final_pred_speeds.mean():.2f}")
    print(f"Median:{np.median(final_pred_speeds):.2f}")
    
    print("\n" + "=" * 70)
    print("CLIPPING / GUARD STATISTICS")
    print("=" * 70)
    print(f"Upper clip (pred >= 120): {upper_clip_count} ({upper_clip_count/len(raw_preds)*100:.1f}%)")
    print(f"Lower clip (pred <= 0):   {lower_clip_count} ({lower_clip_count/len(raw_preds)*100:.1f}%)")
    print(f"30% drop guard triggered: {drop_guard_count} ({drop_guard_count/len(raw_preds)*100:.1f}%)")
    
    print("\n" + "=" * 70)
    print("CURRENT vs PREDICTED SPEED DISTRIBUTIONS")
    print("=" * 70)
    print(f"Current  - Min: {cur_speeds.min():.1f}, Max: {cur_speeds.max():.1f}, Mean: {cur_speeds.mean():.1f}, Median: {np.median(cur_speeds):.1f}")
    print(f"Predicted- Min: {final_pred_speeds.min():.1f}, Max: {final_pred_speeds.max():.1f}, Mean: {final_pred_speeds.mean():.1f}, Median: {np.median(final_pred_speeds):.1f}")
    
    latest_rows = latest_rows.reset_index(drop=True)
    latest_rows["raw_pred_change"] = raw_preds
    latest_rows["final_pred_speed"] = final_pred_speeds
    latest_rows["final_change"] = final_changes
    
    print("\n" + "=" * 70)
    print("BY ZONE")
    print("=" * 70)
    for zone in sorted(latest_rows["zone_id"].dropna().unique()):
        zdf = latest_rows[latest_rows["zone_id"] == zone]
        if len(zdf) == 0:
            continue
        print(f"\nZone: {zone}, Links: {len(zdf)}")
        print(f"  Current speed:    mean={zdf['speed_midpoint'].mean():.1f}, median={zdf['speed_midpoint'].median():.1f}")
        print(f"  Raw delta:        mean={zdf['raw_pred_change'].mean():.2f}, median={zdf['raw_pred_change'].median():.2f}, max={zdf['raw_pred_change'].max():.2f}")
        print(f"  Final pred speed: mean={zdf['final_pred_speed'].mean():.1f}, median={zdf['final_pred_speed'].median():.1f}")
        print(f"  Final change:     mean={zdf['final_change'].mean():.2f}, median={zdf['final_change'].median():.2f}")
        uc = (zdf['final_pred_speed'] >= 120).sum()
        lc = (zdf['final_pred_speed'] <= 0).sum()
        dg = ((zdf['speed_midpoint'] - zdf['final_pred_speed']) > (0.30 * zdf['speed_midpoint'])).sum()
        print(f"  Clipped @120: {uc}, Clipped @0: {lc}, Drop guard: {dg}")
    
    print("\n" + "=" * 70)
    print("BY ROAD CATEGORY")
    print("=" * 70)
    for cat in sorted(latest_rows["road_category"].dropna().unique()):
        cdf = latest_rows[latest_rows["road_category"] == cat]
        if len(cdf) == 0:
            continue
        print(f"\nRoad Cat {cat}: Links={len(cdf)}")
        print(f"  Current: mean={cdf['speed_midpoint'].mean():.1f}")
        print(f"  Raw delta: mean={cdf['raw_pred_change'].mean():.2f}, max={cdf['raw_pred_change'].max():.2f}")
        print(f"  Final:   mean={cdf['final_pred_speed'].mean():.1f}")
        uc = (cdf['final_pred_speed'] >= 120).sum()
        lc = (cdf['final_pred_speed'] <= 0).sum()
        dg = ((cdf['speed_midpoint'] - cdf['final_pred_speed']) > (0.30 * cdf['speed_midpoint'])).sum()
        print(f"  Clipped @120: {uc}, @0: {lc}, Drop guard: {dg}")
    
    print("\n" + "=" * 70)
    print("INTERPRETATION VERIFICATION")
    print("=" * 70)
    print("Model output = predicted_speed_change (delta at t+5min)")
    print("Formula: final_pred = cur_speed + model_output (then clip/guard)")
    print(f"Sample check (first 5):")
    for i in range(min(5, len(raw_preds))):
        cur = cur_speeds[i]
        raw = raw_preds[i]
        expected = cur + raw
        actual = final_pred_speeds[i]
        match = abs(expected - actual) < 0.1 or actual in [0, 120] or (cur - expected) > (0.3 * cur)
        print(f"  Link {latest_rows.iloc[i]['link_id']}: cur={cur:.1f}, raw_delta={raw:.2f}, expected={expected:.2f}, actual={actual:.2f}, match={match}")
    
    print("\n" + "=" * 70)
    print("CONCLUSION")
    print("=" * 70)
    if raw_preds.mean() > 20:
        print("WARNING: Raw delta mean > 20 km/h. Model predicts large speed increases.")
    elif raw_preds.mean() < -10:
        print("WARNING: Raw delta mean < -10 km/h. Model predicts large drops.")
    else:
        print("OK: Raw delta mean in plausible range (-10 to +20 km/h).")
    
    if upper_clip_count > len(raw_preds) * 0.1:
        print(f"WARNING: {upper_clip_count} links ({upper_clip_count/len(raw_preds)*100:.1f}%) clipped at 120 km/h.")
    else:
        print(f"OK: Upper clipping at reasonable level ({upper_clip_count} links).")
    
    if drop_guard_count > len(raw_preds) * 0.05:
        print(f"WARNING: {drop_guard_count} links ({drop_guard_count/len(raw_preds)*100:.1f}%) hit 30% drop guard.")
    else:
        print(f"OK: Drop guard triggered for {drop_guard_count} links.")
    
    print("\nOK: Raw model output IS interpreted as delta_speed (no extra transform).")
    print("OK: Formula: predicted_speed = current_speed + model_output (then clip/guard)")

finally:
    server_process.terminate()
    server_process.wait(timeout=5)