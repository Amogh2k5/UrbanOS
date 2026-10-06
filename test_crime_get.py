import sys
sys.path.insert(0, r'C:\projects\UrbanOS')
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)
response = client.get('/api/crime/report')
print(f'GET /api/crime/report status: {response.status_code}')
if response.status_code == 200:
    data = response.json()
    print(f'Keys: {list(data.keys())}')
    print(f'Period: {data.get("period")}')
else:
    print(f'Error: {response.text[:500]}')