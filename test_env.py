import subprocess
import time
import sys
import os
import requests

# Kill any existing uvicorn
subprocess.run(['taskkill', '/F', '/IM', 'uvicorn.exe'], capture_output=True)
time.sleep(2)

proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000', '--reload'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, 'PYTHONPATH': r'C:\projects\UrbanOS'})
time.sleep(15)

try:
    response = requests.get('http://localhost:8000/api/overview/city', timeout=30)
    print(f'Status: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        print(f'Modules: {len(data.get("modules", []))}')
        ai_brief = data.get("ai_brief", "NONE")
        print(f'AI Brief: {ai_brief[:100]}...')
except Exception as e:
    print(f'Error: {e}')
finally:
    proc.terminate()
    try:
        stdout, stderr = proc.communicate(timeout=5)
        print('STDOUT:')
        print(stdout.decode()[-3000:])
        print('STDERR:')
        print(stderr.decode()[-3000:])
    except:
        pass