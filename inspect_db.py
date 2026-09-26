import sqlite3

conn = sqlite3.connect('data/traffic_observations.db')
cursor = conn.cursor()

# Check schema
cursor.execute('SELECT sql FROM sqlite_master WHERE type="table" AND name="traffic_observations"')
for row in cursor.fetchall():
    print("Schema:", row[0])

# Check columns
cursor.execute('PRAGMA table_info(traffic_observations)')
print("Columns:")
for row in cursor.fetchall():
    print(row)

# Check row count using MAX(rowid) - fast
cursor.execute('SELECT MAX(rowid) FROM traffic_observations')
print("Row count (MAX rowid):", cursor.fetchone()[0])

# Check date range
cursor.execute('SELECT MIN(observed_at), MAX(observed_at) FROM traffic_observations')
print("Date range:", cursor.fetchone())

# Sample a few rows
cursor.execute('SELECT * FROM traffic_observations LIMIT 5')
print("Sample rows:")
for row in cursor.fetchall():
    print(row)

conn.close()