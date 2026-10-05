import sys
sys.path.insert(0, r'C:\projects\UrbanOS')
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)
response = client.get('/api/overview/city')
print(f'Status: {response.status_code}')
if response.status_code == 200:
    data = response.json()
    print(f'Modules: {len(data.get("modules", []))}')
    print(f'Alerts: {len(data.get("alerts", []))}')
    print(f'AI Brief: {data.get("ai_brief")}')
    for m in data.get('modules', []):
        kpi = m.get('kpi')
        kpi_str = f'{kpi["label"]}: {kpi["value"]} {kpi["unit"]}' if kpi else 'None'
        print(f'  - {m["id"]}: {m["status"]} KPI={kpi_str}')
    if data.get('alerts'):
        for a in data['alerts']:
            print(f'  - {a.get("domain")}: {a.get("title")[:50]}')
else:
    print(f'Error: {response.text[:500]}')