import sys
sys.path.insert(0, r'C:\projects\UrbanOS')
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)
response = client.get('/api/crime/report')
print(f'Status: {response.status_code}')
if response.status_code == 200:
    data = response.json()
    print(f'source_status: {data.get("source_status")}')
    print(f'total_physical_crime_2025: {data.get("total_physical_crime_2025")}')
    print(f'total_scams_2025: {data.get("total_scams_2025")}')
    print(f'overview rows: {len(data.get("overview", []))}')
    print(f'scam_types rows: {len(data.get("scam_types", []))}')
    print(f'warnings: {data.get("warnings")}')
    print(f'errors: {data.get("errors")}')