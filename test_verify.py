import sys
sys.path.insert(0, r'C:\projects\UrbanOS')
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)
response = client.get('/api/overview/city')
data = response.json()
print(f'Alerts count: {len(data.get("alerts", []))}')
for a in data.get('alerts', []):
    print(f'  Domain: {a["domain"]}')
    print(f'  Severity: {a["severity"]}')
    print(f'  Title: {a["title"]}')
    print(f'  Description: {a["description"][:80]}...')
    print(f'  Timestamp: {a["timestamp"]}')
    print(f'  Affected zones: {a["affected_zones"]}')
    print('---')