import os
import sys
sys.path.insert(0, r"C:\projects\UrbanOS")
from backend.app.mobility.traffic.data import TrafficObservationStore
from pathlib import Path

db_path = Path("data/traffic_observations.db")
csv_path = Path("data/traffic/traffic_observations.csv")

store = TrafficObservationStore(db_path)
print("Exporting to CSV...")
store.export_latest_seven_per_link(csv_path)
print("Done.")