import requests

endpoints = [
    ('road', 'https://data.gov.sg/api/action/package_search?q=road&rows=50'),
    ('traffic', 'https://data.gov.sg/api/action/package_search?q=traffic&rows=50'),
    ('infrastructure', 'https://data.gov.sg/api/action/package_search?q=infrastructure&rows=50'),
    ('transport', 'https://data.gov.sg/api/action/package_search?q=transport&rows=50'),
    ('bridge', 'https://data.gov.sg/api/action/package_search?q=bridge&rows=50'),
    ('tunnel', 'https://data.gov.sg/api/action/package_search?q=tunnel&rows=50'),
    ('expressway', 'https://data.gov.sg/api/action/package_search?q=expressway&rows=50'),
    ('highway', 'https://data.gov.sg/api/action/package_search?q=highway&rows=50'),
    ('street', 'https://data.gov.sg/api/action/package_search?q=street&rows=50'),
    ('lane', 'https://data.gov.sg/api/action/package_search?q=lane&rows=50'),
    ('expressway', 'https://data.gov.sg/api/action/package_search?q=expressway&rows=50'),
]

def check_url(name, url):
    try:
        resp = requests.get(url, timeout=10)
        print(url, '->', resp.status_code)
        if resp.status_code == 200:
            data = resp.json()
            if 'result' in data and 'count' in data['result']:
                print('  Count:', data['result']['count'])
            elif 'count' in data:
                print('  Count:', data['count'])
            elif 'data' in data and isinstance(data['data'], list):
                print('  Count:', len(data['data']))
            else:
                print('  Response keys:', list(data.keys())[:5])
        else:
            print('  Error:', resp.text[:200])
    except Exception as e:
        print('  Error parsing:', e)
    print()

if __name__ == '__main__':
    endpoints = [
        ('road', 'https://data.gov.sg/api/action/package_search?q=road&rows=50'),
        ('traffic', 'https://data.gov.sg/api/action/package_search?q=traffic&rows=50'),
        ('infrastructure', 'https://data.gov.sg/api/action/package_search?q=infrastructure&rows=50'),
        ('transport', 'https://data.gov.sg/api/action/package_search?q=transport&rows=50'),
        ('bridge', 'https://data.gov.sg/api/action/package_search?q=bridge&rows=50'),
        ('tunnel', 'https://data.gov.sg/api/action/package_search?q=tunnel&rows=50'),
        ('expressway', 'https://data.gov.sg/api/action/package_search?q=expressway&rows=50'),
        ('highway', 'https://data.gov.sg/api/action/package_search?q=highway&rows=50'),
        ('street', 'https://data.gov.sg/api/action/package_search?q=street&rows=50'),
        ('lane', 'https://data.gov.sg/api/action/package_search?q=lane&rows=50'),
        ('expressway', 'https://data.gov.sg/api/action/package_search?q=expressway&rows=50'),
    ]
    for name, url in [
        ('road', 'https://data.gov.sg/api/action/package_search?q=road&rows=50'),
        ('traffic', 'https://data.gov.sg/api/action/package_search?q=traffic&rows=50'),
        ('infrastructure', 'https://data.gov.sg/api/action/package_search?q=infrastructure&rows=50'),
        ('transport', 'https://data.gov.sg/api/action/package_search?q=transport&rows=50'),
        ('bridge', 'https://data.gov.sg/api/action/package_search?q=bridge&rows=50'),
        ('tunnel', 'https://data.gov.sg/api/action/package_search?q=tunnel&rows=50'),
        ('expressway', 'https://data.gov.sg/api/action/package_search?q=expressway&rows=50'),
        ('highway', 'https://data.gov.sg/api/action/package_search?q=highway&rows=50'),
        ('street', 'https://data.gov.sg/api/action/package_search?q=street&rows=50'),
        ('lane', 'https://data.gov.sg/api/action/package_search?q=lane&rows=50'),
        ('expressway', 'https://data.gov.sg/api/action/package_search?q=expressway&rows=50'),
    ]:
        resp = requests.get(url, timeout=10)
        print(url, '->', resp.status_code)
        if resp.status_code == 200:
            data = resp.json()
            if 'result' in data and 'count' in data['result']:
                print('  Count:', data['result']['count'])
            elif 'count' in data:
                print('  Count:', data['count'])
            elif 'data' in data and isinstance(data['data'], list):
                print('  Count:', len(data['data']))
            else:
                print('  Response keys:', list(data.keys())[:5])
        else:
            print('  Error:', resp.text[:200])
        print()