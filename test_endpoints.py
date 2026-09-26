import subprocess
import time
import requests
import sys
import json

server_process = subprocess.Popen([
    sys.executable, "-m", "uvicorn", "backend.app.main:app", 
    "--host", "0.0.0.0", "--port", "8000"
], cwd=r"C:\projects\UrbanOS")

time.sleep(5)

base = "http://127.0.0.1:8000"

try:
    # Test predict endpoint
    print("Testing /api/mobility/traffic/predict...")
    start = time.time()
    resp = requests.get(f"{base}/api/mobility/traffic/predict", timeout=30)
    elapsed = time.time() - start
    print(f"HTTP {resp.status_code} in {elapsed:.3f}s")
    if resp.status_code == 200:
        data = resp.json()
        print(f"prediction_timestamp: {data.get('prediction_timestamp')}")
        print(f"target_timestamp: {data.get('target_timestamp')}")
        print(f"model: {data.get('model')}")
        print(f"is_ml_model: {data.get('is_ml_model')}")
        print(f"divisions: {len(data.get('divisions', []))}")
        for d in data.get('divisions', []):
            print(f"  {d['division']}: current={d['current_avg_speed']}, predicted={d['predicted_avg_speed']}, change={d['speed_change']}")
        
        # Verify link predictions
        links = data.get('link_predictions', [])
        print(f"\nlink_predictions count: {len(links)}")
        if links:
            # Check a few for sanity
            for lp in links[:5]:
                print(f"  link={lp['link_id']}: cur={lp['current_speed']:.2f}, pred={lp['predicted_speed']:.2f}, change={lp['speed_change']:.2f}")
                # Verify change = pred - cur
                assert abs(lp['speed_change'] - (lp['predicted_speed'] - lp['current_speed'])) < 0.01
    
    # Test report endpoint
    print("\nTesting /api/traffic/report...")
    start = time.time()
    resp = requests.get(f"{base}/api/traffic/report", timeout=30)
    elapsed = time.time() - start
    print(f"HTTP {resp.status_code} in {elapsed:.3f}s")
    if resp.status_code == 200:
        data = resp.json()
        print(f"generated_at: {data.get('generated_at')}")
        print(f"overall_status: {data.get('overall_status')}")
        print(f"overall_average_speed: {data.get('overall_average_speed')}")
        print(f"incidents: {len(data.get('incidents', []))}")
        print(f"zones: {len(data.get('zones', []))}")

finally:
    server_process.terminate()
    server_process.wait(timeout=5)