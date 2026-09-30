import sqlite3
import pandas as pd
import numpy as np
from datetime import timezone, timedelta
import csv

SG_OFFSET = timezone(timedelta(hours=8))
DB_PATH = "data/traffic_observations.db"
OUT_CSV = "traffic/data/processed/zone_speed_series_raw.csv"
BATCH_TS = 50  # timestamps per query

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

def fetch_zone_batch(timestamps, conn):
    placeholders = ','.join(['?']*len(timestamps))
    query = f"""
        SELECT observed_at, zone_id,
               AVG(speed_midpoint) as avg_speed,
               MIN(speed_midpoint) as min_speed,
               MAX(speed_midpoint) as max_speed,
               COUNT(*) as link_count
        FROM traffic_observations
        WHERE observed_at IN ({placeholders})
          AND road_category IN (2,3,4,5,6)
          AND speed_midpoint BETWEEN 0 AND 120
          AND zone_id IS NOT NULL
        GROUP BY observed_at, zone_id
    """
    df = pd.read_sql_query(query, conn, params=timestamps)
    return df

def main():
    timestamps = get_full_timestamps()
    print(f"Full snapshots: {len(timestamps)}")
    print(f"Range: {timestamps[0]} -> {timestamps[-1]}")

    conn = sqlite3.connect(DB_PATH)
    # Write header
    with open(OUT_CSV, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp','zone_id','avg_speed','min_speed','max_speed','link_count'])
    # Process batches
    for i in range(0, len(timestamps), BATCH_TS):
        batch = timestamps[i:i+BATCH_TS]
        df = fetch_zone_batch(batch, conn)
        df['observed_at'] = pd.to_datetime(df['observed_at']).dt.tz_convert(SG_OFFSET)
        # Append
        with open(OUT_CSV, 'a', newline='') as f:
            df.to_csv(f, header=False, index=False, columns=['observed_at','zone_id','avg_speed','min_speed','max_speed','link_count'])
        if (i//BATCH_TS) % 10 == 0:
            print(f"Processed {i+len(batch)}/{len(timestamps)} timestamps")
    conn.close()
    print(f"Saved to {OUT_CSV}")

if __name__ == "__main__":
    main()