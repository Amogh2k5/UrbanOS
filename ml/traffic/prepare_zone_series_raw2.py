import sqlite3
import pandas as pd
import numpy as np
from datetime import timezone, timedelta
import csv

SG_OFFSET = timezone(timedelta(hours=8))
DB_PATH = "data/traffic_observations.db"
OUT_CSV = "traffic/data/processed/zone_speed_series_raw.csv"

def get_full_timestamps():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT observed_at FROM (
            SELECT observed_at, COUNT(*) as cnt
            FROM traffic_observations
            GROUP BY observed_at
            HAVING cnt = 143787
        )
        ORDER BY observed_at
    """)
    ts = [r[0] for r in c.fetchall()]
    conn.close()
    return ts

def main():
    timestamps = get_full_timestamps()
    print(f"Full snapshots: {len(timestamps)}")
    print(f"Range: {timestamps[0]} -> {timestamps[-1]}")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    with open(OUT_CSV, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp','zone_id','avg_speed','min_speed','max_speed','link_count'])
    for idx, ts in enumerate(timestamps):
        c.execute("""
            SELECT zone_id,
                   AVG(speed_midpoint) as avg_speed,
                   MIN(speed_midpoint) as min_speed,
                   MAX(speed_midpoint) as max_speed,
                   COUNT(*) as link_count
            FROM traffic_observations
            WHERE observed_at = ?
              AND road_category IN (2,3,4,5,6)
              AND speed_midpoint BETWEEN 0 AND 120
              AND zone_id IS NOT NULL
            GROUP BY zone_id
        """, (ts,))
        rows = c.fetchall()
        with open(OUT_CSV, 'a', newline='') as f:
            writer = csv.writer(f)
            for r in rows:
                writer.writerow([ts, r[0], r[1], r[2], r[3], r[4]])
        if idx % 100 == 0:
            print(f"Processed {idx+1}/{len(timestamps)} timestamps")
    conn.close()
    print(f"Saved to {OUT_CSV}")

if __name__ == "__main__":
    main()