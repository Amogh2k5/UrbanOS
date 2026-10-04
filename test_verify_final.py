import subprocess
import time
import sys
import requests

proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(15)

try:
    response = requests.get('http://localhost:8000/api/overview/city', timeout=60)
    print(f'/api/overview/city: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        print(f'  Modules: {len(data.get("modules", []))}')
        ai_brief = data.get("ai_brief", "NONE")
        print(f'  AI Brief: {ai_brief[:100]}...')
except Exception as e:
    print(f'Error: {e}')
finally:
    proc.terminate()