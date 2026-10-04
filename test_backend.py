import subprocess
import time
import requests
import sys

proc = subprocess.Popen([sys.executable, '-m', 'backend.app.main'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(10)

try:
    response = requests.get('http://localhost:8000/health', timeout=5)
    print(f'Health: {response.status_code} - {response.json()}')
    
    response = requests.get('http://localhost:8000/api/overview/city', timeout=60)
    print(f'Overview city: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        print(f'  Modules: {len(data.get("modules", []))}')
        print(f'  Alerts: {len(data.get("alerts", []))}')
        print(f'  AI Brief: {data.get("ai_brief", "NONE")[:100]}...')
        for m in data.get('modules', []):
            kpi = m.get('kpi')
            kpi_str = f'{kpi["label"]}: {kpi["value"]} {kpi["unit"]}' if kpi else 'None'
            print(f'  - {m["id"]}: {m["status"]} KPI={kpi_str}')
    else:
        print(f'  Error: {response.text[:200]}')
        
    # Test module detail
    response = requests.get('http://localhost:8000/api/overview/module/traffic', timeout=30)
    print(f'\\nModule traffic: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        print(f'  Status: {data.get("status")}')
        print(f'  Summary: {data.get("summary")[:100]}...')
        print(f'  Cross-domain: {data.get("cross_domain")}')
        print(f'  Alerts: {len(data.get("alerts", []))}')
    else:
        print(f'  Error: {response.text[:200]}')
        
    # Test chat
    response = requests.post('http://localhost:8000/api/overview/chat', 
        json={'message': 'What is the current main city concern?', 'module_id': 'traffic'}, 
        timeout=30)
    print(f'\\nChat: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        print(f'  Response: {data.get("response")[:200]}')
    else:
        print(f'  Error: {response.text[:200]}')

except Exception as e:
    print(f'Error: {e}')
finally:
    proc.terminate()