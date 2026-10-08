import sys
sys.path.insert(0, r'C:\projects\UrbanOS')
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)
response = client.get('/api/water/report')
print(f'Status: {response.status_code}')
if response.status_code == 200:
    data = response.json()
    print(f'Domain: {data.get("domain")}')
    print(f'Subdomain: {data.get("subdomain")}')
    print(f'Overall status: {data.get("overall_status")}')
    print(f'Overall risk: {data.get("overall_risk")}')
    print(f'Confidence: {data.get("confidence")}')
    print(f'Supply status: {data.get("supply", {}).get("status")}')
    print(f'Drain sensor count: {data.get("drain", {}).get("sensor_count")}')
    print(f'Drain readings available: {data.get("drain", {}).get("readings_available")}')
    print(f'Usage potable total: {data.get("usage", {}).get("potable_total")}')
    print(f'Alerts: {len(data.get("alerts", []))}')
    print(f'Insights: {len(data.get("insights", []))}')
    print(f'Sources: {len(data.get("sources", []))}')
else:
    print(f'Error: {response.text[:500]}')