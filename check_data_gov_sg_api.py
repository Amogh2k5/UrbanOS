import requests
import re

resp = requests.get('https://data.gov.sg')
print('Status:', resp.status_code)
matches = re.findall(r'/api/[^"\s>]+', resp.text)
for m in sorted(set(matches)):
    print(m)