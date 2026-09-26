import os
from dotenv import load_dotenv
load_dotenv()

import sys
sys.path.insert(0, '.')
from backend.app.mobility.traffic.data import collect_traffic_once

try:
    result = collect_traffic_once()
    print('Collection result:')
    print(f'  timestamp: {result.timestamp}')
    print(f'  records_received: {result.records_received}')
    print(f'  records_stored: {result.records_stored}')
    print(f'  records_updated: {result.records_updated}')
    print(f'  zones_mapped: {result.zones_mapped}')
    print(f'  zones_unmapped: {result.zones_unmapped}')
    print(f'  errors: {result.errors}')
except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc()