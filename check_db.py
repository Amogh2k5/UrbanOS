import sqlite3
conn = sqlite3.connect('data/traffic_observations.db', timeout=120)
cursor = conn.cursor()
cursor.execute('SELECT sql FROM sqlite_master WHERE type="table" AND name="traffic_observations"')
print('Schema:', cursor.fetchone()[0])
cursor.execute('SELECT COUNT(*) FROM traffic_observations')
print('Total rows:', cursor.fetchone()[0])