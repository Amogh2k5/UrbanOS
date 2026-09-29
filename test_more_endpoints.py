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

# Try variations of endpoint names
endpoints_to_try = [
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

# Also try with different suffixes
all_endpoints = set([
    "RoadOpenings", "RoadWorks", "RoadWorksSchedule", "RoadHump", "TrafficLight",
    "RoadFacilities", "RoadSectionLine", "KerbLine", "LaneMarking", "TrafficLight",
    "TrafficSign", "VehicularBridgeFlyoverUnderpass", "PedestrianFacilities",
    "PedestrianOverheadbridgeUnderpass", "Railing", "RoadCrossing", "RoadHump",
    "SpeedRegulatingStrip", "StreetLighting", "StreetPaint", "TaxiStand",
    "RoadOpening", "RoadWork", "RoadWorkSchedule", "RoadHump",
    "TrafficLights", "RoadFacility", "RoadSection", "Kerb", "Lane",
    "TrafficSign", "VehicularBridge", "Pedestrian", "Overheadbridge",
    "Railings", "Crossing", "Hump", "SpeedStrip", "StreetLight", "StreetPaint", "TaxiStands",
])

all_endpoints = list(set([
    "RoadOpenings", "RoadWorks", "RoadWorksSchedule", "RoadHump", "TrafficLight",
    "RoadFacilities", "RoadSectionLine", "KerbLine", "LaneMarking", "TrafficLight",
    "TrafficSign", "VehicularBridgeFlyoverUnderpass", "PedestrianFacilities",
    "PedestrianOverheadbridgeUnderpass", "Railing", "RoadCrossing", "RoadHump",
    "SpeedRegulatingStrip", "StreetLighting", "StreetPaint", "TaxiStand",
    "RoadOpening", "RoadWork", "RoadWorkSchedule", "RoadHump",
    "TrafficLights", "RoadFacility", "RoadSection", "Kerb", "Lane",
    "TrafficSign", "VehicularBridge", "Pedestrian", "Overheadbridge",
    "Railings", "Crossing", "Hump", "SpeedStrip", "StreetLight", "StreetPaint", "TaxiStands",
]))

print("Testing all endpoint variations...")
for ep in sorted(all_endpoints):
    url = f"https://datamall2.mytransport.sg/ltaodataservice/{ep}"
    try:
        resp = requests.get(url, headers={"AccountKey": os.getenv("LTA_API_KEY"), "accept": "application/json"}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if "value" in data:
                print(f'{ep}: {len(data["value"])} records')
            else:
                print(f'{ep}: OK - {data}')
        elif resp.status_code != 404:
            print(f'{ep}: {resp.status_code}')
    except Exception as e:
        print(f'{ep}: Error - {e}')