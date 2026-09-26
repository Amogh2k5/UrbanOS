import sqlite3
import pandas as pd
import json

DB_PATH = "data/traffic_observations.db"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# Get latest observed_at
latest_ts = conn.execute('SELECT MAX(observed_at) FROM traffic_observations').fetchone()[0]
print(f"Latest observed_at: {latest_ts}")

# Count links in latest snapshot
rows = conn.execute('SELECT * FROM traffic_observations WHERE observed_at = ?', (latest_ts,)).fetchall()
print(f"Number of links in latest snapshot: {len(rows)}")

if len(rows) == 0:
    print("No data")
    exit()

# Convert to DataFrame
df = pd.DataFrame([dict(r) for r in rows])

# Basic info
print("\n--- Snapshot Info ---")
print(f"observed_at: {latest_ts}")
print(f"Total links: {len(df)}")
print(f"Unique road names: {df['road_name'].nunique()}")
print(f"Unique link_ids: {df['link_id'].nunique()}")

# Zone distribution
print("\n--- Zone ID Distribution ---")
zone_dist = df['zone_id'].value_counts()
print(zone_dist.to_string())

print("\n--- Zone Name Distribution ---")
zone_name_dist = df['zone_name'].value_counts()
print(zone_name_dist.to_string())

# Coordinate stats
print("\n--- Coordinate Stats ---")
for col in ['start_latitude', 'start_longitude', 'end_latitude', 'end_longitude']:
    if col in df.columns:
        vals = pd.to_numeric(df[col], errors='coerce')
        print(f"{col}: min={vals.min():.6f}, max={vals.max():.6f}, mean={vals.mean():.6f}, nulls={vals.isna().sum()}")

# Midpoint
df['mid_lat'] = (pd.to_numeric(df['start_latitude'], errors='coerce') + pd.to_numeric(df['end_latitude'], errors='coerce')) / 2
df['mid_lon'] = (pd.to_numeric(df['start_longitude'], errors='coerce') + pd.to_numeric(df['end_longitude'], errors='coerce')) / 2

print("\n--- Midpoint Stats ---")
print(f"mid_lat: min={df['mid_lat'].min():.6f}, max={df['mid_lat'].max():.6f}, mean={df['mid_lat'].mean():.6f}")
print(f"mid_lon: min={df['mid_lon'].min():.6f}, max={df['mid_lon'].max():.6f}, mean={df['mid_lon'].mean():.6f}")

# Unique coordinate pairs
start_pairs = df[['start_latitude','start_longitude']].dropna().drop_duplicates()
end_pairs = df[['end_latitude','end_longitude']].dropna().drop_duplicates()
mid_pairs = df[['mid_lat','mid_lon']].dropna().drop_duplicates()
print(f"\nUnique start coordinate pairs: {len(start_pairs)}")
print(f"Unique end coordinate pairs: {len(end_pairs)}")
print(f"Unique midpoint pairs: {len(mid_pairs)}")

# First/last 20 link IDs
print("\n--- First 20 link IDs ---")
print(df['link_id'].head(20).tolist())
print("\n--- Last 20 link IDs ---")
print(df['link_id'].tail(20).tolist())

# Road category distribution
print("\n--- Road Category Distribution ---")
print(df['road_category'].value_counts().to_string())

# Check if we have the planning regions geojson locally
import os
geojson_path = "backend/app/mobility/traffic/data/processed/singapore_planning_regions.geojson"
if os.path.exists(geojson_path):
    print(f"\nPlanning regions GeoJSON exists at {geojson_path}")
    with open(geojson_path) as f:
        gj = json.load(f)
    print(f"Feature count: {len(gj.get('features', []))}")
    for feat in gj.get('features', []):
        props = feat.get('properties', {})
        print(f"  region: {props.get('region') or props.get('name') or props.get('zone_name')}, zone_id: {props.get('zone_id')}")
else:
    print(f"\nPlanning regions GeoJSON NOT FOUND at {geojson_path}")

# Check old traffic zones geojson
old_geojson = "traffic/data/processed/singapore_traffic_zones.geojson"
if os.path.exists(old_geojson):
    print(f"\nOld traffic zones GeoJSON exists at {old_geojson}")
    with open(old_geojson) as f:
        gj = json.load(f)
    print(f"Feature count: {len(gj.get('features', []))}")
    for feat in gj.get('features', []):
        props = feat.get('properties', {})
        print(f"  zone_id: {props.get('zone_id')}, zone_name: {props.get('zone_name')}")
else:
    print(f"\nOld traffic zones GeoJSON NOT FOUND at {old_geojson}")

conn.close()