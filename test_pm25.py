import sys
sys.path.insert(0, '.')
from fastapi.testclient import TestClient
from backend.app.main import app
client = TestClient(app)

# Test PM2.5 KPI
resp = client.get('/kpi/live/pm25')
print('PM2.5 KPI:', resp.status_code)
if resp.status_code == 200:
    print(resp.json())

# Test PM2.5 prediction
resp = client.get('/api/pollution/predict')
print('PM2.5 Prediction:', resp.status_code)
if resp.status_code == 200:
    data = resp.json()
    print('Prediction timestamp:', data.get('prediction_timestamp'))
    print('Target window:', data.get('target_window'))
    for r in data.get('regions', []):
        print(f'  {r["region"]}: ml={r["is_ml_model"]}, model={r["model"]}, mean={r["next_day_mean_ugm3"]}, max={r["next_day_max_ugm3"]}')