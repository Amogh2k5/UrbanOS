with open(r'C:\projects\UrbanOS\backend\app\environment\flood\agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

import re
matches = list(re.finditer(r'Malaysia|MALAYSIA|Johor|JOHOR', content, re.IGNORECASE))

with open('malaysia_refs_detailed.txt', 'w', encoding='utf-8') as out:
    out.write(f'Malaysia references: {len(matches)}\n')
    for i, m in enumerate(matches):
        start = max(0, m.start()-50)
        end = min(len(content), m.end()+50)
        ctx = content[start:end].replace('\n', ' ').replace('\r', ' ')
        with open('refs_detailed.txt', 'a', encoding='utf-8') as out:
            out.write(f'{i+1}. Pos {m.start()}: {ctx}\n')

print('Done')