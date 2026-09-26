import subprocess
import sys
import time
import requests
import json
import os
import signal

# Kill any existing uvicorn
os.system('taskkill /f /im python.exe 2>nul')
time.sleep(2)

# Start server
proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000'],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
print('Server started, PID:', proc.pid)
time.sleep(6)  # wait for startup

try:
    r = requests.get('http://localhost:8000/api/pollution/predict', timeout=10)
    print('Status:', r.status_code)
    print('Response:', json.dumps(r.json(), indent=2))
except Exception as e:
    print('Request error:', e)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except:
        proc.kill()