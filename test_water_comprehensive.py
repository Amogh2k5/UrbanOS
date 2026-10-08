import sys
sys.path.insert(0, r'C:\projects\UrbanOS')
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

# Test water report endpoint
print('=== /api/water/report ===')
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

# Test overview includes water
print()
print('=== /api/overview/city (water module) ===')
response = client.get('/api/overview/city')
data = response.json()
water_module = next((m for m in data.get('modules', []) if m['id'] == 'water'), None)
if water_module:
    print(f'Water module found: {water_module}')
else:
    print('Water module NOT found in overview')

# Test all water section endpoints
print()
print('=== Water section endpoints ===')
for endpoint in ['supply', 'drain', 'usage', 'forecast', 'newater', 'quality', 'map', 'sources', 'overview']:
    response = client.get(f'/api/water/{endpoint}')
    print(f'  /api/water/{endpoint}: {response.status_code}')