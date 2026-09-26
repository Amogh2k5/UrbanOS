import os, json
from dotenv import load_dotenv
load_dotenv()
import httpx

api_key = os.getenv('LTA_API_KEY')
headers = {'AccountKey': api_key, 'accept': 'application/json'}

# test first page
url = 'https://datamall2.mytransport.sg/ltaodataservice/v4/TrafficSpeedBands'
params1 = {'$top': 1000, '$skip': 0}
r1 = httpx.get('https://datamall2.mytransport.sg/ltaodataservice/v4/TrafficSpeedBands', params=params1, headers=headers, timeout=30)
print('Page1 status:', r1.status_code)
d1 = r1.json()
vals1 = d1.get('value', [])
print('Page1 records:', len(vals1))
ids1 = set(v['LinkID'] for v in vals1)
print('Page1 unique LinkIDs:', len(ids1))

# test second page
params2 = {'$top': 1000, '$skip': 1000}
r2 = httpx.get('https://datamall2.mytransport.sg/ltaodataservice/v4/TrafficSpeedBands', params=params2, headers=headers, timeout=30)
print('Page2 status:', r2.status_code)
d2 = r2.json()
vals2 = d2.get('value', [])
print('Page2 records:', len(vals2))
ids2 = set(v['LinkID'] for v in vals2)
print('Page2 unique LinkIDs:', len(ids2))

# compare
new_ids = ids2 - ids1
print('New LinkIDs in page2:', len(new_ids))
print('Overlap:', len(ids1 & ids2))

# also test skip=2000
params3 = {'$top': 1000, '$skip': 2000}
r3 = httpx.get('https://datamall2.mytransport.sg/ltaodataservice/v4/TrafficSpeedBands', params=params3, headers=headers, timeout=30)
print('Page3 status:', r3.status_code)
d3 = r3.json()
vals3 = d3.get('value', [])
print('Page3 records:', len(vals3))
ids3 = set(v['LinkID'] for v in vals3)
print('Page3 unique LinkIDs:', len(ids3))
print('New in page3:', len(ids3 - ids1 - ids2))
print('Total unique across 3 pages:', len(ids1 | ids2 | ids3))