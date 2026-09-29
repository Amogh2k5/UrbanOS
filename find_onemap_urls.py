import re

with open('onemap_docs.html', 'r', encoding='utf-8') as f:
    content = f.read()

matches = re.findall(r'https?://[^"\s>]+', content)
for m in sorted(set(matches)):
    if 'api' in m.lower():
        print(m)