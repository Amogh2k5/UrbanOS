import subprocess
import time
import sys
import requests

proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(10)

try:
    response = requests.get('http://localhost:8000/api/overview/city', timeout=30)
    print(f'Status: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        print(f'AI Brief: {data.get("ai_brief")}')
        print(f'Alerts: {len(data.get("alerts", []))}')
    else:
        print(f'Error: {response.text[:200]}')
except Exception as e:
    print(f'Error: {e}')
finally:
    proc.terminate()
    try:
        stdout, stderr = proc.communicate(timeout=5)
        print('=== STDOUT ===')
        print(stdout.decode()[-3000:])
        print('=== STDERR ===')
        print(stderr.decode()[-3000:])
    except:
        pass