import sys
sys.path.insert(0, r'C:\projects\UrbanOS')
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)
response = client.get('/api/overview/city')
data = response.json()
for m in data.get('modules', []):
    kpi = m.get('kpi')
    kpi_str = f'{kpi["label"]}: {kpi["value"]} {kpi["unit"]}' if kpi else 'None'
    print(f'  - {m["id"]}: {m["status"]} KPI={kpi_str} detail_route={m.get("detail_route")}')