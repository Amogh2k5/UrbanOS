import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env
load_dotenv(Path(__file__).parent / ".env")

print("Environment variables loaded:")
print(f"  LTA_ACCOUNT_KEY: {'YES' if os.getenv('LTA_ACCOUNT_KEY') else 'NO'}")
print(f"  LTA_API_KEY: {'YES' if os.getenv('LTA_API_KEY') else 'NO'}")

# Now test the collector
import sys
sys.path.insert(0, str(Path(__file__).parent))

from backend.app.mobility.traffic.data import collect_traffic_once

print("\nRunning manual collection...")
result = collect_traffic_once()
print(f"Timestamp: {result.timestamp}")
print(f"Records received: {result.records_received}")
print(f"Records stored: {result.records_stored}")
print(f"Records updated: {result.records_updated}")
print(f"Zones mapped: {result.zones_mapped}")
print(f"Zones unmapped: {result.zones_unmapped}")
print(f"Errors: {result.errors}")