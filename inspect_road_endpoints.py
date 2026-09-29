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

endpoints = [
    "RoadOpenings",
    "RoadWorks",
    "RoadWorksSchedule",
    "RoadHump",
    "TrafficLight",
    "RoadFacilities",
    "RoadSectionLine",
    "KerbLine",
    "LaneMarking",
    "TrafficLight",
    "TrafficSign",
    "VehicularBridgeFlyoverUnderpass",
    "PedestrianFacilities",
    "PedestrianOverheadbridgeUnderpass",
    "Railing",
    "RoadCrossing",
    "RoadHump",
    "SpeedRegulatingStrip",
    "StreetLighting",
    "StreetPaint",
    "TaxiStand",
]

for ep in [
    "RoadOpenings",
    "RoadWorks",
    "RoadWorksSchedule",
    "RoadHump",
    "TrafficLight",
    "RoadFacilities",
    "RoadSectionLine",
    "KerbLine",
    "LaneMarking",
    "TrafficLight",
    "TrafficSign",
    "VehicularBridgeFlyoverUnderpass",
    "PedestrianFacilities",
    "PedestrianOverheadbridgeUnderpass",
    "Railing",
    "RoadCrossing",
    "RoadHump",
    "SpeedRegulatingStrip",
    "StreetLighting",
    "StreetPaint",
    "TaxiStand",
]:
    url = f"https://datamall2.mytransport.sg/ltaodataservice/{ep}"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if "value" in data:
                print(f"{ep}: {len(data['value'])} records")
                if data['value']:
                    print(f"  First record keys: {list(data['value'][0].keys())}")
                    print(f"  First record: {data['value'][0]}")
            else:
                print(f"{ep}: OK - {data}")
        else:
            print(f"{ep}: {resp.status_code}")
    except Exception as e:
        print(f"{ep}: Error - {e}")