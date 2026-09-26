import requests
import time

base = "http://127.0.0.1:8000"

print("Testing /api/mobility/traffic/predict...")
start = time.time()
try:
    resp = requests.get(f"{base}/api/mobility/traffic/predict", timeout=30)
    elapsed = time.time() - start
    print(f"HTTP {resp.status_code} in {elapsed:.3f}s")
    if resp.status_code == 200:
        data = resp.json()
        print(f"prediction_timestamp: {data.get('prediction_timestamp')}")
        print(f"target_timestamp: {data.get('target_timestamp')}")
        print(f"model: {data.get('model')}")
        print(f"divisions: {len(data.get('divisions', []))}")
        for d in data.get('divisions', [])[:5]:
            print(f"  {d['division']}: current={d['current_avg_speed']}, predicted={d['predicted_avg_speed']}")
except Exception as e:
    print(f"Exception: {e}")

print()
print("Testing /api/traffic/report...")
start = time.time()
try:
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
except Exception as e:
    print(f"Exception: {e}")