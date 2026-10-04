import subprocess
import time
import requests
import sys

proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(60)

try:
    response = requests.get('http://localhost:8000/api/overview/city', timeout=180)
    print(f'Overview city: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        ai_brief = data.get("ai_brief", "NONE")
        print(f'  AI Brief: {ai_brief[:200]}...')
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