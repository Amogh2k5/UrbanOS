import requests
import re

resp = requests.get('https://data.gov.sg')
content = resp.text

# Find all URLs containing 'api'
matches = re.findall(r'https?://[^"\s>]+api[^"\s>]*', content)
for m in sorted(set(matches)):
    print(m)