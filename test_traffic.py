import sys
sys.path.insert(0, '.')
from fastapi.testclient import TestClient
from backend.app.main import app
client = TestClient(app)

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