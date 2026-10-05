import asyncio
import sys
sys.path.insert(0, r'C:\projects\UrbanOS')

from backend.app.overview.api import _fetch_road_events
from backend.app.overview.schemas import AlertItem

async def test():
    road_events = await _fetch_road_events()
    print(f'Road events: {len(road_events)}')
    for r in road_events:
        print(f'  {r}')
        try:
            alert = AlertItem(**r)
            print(f'  Created AlertItem: {alert}')
        except Exception as e:
            print(f'  ERROR creating AlertItem: {e}')

asyncio.run(test())