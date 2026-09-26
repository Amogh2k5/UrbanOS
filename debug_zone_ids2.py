import os
from dotenv import load_dotenv
load_dotenv()
import sys
sys.path.insert(0, r"C:\projects\UrbanOS")
from backend.app.mobility.traffic.api import TrafficSpeedBandsV2ApiClient

api_key = os.getenv('LTA_API_KEY')
client = TrafficSpeedBandsV2ApiClient(api_key=api_key)
print("Fetching first page only via client...")
snapshot = client.fetch_all_pages()
print(f"Total segments: {len(snapshot.segments)}")
# inspect first few segments zone_id
for seg in snapshot.segments[:20]:
    print(seg.zone_id)
# count unique zone_ids
zone_ids = set(seg.zone_id for seg in snapshot.segments)
print("Unique zone_ids:", zone_ids)