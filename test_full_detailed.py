import subprocess
import time
import requests
import sys

proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(15)

try:
    response = requests.get('http://localhost:8000/api/overview/city', timeout=60)
    print(f'Overview city: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        print(f'  AI Brief: {data.get("ai_brief", "NONE")[:200]}...')
        for m in data.get('modules', []):
            print(f'  - {m["id"]}: {m["status"]} KPI={m.get("kpi")}')
    else:
        print(f'  Error: {response.text[:200]}')
        
    # Check each module detail
    for module_id in ['traffic', 'roads', 'transit', 'pm25', 'weather', 'flood', 'fire']:
        response = requests.get(f'http://localhost:8000/api/overview/module/{module_id}', timeout=30)
        print(f'\nModule {module_id}: {response.status_code}')
        if response.status_code == 200:
            data = response.json()
            print(f'  Summary: {data.get("summary", "NONE")[:150]}...')
        else:
            print(f'  Error: {response.text[:200]}')

except Exception as e:
    print(f'Error: {e}')
finally:
    try:
        stdout, stderr = proc.communicate(timeout=5)
        print('\n=== BACKEND STDOUT ===')
        print(stdout.decode()[-3000:])
        print('\n=== BACKEND STDERR ===')
        print(stderr.decode()[-3000:])
    except:
        pass
    proc.terminate()