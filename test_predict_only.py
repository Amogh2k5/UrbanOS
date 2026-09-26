import subprocess
import time
import requests
import sys
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

# Test predict endpoint only
print(f"\n{'='*60}")
print(f"Testing /api/mobility/traffic/predict")
print(f"{'='*60}")
start = time.time()
try:
    resp = requests.get(f"{base}/api/mobility/traffic/predict", timeout=60)
    elapsed = time.time() - start
    print(f"HTTP {resp.status_code} in {elapsed:.3f}s")
    if resp.status_code == 200:
        data = resp.json()
        print(json.dumps(data, indent=2, default=str)[:5000])
    else:
        print(f"Error: {resp.text[:1000]}")
except Exception as e:
    print(f"Exception: {e}")

server_process.terminate()
server_process.wait(timeout=5)
print("\nServer stopped.")