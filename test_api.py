import sys
sys.path.insert(0, '.')
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)
response = client.get('/api/mobility/traffic/predict')
print('Status:', response.status_code)
data = response.json()
print('Keys:', data.keys())
print('Divisions:', len(data.get('divisions', [])))
for d in data.get('divisions', []):
    print(f'  {d["division"]}: current={d["current_avg_speed"]}, pred={d["predicted_avg_speed"]}, segments={d["segment_count"]}, congestion={d["congestion_level"]}')