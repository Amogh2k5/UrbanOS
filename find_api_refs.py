import requests
import re

resp = requests.get('https://data.gov.sg')
content = resp.text.lower()

# Search for API-related content
matches = re.findall(r'api[^\s"\'<>]{0,50}', content, re.IGNORECASE)
for m in sorted(set(matches)):
    print(m[:100])