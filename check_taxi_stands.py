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

# Check TaxiStands in detail
url = f"https://datamall2.mytransport.sg/ltaodataservice/TaxiStands"
try:
    resp = requests.get(url, headers={"AccountKey": os.getenv("LTA_API_KEY"), "accept": "application/json"}, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        if "value" in data:
            print(f"TaxiStands: {len(data['value'])} records")
            if data['value']:
                print("First record keys:", list(data['value'][0].keys()))
                print("First record:", data['value'][0])
                print("...")
                print("Last record:", data['value'][-1])
        else:
            print(f"TaxiStands: OK - {data}")
    else:
        print(f"TaxiStands: {resp.status_code}")
except Exception as e:
    print(f"TaxiStands: Error - {e}")