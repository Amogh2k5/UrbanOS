import sys
sys.path.insert(0, '.')
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)
response = client.get('/api/traffic/report')
print('Status:', response.status_code)
data = response.json()
print('Keys:', data.keys())
print('Zones:', len(data.get('zones', [])))
for z in data.get('zones', []):
    print(f'  {z["zone_id"]}: {z["zone_name"]}, current={z["current_average_speed"]}, pred={z["predicted_average_speed"]}, segments={z["segment_count"]}, congestion={z["congestion_level"]}, incidents={z["incident_count"]}')
print()
print('Overall congestion:', data.get('overall_congestion_level'))
print('Overall status:', data.get('overall_status'))
print('Overall avg speed:', data.get('overall_average_speed'))
print('Overall predicted:', data.get('overall_predicted_speed'))
print('Total incidents:', data.get('active_alert_count', data.get('total_incidents', 'N/A')))