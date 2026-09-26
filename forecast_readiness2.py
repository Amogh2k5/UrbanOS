import os
import sys
import time
import pandas as pd
from collections import Counter
from pathlib import Path

sys.path.insert(0, r"C:\projects\UrbanOS")

csv_path = Path(r"C:\projects\UrbanOS\data\traffic\traffic_observations.csv")
print("=== CSV Inspection ===")
if not csv_path.exists():
    print("CSV not found")
else:
    df = pd.read_csv(csv_path)
    print(f"Total rows: {len(df)}")
    print(f"Unique LinkIDs: {df['link_id'].nunique()}")
    print(f"Unique timestamps: {df['observed_at'].nunique()}")
    print(f"Oldest timestamp: {df['observed_at'].min()}")
    print(f"Newest timestamp: {df['observed_at'].max()}")
    print(f"Unique road names: {df['road_name'].nunique()}")
    print(f"Road categories: {df['road_category'].unique()}")
    print("\nZone ID distribution:")
    print(df['zone_id'].value_counts().to_string())
    ts_counts = df.groupby('observed_at').size()
    print(f"\nRows per timestamp: min={ts_counts.min()}, max={ts_counts.max()}, mean={ts_counts.mean():.1f}")
    seq_counts = df.groupby('link_id').size()
    print(f"\nObservations per link: min={seq_counts.min()}, max={seq_counts.max()}, mean={seq_counts.mean():.1f}")
    links_with_7plus = (seq_counts >= 7).sum()
    print(f"Links with >=7 observations: {links_with_7plus} / {len(seq_counts)}")
    LEGACY_TO_REGION = {
        "SG_CENTRAL_NORTH": "Central",
        "SG_CENTRAL_SOUTH": "Central",
        "SG_EAST": "East",
        "SG_NORTH": "North",
        "SG_NORTH_EAST": "North-East",
        "SG_WEST_NORTH": "West",
        "SG_WEST_SOUTH": "West",
        "SG_SENTOSA": "Central",
    }
    df['region'] = df['zone_id'].map(LEGACY_TO_REGION).fillna('Unknown')
    print("\nFive-region distribution (latest snapshot):")
    latest_ts = df['observed_at'].max()
    latest_df = df[df['observed_at'] == latest_ts]
    reg_dist = latest_df['region'].value_counts()
    print(reg_dist.to_string())

# 2. Run predictor with CSV store
print("\n=== Running Predictor ===")
from backend.app.mobility.traffic.data import TrafficObservationCSVStore
from backend.app.mobility.traffic.predictor import TrafficPredictor

store = TrafficObservationCSVStore(csv_path=csv_path)
predictor = TrafficPredictor()

start = time.time()
try:
    features_df, link_preds, diagnostics = predictor.predict_latest(store)
    elapsed = time.time() - start
    print(f"Prediction latency: {elapsed:.2f}s")
    print(f"Predictions generated: {len(link_preds)}")
    LEGACY_TO_REGION = {
        "SG_CENTRAL_NORTH": "Central",
        "SG_CENTRAL_SOUTH": "Central",
        "SG_EAST": "East",
        "SG_NORTH": "North",
        "SG_NORTH_EAST": "North-East",
        "SG_WEST_NORTH": "West",
        "SG_WEST_SOUTH": "West",
        "SG_SENTOSA": "Central",
    }
    pred_regions = Counter(LEGACY_TO_REGION.get(p.zone_id, p.zone_id) for p in link_preds)
    print("Prediction region distribution:")
    for r in ["Central","East","North","North-East","West"]:
        print(f"  {r}: {pred_regions.get(r,0)}")
except Exception as e:
    print(f"Prediction failed: {e}")
    import traceback
    traceback.print_exc()