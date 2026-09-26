import requests
import time

# Just test the existing server
time.sleep(2)
r = requests.get('http://localhost:8000/api/pollution/predict')
print('Status:', r.status_code)
d = r.json()
for x in d['regions']:
    print(f"  {x['region']}: mean={x['next_day_mean_ugm3']}, max={x['next_day_max_ugm3']}, model={x['model']}")