import requests
import os
from dotenv import load_dotenv
load_dotenv()

import requests
import os
from dotenv import load_dotenv
load_dotenv()

headers = {"AccountKey": os.getenv("LTA_API_KEY"), "accept": "application/json"}

# Test pagination for RoadOpenings
url = "https://datamall2.mytransport.sg/ltaodataservice/RoadOpenings"
resp = requests.get(url, headers={"AccountKey": os.getenv("LTA_API_KEY"), "accept": "application/json"}, params={"$top": 1000}, timeout=10)
print("RoadOpenings with \$top=1000:")
if resp.status_code == 200:
    data = resp.json()
    if "value" in data:
        print(f"  Records with \$top=1000: {len(data['value'])}")
    else:
        print(f"  OK - {resp.json()}")
else:
    print(f"Error: {resp.status_code}")

# Check with skip
resp = requests.get("https://datamall2.mytransport.sg/ltaodataservice/RoadOpenings",
    headers={"AccountKey": os.getenv("LTA_API_KEY"), "accept": "application/json"},
    params={"$top": 500, "$skip": 500}, timeout=10)
print("With \$top=500 \$skip=500:")
if resp.status_code == 200:
    data = resp.json()
    if "value" in data:
        print(f"  Records with skip=500: {len(data['value'])}")
    else:
        print(f"  OK - {data}")
else:
    print(f"Error: {resp.status_code}")

# Also check RoadWorks
resp = requests.get("https://datamall2.mytransport.sg/ltaodataservice/RoadWorks",
    headers={"AccountKey": os.getenv("LTA_API_KEY"), "accept": "application/json"},
    params={"$top": 1000}, timeout=10)
print("\nRoadWorks with \$top=1000:")
if resp.status_code == 200:
    data = resp.json()
    if "value" in data:
        print(f"  Records with \$top=1000: {len(data['value'])}")
    else:
        print(f"  OK - {data}")
else:
    print(f"Error: {resp.status_code}")

resp = requests.get("https://datamall2.mytransport.sg/ltaodataservice/RoadWorks",
    headers={"AccountKey": os.getenv("LTA_API_KEY"), "accept": "application/json"},
    params={"$top": 500, "$skip": 500}, timeout=10)
print("RoadWorks with \$top=500 \$skip=500:")
if resp.status_code == 200:
    data = resp.json()
    if "value" in data:
        print(f"  Records with skip=500: {len(data['value'])}")
    else:
        print(f"  OK - {data}")
else:
    print(f"Error: {resp.status_code}")