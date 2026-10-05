import asyncio
import sys
sys.path.insert(0, r'C:\projects\UrbanOS')

from backend.app.overview.api import _fetch_traffic_incidents, _fetch_fire_incidents, _fetch_flood_alerts, _fetch_transit_alerts, _fetch_road_events

async def test():
    traffic = await _fetch_traffic_incidents()
    fire = await _fetch_fire_incidents()
    flood = await _fetch_flood_alerts()
    transit = await _fetch_transit_alerts()
    roads = await _fetch_road_events()
    print(f'Traffic: {len(traffic)}')
    print(f'Fire: {len(fire)}')
    print(f'Flood: {len(flood)}')
    print(f'Transit: {len(transit)}')
    print(f'Roads: {len(roads)}')

asyncio.run(test())