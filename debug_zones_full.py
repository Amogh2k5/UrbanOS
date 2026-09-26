import os
from dotenv import load_dotenv
load_dotenv()
import sys
sys.path.insert(0, r"C:\projects\UrbanOS")
from backend.app.mobility.traffic.api import TrafficSpeedBandsV2ApiClient

api_key = os.getenv('LTA_API_KEY')
client = TrafficSpeedBandsV2ApiClient(api_key=api_key)
print("Fetching all pages (first 5 pages for speed)...")
# We'll just fetch first few pages to inspect zone_ids
from backend.app.mobility.traffic.data import TrafficObservationCSVStore
store = TrafficObservationCSVStore()
# Actually let's just use client.fetch_all_pages but break early
import httpx
api_key = os.getenv('LTA_API_KEY')
headers = {'AccountKey': api_key, 'accept': 'application/json'}
url = 'https://datamall2.mytransport.sg/ltaodataservice/v4/TrafficSpeedBands'
page = 0
zone_ids_set = set()
while page < 5:
    skip = page * 500
    params = {'$top': 500, '$skip': skip}
    r = httpx.get('https://datamall2.mytransport.sg/ltaodataservice/v4/TrafficSpeedBands', params=params, headers=headers, timeout=30)
    d = r.json()
    vals = d.get('value', [])
    if not vals:
        break
    for v in vals:
        # get zone via midpoint using get_zone? But we can just see the raw fields: there is no zone_id in raw API.
        # The zone_id is assigned in _normalize_page using get_zone.
        # We'll just fetch first page with client to see zone_ids after normalization.
        pass
    page += 1