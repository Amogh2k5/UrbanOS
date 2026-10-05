import subprocess
import time
import sys
import requests

proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(10)

try:
    import asyncio
    from backend.app.overview.api import _fetch_road_events
    from backend.app.overview.schemas import AlertItem
    
    async def test():
        road_events = await _fetch_road_events()
        print(f'Road events: {len(road_events)}')
        
        # Try to create AlertItem objects
        alerts = []
        for e in road_events:
            try:
                alert = AlertItem(**e)
                alerts.append(alert)
                print(f'Created AlertItem: {alert}')
            except Exception as e:
                print(f'Error creating AlertItem: {e}')
                print(f'  Data: {e}')
        
        print(f'Successfully created {len(alerts)} AlertItems')
    
    asyncio.run(test())
    
except Exception as e:
    print(f'Error: {e}')
finally:
    proc.terminate()