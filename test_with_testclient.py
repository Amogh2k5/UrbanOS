import sys
sys.path.insert(0, 'C:/projects/UrbanOS')

from backend.app.main import app
from starlette.testclient import TestClient

client = TestClient(app)

response = client.get('/api/pollution/predict')
print('Status:', response.status_code)
print('Response:', response.json())