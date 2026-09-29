import requests
import re

resp = requests.get('https://data.gov.sg')
content = resp.text

# Find all links
matches = re.findall(r'href=["\']([^"\']*)["\']', resp.text)
for m in sorted(set(matches)):
    if any(kw in m.lower() for kw in ['api', 'develop', 'doc', 'guide', 'help']):
        print(m)