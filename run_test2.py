import subprocess, time, requests, json, sys, os, signal

proc = subprocess.Popen([
    sys.executable, "-m", "uvicorn", "backend.app.main:app",
    "--host", "0.0.0.0", "--port", "8001"
], cwd=r"C:\projects\UrbanOS", stdout=subprocess.PIPE, stderr=subprocess.PIPE)

time.sleep(5)

try:
    r = requests.get('http://127.0.0.1:8001/api/mobility/traffic/predict', timeout=30)
    print('Status:', r.status_code)
    data = r.json()
    # print only divisions
    print('DIVISIONS:')
    print(json.dumps(data.get('divisions', []), indent=2))
except Exception as e:
    print('Error:', e)
finally:
    proc.terminate()
    proc.wait(timeout=5)