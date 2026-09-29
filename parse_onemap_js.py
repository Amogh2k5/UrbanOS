import re
import requests

resp = requests.get('https://www.onemap.gov.sg/apidocs/static/js/main.4c62b5c1.js', timeout=10)
print('Main JS:', resp.status_code)
with open('main.js', 'w', encoding='utf-8') as f:
    f.write(resp.text)
print('Saved main JS')

with open('main.js', 'r', encoding='utf-8') as f:
    content = f.read()

import re
matches = re.findall(r'/api/[^"\s>]+', resp.text)
for m in sorted(set(matches)):
    print(m)