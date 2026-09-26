import os
from dotenv import load_dotenv
load_dotenv()
import httpx

api_key = os.getenv('LTA_API_KEY')
headers = {'AccountKey': api_key, 'accept': 'application/json'}

url = 'https://datamall2.mytransport.sg/ltaodataservice/v4/TrafficSpeedBands'
all_ids = set()
page = 0
page_size = 1000
max_pages = 20  # safety limit

while page < max_pages:
    skip = page * 1000
    params = {'$top': 1000, '$skip': skip}
    r = httpx.get('https://datamall2.mytransport.sg/ltaodataservice/v4/TrafficSpeedBands', params=params, headers=headers, timeout=30)
    print(f'Page {page} (skip={skip}) status: {r.status_code}')
    d = r.json()
    vals = d.get('value', [])
    print(f'  records: {len(vals)}')
    if not vals:
        print('  No more records, stopping.')
        break
    ids = set(v['LinkID'] for v in vals)
    new_ids = ids - all_ids
    print(f'  new unique LinkIDs: {len(new_ids)}')
    all_ids.update(ids)
    if len(new_ids) == 0:
        print('  No new IDs, stopping.')
        break
    page += 1

print(f'\nTotal unique LinkIDs collected: {len(all_ids)}')