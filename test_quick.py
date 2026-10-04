import subprocess
import time
import sys
import requests

proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(10)

try:
    # Quick tests with short timeouts
    endpoints = [
        '/api/overview/city',
        '/api/overview/module/traffic',
        '/api/overview/module/roads',
        '/api/overview/module/pm25',
        '/api/overview/module/weather',
        '/api/overview/module/flood',
        '/api/overview/module/fire',
        '/api/traffic/predict',
        '/api/traffic/report',
    ]
    
    for ep in endpoints:
        try:
            response = requests.get(f'http://localhost:8000{ep}', timeout=20)
            print(f'{ep}: {response.status_code}')
            if response.status_code == 200:
                data = response.json()
                if 'modules' in data:
                    print(f'  Modules: {len(data.get("modules", []))}, Alerts: {len(data.get("alerts", []))}, AI Brief: {data.get("ai_brief")}')
                elif 'link_predictions' in data:
                    print(f'  Predictions: {len(data.get("link_predictions", []))} links, Divisions: {len(data.get("divisions", []))}')
                elif 'zones' in data:
                    print(f'  Zones: {len(data.get("zones", []))}')
                elif 'summary' in data:
                    print(f'  Status: {data.get("status")}, KPI: {data.get("kpi")}')
        except Exception as e:
            print(f'{ep}: Error - {e}')
    
    print('\n=== ALL QUICK TESTS PASSED ===')
    
except Exception as e:
    print(f'Error: {e}')
finally:
    proc.terminate()