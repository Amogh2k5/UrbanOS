import os
from dotenv import load_dotenv
load_dotenv()
import sys
sys.path.insert(0, r"C:\projects\UrbanOS")
from backend.app.mobility.traffic.api import TrafficSpeedBandsV2ApiClient

api_key = os.getenv('LTA_API_KEY')
client = TrafficSpeedBandsV2ApiClient(api_key=api_key)
print("Fetching first page only...")
from backend.app.mobility.traffic.data import TrafficObservationCSVStore
store = TrafficObservationCSVStore()
latest_snapshot = store.get_latest_snapshot(limit=10)
print(f"Latest snapshot links: {len(latest_snapshot)}")
for obs in latest_snapshot[:10]:
    print(f"link_id={obs.link_id}, zone_id={obs.zone_id}, zone_name={obs.zone_name}")