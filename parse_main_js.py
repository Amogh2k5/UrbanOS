import re

with open('main.js', 'r', encoding='utf-8') as f:
    content = f.read()

matches = re.findall(r'/api/[^"\s>]+', content)
for m in sorted(set(matches)):
    print(m)