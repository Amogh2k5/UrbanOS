#!/usr/bin/env python
"""
Export traffic observations for the latest snapshot's links - last 7 observations each.
This mimics what the predictor does, but runs ONCE at export time instead of at every prediction.
"""
import sqlite3
import csv
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

DB_PATH = Path("data/traffic_observations.db")
CSV_PATH = Path("data/traffic/traffic_observations.csv")

# Columns needed by TrafficPredictor
COLUMNS = [
    "observed_at", "link_id", "road_name", "road_category", "speed_band",
    "minimum_speed", "maximum_speed", "speed_midpoint",
    "start_latitude", "start_longitude", "end_latitude", "end_longitude",
    "zone_id", "zone_name"
]

def export_latest_snapshot_history():
    """Export last 7 observations for each link in the latest snapshot."""
    print(f"Opening database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. Get latest timestamp
    cursor.execute('SELECT MAX(observed_at) FROM traffic_observations')
    latest_ts = cursor.fetchone()[0]
    print(f"Latest timestamp: {latest_ts}")
    
    # 2. Get all link_ids in the latest snapshot (with their latest data)
    cursor.execute("""
        SELECT link_id, road_name, road_category, zone_id, zone_name
        FROM traffic_observations
        WHERE observed_at = ?
    """, (latest_ts,))
    
    latest_snapshot = cursor.fetchall()
    link_ids = [row['link_id'] for row in latest_snapshot]
    print(f"Links in latest snapshot: {len(link_ids)}")
    
    if not link_ids:
        print("No links in latest snapshot!")
        return
    
    # 3. For these link_ids, get last 7 observations each using window function
    # This is the same query as in predictor.py but run once for all links
    placeholders = ','.join('?' for _ in link_ids)
    query = f"""
        WITH ranked AS (
            SELECT {', '.join(COLUMNS)},
                   ROW_NUMBER() OVER (PARTITION BY link_id ORDER BY observed_at DESC) as rn
            FROM traffic_observations
            WHERE link_id IN ({placeholders})
        )
        SELECT {', '.join(COLUMNS)}
        FROM ranked
        WHERE rn <= 7
        ORDER BY link_id, observed_at DESC
    """
    
    print("Fetching last 7 observations per link using window function...")
    cursor = conn.execute(query, link_ids)
    
    rows = []
    for row in cursor:
        rows.append([row[col] for col in COLUMNS])
    
    print(f"Fetched {len(rows):,} total observations")
    
    # 4. Write to CSV
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    
    print(f"Export complete! Written {len(rows):,} rows to {CSV_PATH}")
    print(f"CSV size: {CSV_PATH.stat().st_size / (1024**2):.1f} MB")
    
    # Verify
    by_link = defaultdict(list)
    for row in rows:
        by_link[row[1]].append(row)
    
    print(f"Unique link_ids in CSV: {len(by_link)}")
    obs_counts = [len(v) for v in by_link.values()]
    print(f"Observations per link: min={min(obs_counts)}, max={max(obs_counts)}, avg={sum(obs_counts)/len(obs_counts):.1f}")
    links_with_7plus = sum(1 for c in obs_counts if c >= 7)
    print(f"Links with >=7 observations: {links_with_7plus}/{len(obs_counts)}")
    
    # Sample
    print("\nSample (first 3 links):")
    for link_id, obs_list in list(by_link.items())[:3]:
        print(f"  Link {link_id}: {len(obs_list)} observations")
        for i, obs in enumerate(obs_list[:7]):
            print(f"    {i+1}. {obs[0]} speed_midpoint={obs[7]}")
    
    conn.close()

if __name__ == "__main__":
    export_latest_snapshot_history()