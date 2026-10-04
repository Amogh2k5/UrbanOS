import subprocess
import time
import sys
import requests

proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(15)

print(f'Process alive: {proc.poll() is None}')

try:
    response = requests.get('http://localhost:8000/health', timeout=5)
    print(f'Health: {response.status_code}')
except Exception as e:
    print(f'Health Error: {e}')

try:
    response = requests.get('http://localhost:8000/api/overview/city', timeout=30)
    print(f'Overview: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        modules = data.get('modules', [])
        print(f'Modules: {len(modules)}')
except Exception as e:
    print(f'Overview Error: {e}')
finally:
    proc.terminate()