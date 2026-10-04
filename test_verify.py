import requests
import subprocess
import time
import sys

proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(15)

try:
    response = requests.get('http://localhost:8000/api/overview/module/traffic', timeout=60)
    print(f'Module traffic: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        summary = data.get("summary", "")
        print(f'  Summary: {summary[:150]}...')
        print(f'  Cross-domain: {data.get("cross_domain")}')
        print(f'  Alerts: {len(data.get("alerts", []))}')
    else:
        print(f'  Error: {response.text[:200]}')
        
    response = requests.post('http://localhost:8000/api/overview/chat', 
        json={'message': 'What is the current main city concern?', 'module_id': 'traffic'}, 
        timeout=60)
    print(f'\nChat: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        resp_text = data.get("response", "")
        print(f'  Response: {resp_text[:200]}')
    else:
        print(f'  Error: {response.text[:200]}')
except Exception as e:
    print(f'Error: {e}')
finally:
    proc.terminate()