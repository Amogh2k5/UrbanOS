import subprocess
import sys
import time
import requests

# Kill existing uvicorn
import os
os.system('taskkill /f /im python.exe 2>nul')

time.sleep(2)

# Start new server
proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000'], 
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
print('Server started, PID:', proc.pid)
time.sleep(5)

r = requests.get('http://localhost:8000/api/pollution/predict')
print('Status:', r.status_code)
d = r.json()
for x in d['regions']:
    print(f"  {x['region']}: mean={x['next_day_mean_ugm3']}, max={x['next_day_max_ugm3']}, model={x['model']}")

proc.terminate()