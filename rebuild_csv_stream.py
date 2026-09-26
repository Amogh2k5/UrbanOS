import sqlite3
import csv
import os
import sys
from pathlib import Path

DB = Path(r"C:\projects\UrbanOS\data\traffic_observations.db")
CSV_TMP = Path(r"C:\projects\UrbanOS\data\traffic\traffic_observations.csv.tmp")
CSV = Path(r"C:\projects\UrbanOS\data\traffic\traffic_observations.csv")
CHUNK = 50000

SQL = """
WITH ranked AS (
    SELECT
        observed_at, link_id, road_name, road_category, speed_band,
        minimum_speed, maximum_speed, speed_midpoint,
        start_latitude, start_longitude, end_latitude, end_longitude,
        zone_id, zone_name,
        ROW_NUMBER() OVER (PARTITION BY link_id ORDER BY observed_at DESC) AS rn
    FROM traffic_observations
)
SELECT
    observed_at, link_id, road_name, road_category, speed_band,
    minimum_speed, maximum_speed, speed_midpoint,
    start_latitude, start_longitude, end_latitude, end_longitude,
    zone_id, zone_name
FROM ranked
WHERE rn <= 7
ORDER BY observed_at, link_id;
"""

def main():
    CSV.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "observed_at","link_id","road_name","road_category","speed_band",
        "minimum_speed","maximum_speed","speed_midpoint",
        "start_latitude","start_longitude","end_latitude","end_longitude",
        "zone_id","zone_name"
    ]

    with sqlite3.connect(DB) as con, open(CSV_TMP, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["observed_at","link_id","road_name","road_category","speed_band",
                         "minimum_speed","maximum_speed","speed_midpoint",
                         "start_latitude","start_longitude","end_latitude","end_longitude",
                         "zone_id","zone_name"])
        cur = con.execute("""
            WITH ranked AS (
                SELECT observed_at, link_id, road_name, road_category, speed_band,
                       minimum_speed, maximum_speed, speed_midpoint,
                       start_latitude, start_longitude, end_latitude, end_longitude,
                       zone_id, zone_name,
                       ROW_NUMBER() OVER (PARTITION BY link_id ORDER BY observed_at DESC) AS rn
                FROM traffic_observations
            )
            SELECT observed_at, link_id, road_name, road_category, speed_band,
                   minimum_speed, maximum_speed, speed_midpoint,
                   start_latitude, start_longitude, end_latitude, end_longitude,
                   zone_id, zone_name
            FROM ranked
            WHERE rn <= 7
            ORDER BY observed_at, link_id;
        """)

        chunk = []
        total = 0
        for row in cur:
            chunk.append(row)
            if len(chunk) >= 50000:
                writer.writerows(chunk)
                chunk.clear()
        if chunk:
            writer.writerows(chunk)

    # atomic replace
    os.replace(CSV_TMP, CSV)
    print("✅ CSV rebuilt")

if __name__ == "__main__":
    main()