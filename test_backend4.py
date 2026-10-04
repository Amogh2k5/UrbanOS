import subprocess
import time
import requests
import sys

# Run uvicorn with output visible
proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000', '--log-level', 'debug'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# Wait for startup
time.sleep(15)

try:
    # Read some output
    try:
        stdout, stderr = proc.communicate(timeout=2)
        print(f'Process exited: {proc.returncode}')
        print(f'STDOUT: {stdout.decode()[-3000:]}')
        print(f'STDERR: {stderr.decode()[-3000:]}')
    except subprocess.TimeoutExpired:
        print('Process still running, testing endpoints...')
        
        response = requests.get('http://localhost:8000/health', timeout=5)
        print(f'Health: {response.status_code} - {response.json()}')
        
        response = requests.get('http://localhost:8000/api/overview/city', timeout=60)
        print(f'Overview city: {response.status_code}')
        if response.status_code == 200:
            data = response.json()
            print(f'  Modules: {len(data.get("modules", []))}')
            print(f'  Alerts: {len(data.get("alerts", []))}')
            print(f'  AI Brief: {data.get("ai_brief", "NONE")[:100]}...')
        else:
            print(f'  Error: {response.text[:200]}')
except Exception as e:
    print(f'Error: {e}')
finally:
    proc.terminate()