import os
from dotenv import load_dotenv
load_dotenv()
import sys
sys.path.insert(0, r"C:\projects\UrbanOS")
from backend.app.mobility.traffic.api import TrafficSpeedBandsV2ApiClient

api_key = os.getenv('LTA_API_KEY')
client = TrafficSpeedBandsV2ApiClient(api_key=api_key)
print("Fetching all pages...")
snapshot = client.fetch_all_pages()
print(f"Snapshot at: {snapshot.snapshot_at}")
print(f"Total segments: {len(snapshot.segments)}")
# unique link IDs
link_ids = set(seg.link_id for seg in snapshot.segments)
print(f"Unique LinkIDs: {len(link_ids)}")
# region mapping
LEGACY_TO_REGION = {
    "SG_CENTRAL_NORTH": "Central",
    "SG_CENTRAL_SOUTH": "Central",
    "SG_EAST": "East",
    "SG_NORTH": "North",
    "SG_NORTH_EAST": "North-East",
    "SG_WEST_NORTH": "West",
    "SG_WEST_SOUTH": "West",
    "SG_SENTOSA": "Central",
}
region_counts = {}
for seg in snapshot.segments:
    region = LEGACY_TO_REGION.get(seg.zone_id, seg.zone_id)
    region_counts[region] = region_counts.get(region, 0) + 1
print("Region distribution:")
for region in ["Central","East","North","North-East","West"]:
    print(f"  {region}: {region_counts.get(region, 0)}")
print(f"Total segments accounted: {sum(region_counts.values())}")