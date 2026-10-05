import subprocess
import time
import sys
import requests

proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(15)

try:
    response = requests.get('http://localhost:8000/api/overview/city', timeout=30)
    print(f'Status: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        print(f'Alerts count: {len(data.get("alerts", []))}')
        if data.get('alerts'):
            for a in data['alerts'][:3]:
                print(f'  - {a.get("domain")}: {a.get("title")[:50]}')
    else:
        print(f'Error: {response.text[:200]}')
except Exception as e:
    print(f'Error: {e}')
finally:
    proc.terminate()
    try:
        stdout, stderr = proc.communicate(timeout=5)
        print('=== STDOUT ===')
        print(stdout.decode()[-5000:])
        print('=== STDERR ===')
        print(stderr.decode()[-5000:])
    except:
        pass