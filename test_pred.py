import requests
response = requests.get('http://localhost:8000/api/pollution/predict')
print('Status:', response.status_code)
import json
data = response.json()
print('Regions:')
for r in data['regions']:
    print(f"  {r['region']}: mean={r['next_day_mean_ugm3']}, max={r['next_day_max_ugm3']}, model={r['model']}")