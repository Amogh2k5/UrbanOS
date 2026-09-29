import requests
import os
from dotenv import load_dotenv
load_dotenv()

import requests
import os
from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv("LTA_API_KEY")
headers = {"AccountKey": os.getenv("LTA_API_KEY"), "accept": "application/json"}

# Check default page size
resp = requests.get(
    "https://datamall2.mytransport.sg/ltaodataservice/TaxiStands",
    headers={"AccountKey": os.getenv("LTA_API_KEY"), "accept": "application/json"},
    timeout=10
)
print("Default page:")
if resp.status_code == 200:
    data = resp.json()
    if "value" in data:
        print(f"Default page: {len(data['value'])} records")
    else:
        print(f"OK - {data}")

# Check with \$top=1000
resp = requests.get(
    "https://datamall2.mytransport.sg/ltaodataservice/TaxiStands",
    headers={"AccountKey": os.getenv("LTA_API_KEY"), "accept": "application/json"},
    params={"$top": 1000},
    timeout=10
)
print("With \$top=1000:")
if resp.status_code == 200:
    data = resp.json()
    if "value" in data:
        print(f"With \$top=1000: {len(data['value'])} records")
    else:
        print(f"OK - {data}")
else:
    print(f"Error: {resp.status_code}")