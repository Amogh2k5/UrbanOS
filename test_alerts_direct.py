import subprocess
import time
import sys
import requests

proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(10)

try:
    import asyncio
    # Test each alert source directly
    from backend.app.overview.api import (
        _fetch_traffic_incidents, _fetch_fire_incidents, 
        _fetch_flood_alerts, _fetch_road_events, _fetch_transit_alerts
    )
    
    async def test_alerts():
        traffic = await _fetch_traffic_incidents()
        fire = await _fetch_fire_incidents()
        flood = await _fetch_flood_alerts()
        roads = await _fetch_road_events()
        transit = await _fetch_transit_alerts()
        
        print(f"Traffic incidents: {len(traffic)}")
        if traffic:
            print(f"  Sample: {traffic[0]}")
        print(f"Fire incidents: {len(fire)}")
        if fire:
            print(f"  Sample: {fire[0]}")
        print(f"Flood alerts: {len(flood)}")
        if flood:
            print(f"  Sample: {flood[0]}")
        print(f"Road events: {len(roads)}")
        if roads:
            print(f"  Sample: {roads[0]}")
        print(f"Transit alerts: {len(transit)}")
        if transit:
            print(f"  Sample: {transit[0]}")
    
    asyncio.run(test_alerts())

except Exception as e:
    print(f'Error: {e}')
finally:
    proc.terminate()