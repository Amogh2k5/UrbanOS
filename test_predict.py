import requests
import time

start = time.time()
try:
    resp = requests.get('http://localhost:8000/api/mobility/traffic/predict', timeout=120)
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
        for d in divisions[:3]:
            div = d.get("division")
            curr = d.get("current_avg_speed")
            pred = d.get("predicted_avg_speed")
            print(f'  {div}: current={curr}, predicted={pred}')
    else:
        print(f'Error: {resp.text[:500]}')
except Exception as e:
    print(f'Exception: {e}')