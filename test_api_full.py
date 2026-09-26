import requests
import time
import json

base = "http://127.0.0.1:8000"

# Test /api/mobility/traffic/predict
print("=" * 60)
print("Testing /api/mobility/traffic/predict")
print("=" * 60)
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
        print(f"is_ml_model: {data.get('is_ml_model')}")
        print(f"source: {data.get('source')}")
        print(f"divisions count: {len(data.get('divisions', []))}")
        for d in data.get('divisions', []):
            print(f"  {d['division']}: current={d['current_avg_speed']}, predicted={d['predicted_avg_speed']}, change={d['speed_change']}, congestion={d['congestion_level']}, segments={d['segment_count']}")
        print(f"link_predictions count: {len(data.get('link_predictions', []))}")
    else:
        print(f"Error: {resp.text[:500]}")
except Exception as e:
    print(f"Exception: {e}")

print()

# Test /api/traffic/report
print("=" * 60)
print("Testing /api/traffic/report")
print("=" * 60)
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
        print(f"overall_predicted_speed: {data.get('overall_predicted_speed')}")
        print(f"overall_congestion_level: {data.get('overall_congestion_level')}")
        print(f"total incidents: {len(data.get('incidents', []))}")
        print(f"zones count: {len(data.get('zones', []))}")
        for z in data.get('zones', [])[:5]:
            print(f"  {z['zone_name']}: current={z['current_average_speed']}, predicted={z['predicted_average_speed']}, incidents={z['incident_count']}")
    else:
        print(f"Error: {resp.text[:500]}")
except Exception as e:
    print(f"Exception: {e}")