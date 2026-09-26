import subprocess
import sys
import time
import requests
import json
import os

# Kill any existing uvicorn
os.system('taskkill /f /im python.exe 2>nul')
time.sleep(2)

# Start server
proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000'],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
print('Server started, PID:', proc.pid)

# Read a few lines of startup
for _ in range(10):
    line = proc.stdout.readline()
    if line:
        print('SERVER:', line.rstrip())
    time.sleep(0.5)

time.sleep(3)

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
    # print remaining output
    for line in proc.stdout:
        print('SERVER:', line.rstrip())