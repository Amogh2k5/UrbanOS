import sqlite3
import pandas as pd
import numpy as np
from datetime import timezone, timedelta

SG_OFFSET = timezone(timedelta(hours=8))
DB_PATH = "data/traffic_observations.db"
OUT_CSV = "traffic/data/processed/zone_speed_series_day.csv"

def main():
    print("Running aggregated query for 2026-08-21...")
    conn = sqlite3.connect(DB_PATH)
    query = """
        SELECT observed_at, zone_id, AVG(speed_midpoint) as zone_avg_speed
        FROM traffic_observations
        WHERE road_category IN (2,3,4,5,6)
          AND speed_midpoint BETWEEN 0 AND 120
          AND zone_id IS NOT NULL
          AND date(observed_at) = '2026-08-21'
          AND observed_at IN (
              SELECT observed_at FROM (
                  SELECT observed_at, COUNT(*) as cnt
                  FROM traffic_observations
                  WHERE date(observed_at) = '2026-08-21'
                  GROUP BY observed_at
                  HAVING cnt = 143787
              )
          )
        GROUP BY observed_at, zone_id
        ORDER BY observed_at, zone_id
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    print(f"Rows: {len(df)}")
    df['observed_at'] = pd.to_datetime(df['observed_at']).dt.tz_convert(SG_OFFSET)

    wide = df.pivot(index='observed_at', columns='zone_id', values='zone_avg_speed')
    wide.columns.name = None
    print(f"Wide shape: {wide.shape}")

    regular_idx = pd.date_range(
        start=wide.index.min().floor('5min'),
        end=wide.index.max().ceil('5min'),
        freq='5min',
        tz=wide.index.tz
    )
    wide = wide.reindex(regular_idx)
    wide = wide.interpolate(method='time').ffill().bfill()
    print(f"Regularized shape: {wide.shape}")

    long = wide.reset_index().melt(id_vars='index', var_name='zone_id', value_name='zone_avg_speed')
    long = long.rename(columns={'index':'timestamp'})
    long.to_csv(OUT_CSV, index=False)
    print(f"Saved to {OUT_CSV}")

if __name__ == "__main__":
    main()