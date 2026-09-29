import requests
import re

resp = requests.get('https://data.gov.sg/datasets?formats=API&sort=relevancy', timeout=30)
print('Status:', resp.status_code)

with open('datasets_api.html', 'w', encoding='utf-8') as f:
    f.write(resp.text)
print('Saved')

with open('datasets_api.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Find all links
matches = re.findall(r'href="([^"]*)"', resp.text)
for m in sorted(set(matches)):
    if 'dataset' in m.lower():
        print(m)