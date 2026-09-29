import requests

paths = [
    '/api/3/action/package_search?q=road&rows=10',
    '/api/2/action/package_search?q=road&rows=10',
    '/api/v1/datasets?q=road',
    '/api/v1/search?q=road',
    '/api/search?q=road',
    '/api/datasets?q=road',
    '/api/v1/search?q=road',
    '/api/data?q=road',
]

for path in paths:
    url = 'https://data.gov.sg' + path
    resp = requests.get('https://data.gov.sg' + path, timeout=10)
    print(path, '->', resp.status_code)
    if resp.status_code == 200:
        try:
            data = resp.json()
            print('  Success! Keys:', list(resp.json().keys()))
        else:
            print('  Failed:', resp.status_code)