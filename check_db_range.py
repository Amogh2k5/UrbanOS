import sqlite3

conn = sqlite3.connect('data/traffic_observations.db', timeout=60)
cursor = conn.cursor()

# Get min/max using indexes (should be fast)
cursor.execute('SELECT MIN(observed_at) FROM traffic_observations')
min_ts = cursor.fetchone()[0]
print("Min timestamp:", min_ts)

cursor.execute('SELECT MAX(observed_at) FROM traffic_observations')
max_ts = cursor.fetchone()[0]
print("Max timestamp:", max_ts)

# Count total rows using MAX(rowid) - fast
cursor.execute('SELECT MAX(rowid) FROM traffic_observations')
print("Total rows (MAX rowid):", cursor.fetchone()[0])

conn.close()