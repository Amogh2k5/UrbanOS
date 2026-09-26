import sqlite3
from pathlib import Path

DB_PATH = Path("data/traffic_observations.db")

conn = sqlite3.connect(DB_PATH, timeout=60)
cursor = conn.cursor()

# Get latest timestamp
cursor.execute('SELECT MAX(observed_at) FROM traffic_observations')
latest = cursor.fetchone()[0]
print(f"DB latest observed_at: {latest}")

# Get min timestamp
cursor.execute('SELECT MIN(observed_at) FROM traffic_observations')
earliest = cursor.fetchone()[0]
print(f"DB earliest observed_at: {earliest}")

# Count total rows
cursor.execute('SELECT MAX(rowid) FROM traffic_observations')
total = cursor.fetchone()[0]
print(f"DB total rows (MAX rowid): {total:,}")

# Count unique links in latest snapshot
cursor.execute('SELECT COUNT(DISTINCT link_id) FROM traffic_observations WHERE observed_at = ?', (latest,))
unique_latest = cursor.fetchone()[0]
print(f"Unique link_ids in latest snapshot: {unique_latest}")

conn.close()