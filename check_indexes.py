import sqlite3
conn = sqlite3.connect('data/traffic_observations.db')
cursor = conn.cursor()
cursor.execute('SELECT sql FROM sqlite_master WHERE type="index" AND tbl_name="traffic_observations"')
for row in cursor.fetchall():
    print(row[0])