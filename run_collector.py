import os
from dotenv import load_dotenv
load_dotenv()
import sys
sys.path.insert(0, r"C:\projects\UrbanOS")
import time
from backend.app.mobility.traffic.data import collect_traffic_once

print("Starting collector...")
start = time.time()
result = collect_traffic_once()
elapsed = time.time() - start
print(f"Collection completed in {elapsed:.2f}s")
print(f"Result: {result}")