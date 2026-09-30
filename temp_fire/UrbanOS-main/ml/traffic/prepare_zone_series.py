import sqlite3
import pandas as pd
import numpy as np
from datetime import timezone, timedelta

SG_OFFSET = timezone(timedelta(hours=8))
DB_PATH = "data/traffic_observations.db"
OUT_CSV = "traffic/data/processed/zone_speed_series.csv"

CHUNK_TIMESTAMPS = 50  # how many timestamps per query

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

def fetch_zone_averages(timestamps):
    """Return DataFrame with columns observed_at, zone_id, zone_avg_speed"""
    all_dfs = []
    conn = sqlite3.connect(DB_PATH)
    for i in range(0, len(timestamps), CHUNK_TIMESTAMPS):
        chunk = timestamps[i:i+CHUNK_TIMESTAMPS]
        placeholders = ','.join(['?']*len(chunk))
        query = f"""
            SELECT observed_at, zone_id, AVG(speed_midpoint) as zone_avg_speed
            FROM traffic_observations
            WHERE observed_at IN ({placeholders})
              AND road_category IN (2,3,4,5,6)
              AND speed_midpoint BETWEEN 0 AND 120
              AND zone_id IS NOT NULL
            GROUP BY observed_at, zone_id
        """
        df = pd.read_sql_query(query, conn, params=chunk)
        all_dfs.append(df)
    conn.close()
    return pd.concat(all_dfs, ignore_index=True)

def main():
    print("Getting full snapshot timestamps...")
    timestamps = get_full_timestamps()
    print(f"Found {len(timestamps)} full snapshots")
    print(f"Range: {timestamps[0]} -> {timestamps[-1]}")

    print("Fetching zone averages...")
    df = fetch_zone_averages(timestamps)
    print(f"Rows: {len(df)}")
    df['observed_at'] = pd.to_datetime(df['observed_at']).dt.tz_convert(SG_OFFSET)

    # Pivot to wide
    wide = df.pivot(index='observed_at', columns='zone_id', values='zone_avg_speed')
    wide.columns.name = None
    print(f"Wide shape: {wide.shape}")

    # Create regular 5-min grid covering range
    regular_idx = pd.date_range(
        start=wide.index.min().floor('5min'),
        end=wide.index.max().ceil('5min'),
        freq='5min',
        tz=wide.index.tz
    )
    wide = wide.reindex(regular_idx)
    # Interpolate missing (time-aware)
    wide = wide.interpolate(method='time').ffill().bfill()
    print(f"Regularized shape: {wide.shape}")

    # Save long format
    long = wide.reset_index().melt(id_vars='index', var_name='zone_id', value_name='zone_avg_speed')
    long = long.rename(columns={'index':'timestamp'})
    long.to_csv(OUT_CSV, index=False)
    print(f"Saved to {OUT_CSV}")

if __name__ == "__main__":
    main()