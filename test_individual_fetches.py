import asyncio
import sys
sys.path.insert(0, r'C:\projects\UrbanOS')

from backend.app.overview.api import _fetch_road_events, _fetch_transit_alerts

async def test():
    print("Testing _fetch_road_events...")
    result = await _fetch_road_events()
    print(f"Road events: {len(result)}")
    for r in result:
        print(f"  {r}")
    
    print("Testing _fetch_transit_alerts...")
    result = await _fetch_transit_alerts()
    print(f"Transit alerts: {len(result)}")

asyncio.run(test())