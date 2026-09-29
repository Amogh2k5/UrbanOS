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

# Check if there's pagination - test with \$skip and \$top
url = "https://datamall2.mytransport.sg/ltaodataservice/TaxiStands"
params = {"$top": 500, "$skip": 500}
try:
    resp = requests.get("https://datamall2.mytransport.sg/ltaodataservice/TaxiStands", 
                       headers={"AccountKey": os.getenv("LTA_API_KEY"), "accept": "application/json"},
                       params={"$top": 500, "$skip": 500}, timeout=10)
    print("Status:", resp.status_code)
    if resp.status_code == 200:
        data = resp.json()
        if "value" in data:
            print(f"TaxiStands (skip 500): {len(data['value'])} records")
            if data['value']:
                print('First:', data['value'][0])
        else:
            print(f'OK - {data}')
    else:
        print(f"Error: {resp.status_code}")
except Exception as e:
    print(f"Error: {e}")