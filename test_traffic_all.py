import sys
sys.path.insert(0, '.')
from fastapi.testclient import TestClient
from backend.app.main import app
client = TestClient(app)

# Test traffic KPI
resp = client.get('/kpi/live/traffic')
print('Traffic KPI:', resp.status_code)
if resp.status_code == 200:
    print(resp.json())

# Test traffic incidents
resp = client.get('/kpi/live/traffic-incidents')
print('Traffic Incidents:', resp.status_code)
if resp.status_code == 200:
    data = resp.json()
    print(f'Incidents count: {data.get("count")}')
    for inc in data.get('incidents', [])[:3]:
        print(f'  {inc["type"]}: {inc["message"]}')

# Test traffic report
resp = client.get('/api/traffic/report')
print('Traffic Report:', resp.status_code)
if resp.status_code == 200:
    data = resp.json()
    print(f'Overall status: {data.get("overall_status")}')
    print(f'Zones: {len(data.get("zones", []))}')
    print(f'Incidents: {len(data.get("incidents", []))}')

# Test traffic prediction
print('Testing traffic prediction...')
resp = client.get('/api/mobility/traffic/predict')
print('Traffic Prediction:', resp.status_code)
if resp.status_code == 200:
    data = resp.json()
    print('Prediction timestamp:', data.get('prediction_timestamp'))
    print('Target timestamp:', data.get('target_timestamp'))
    print('Is ML:', data.get('is_ml_model'))
    print('Model:', data.get('model'))
    print('Divisions:', len(data.get('divisions', [])))
    for d in data.get('divisions', []):
        print(f'  {d["division"]}: current={d["current_avg_speed"]}, pred={d["predicted_avg_speed"]}, congestion={d["congestion_level"]}, segments={d["segment_count"]}')
    print('Link predictions:', len(data.get('link_predictions', [])))
else:
    print('Error:', resp.text)