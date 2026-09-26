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
time.sleep(3)

base = "http://127.0.0.1:8000"

# Test predict endpoint
print("Testing /api/mobility/traffic/predict...")
try:
    resp = requests.get(f"{base}/api/mobility/traffic/predict", timeout=30)
    print(f"HTTP {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"prediction_timestamp: {data.get('prediction_timestamp')}")
        print(f"divisions: {len(data.get('divisions', []))}")
except Exception as e:
    print(f"Exception: {e}")

# Test report endpoint
print("\nTesting /api/traffic/report...")
try:
    resp = requests.get(f"{base}/api/traffic/report", timeout=30)
    print(f"HTTP {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"generated_at: {data.get('generated_at')}")
        print(f"overall_status: {data.get('overall_status')}")
        print(f"overall_average_speed: {data.get('overall_average_speed')}")
        print(f"incidents: {len(data.get('incidents', []))}")
except Exception as e:
    print(f"Exception: {e}")

server_process.terminate()
server_process.wait(timeout=5)
print("\nServer stopped.")