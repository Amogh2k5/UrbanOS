import subprocess
import time
import requests
import sys
import threading
import json

# Start server in background
server_process = subprocess.Popen([
    sys.executable, "-m", "uvicorn", "backend.app.main:app", 
    "--host", "0.0.0.0", "--port", "8000"
], cwd=r"C:\projects\UrbanOS")

# Wait for server to start
print("Waiting for server to start...")
time.sleep(5)

base = "http://127.0.0.1:8000"

def test_endpoint(path, name):
    print(f"\n{'='*60}")
    print(f"Testing {name}")
    print(f"{'='*60}")
    start = time.time()
    try:
        resp = requests.get(f"{base}{path}", timeout=30)
        elapsed = time.time() - start
        print(f"HTTP {resp.status_code} in {elapsed:.3f}s")
        if resp.status_code == 200:
            data = resp.json()
            print(json.dumps(data, indent=2, default=str)[:3000])
            return elapsed, data
        else:
            print(f"Error: {resp.text[:500]}")
    except Exception as e:
        print(f"Exception: {e}")
    return None, None

try:
    test_endpoint("/api/mobility/traffic/predict", "/api/mobility/traffic/predict")
    test_endpoint("/api/traffic/report", "/api/traffic/report")
finally:
    server_process.terminate()
    server_process.wait(timeout=5)
    print("\nServer stopped.")