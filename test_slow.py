import subprocess
import time
import requests
import sys

proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(15)

try:
    response = requests.get('http://localhost:8000/health', timeout=5)
    print(f'Health: {response.status_code}')
    
    # First request might be slow due to traffic prediction service init
    print('Testing overview/city with 120s timeout...')
    response = requests.get('http://localhost:8000/api/overview/city', timeout=120)
    print(f'Overview city: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        print(f'  Modules: {len(data.get("modules", []))}')
        print(f'  Alerts: {len(data.get("alerts", []))}')
        print(f'  AI Brief: {data.get("ai_brief", "NONE")[:200]}...')
        for m in data.get('modules', []):
            kpi = m.get('kpi')
            kpi_str = f'{kpi["label"]}: {kpi["value"]} {kpi["unit"]}' if kpi else 'None'
            print(f'  - {m["id"]}: {m["status"]} KPI={kpi_str}')
    else:
        print(f'  Error: {response.text[:200]}')
except Exception as e:
    print(f'Error: {e}')
finally:
    proc.terminate()