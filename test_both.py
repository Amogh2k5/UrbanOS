import requests
import time

# Wait for server to be ready
time.sleep(2)

# Test /api/mobility/traffic/predict
print("Testing /api/mobility/traffic/predict...")
start = time.time()
try:
    resp = requests.get('http://127.0.0.1:8000/api/mobility/traffic/predict', timeout=30)
    elapsed = time.time() - start
    print(f'Status: {resp.status_code}')
    print(f'Time: {elapsed:.2f}s')
    if resp.status_code == 200:
        data = resp.json()
        model = data.get("model")
        is_ml = data.get("is_ml_model")
        divisions = data.get("divisions", [])
        print(f'Model: {model}')
        print(f'Is ML: {is_ml}')
        print(f'Divisions: {len(divisions)}')
        for d in divisions[:5]:
            div = d.get("division")
            curr = d.get("current_avg_speed")
            pred = d.get("predicted_avg_speed")
            print(f'  {div}: current={curr}, predicted={pred}')
    else:
        print(f'Error: {resp.text[:500]}')
except Exception as e:
    print(f'Exception: {e}')

print()

# Test /api/traffic/report
print("Testing /api/traffic/report...")
start = time.time()
try:
    resp = requests.get('http://127.0.0.1:8000/api/traffic/report', timeout=30)
    elapsed = time.time() - start
    print(f'Status: {resp.status_code}')
    print(f'Time: {elapsed:.2f}s')
    if resp.status_code == 200:
        data = resp.json()
        print(f'Overall status: {data.get("overall_status")}')
        print(f'Overall avg speed: {data.get("overall_average_speed")}')
        print(f'Total incidents: {len(data.get("incidents", []))}')
        print(f'Zones: {len(data.get("zones", []))}')
    else:
        print(f'Error: {resp.text[:500]}')
except Exception as e:
    print(f'Exception: {e}')