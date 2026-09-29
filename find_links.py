import requests
import re

resp = requests.get('https://data.gov.sg')
content = resp.text
matches = re.findall(r'href=[\'"]([^\'"]*)[\'"]', resp.text)
for m in sorted(set(matches)):
    if 'api' in m.lower() or 'developer' in m.lower() or 'dev' in m.lower():
        print(m)