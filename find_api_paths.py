import re

with open('C:/projects/UrbanOS/data_gov_sg.html', 'r', encoding='utf-8') as f:
    content = f.read()

matches = re.findall(r'/api/[^"\s>]+', content)
for m in sorted(set(matches)):
    print(m)