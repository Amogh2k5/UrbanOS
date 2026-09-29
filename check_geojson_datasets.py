import requests
import re

resp = requests.get('https://data.gov.sg/datasets?formats=GEOJSON&sort=relevancy', timeout=30)
print('Status:', resp.status_code)

with open('geojson_datasets.html', 'w', encoding='utf-8') as f:
    f.write(resp.text)
print('Saved')

with open('geojson_datasets.html', 'r', encoding='utf-8') as f:
    content = f.read()

import re
matches = re.findall(r'href="([^"]*dataset[^"]*)"', resp.text)
for m in sorted(set(matches)):
    print(m)