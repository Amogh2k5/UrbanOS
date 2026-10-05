import subprocess
import time
import sys
import requests

proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(10)

try:
    # Test each alert source individually through the API
    sources = [
        ('traffic', '/api/overview/city'),  # This tests all
    ]
    
    # Check if road events work
    import asyncio
    from backend.app.overview.api import _fetch_road_events
    
    async def test():
        road_events = await _fetch_road_events()
        print(f'Road events: {len(road_events)}')
        for e in road_events:
            print(f'  {e}')
    
    import asyncio
    asyncio.run(test())
    
except Exception as e:
    print(f'Error: {e}')
finally:
    proc.terminate()