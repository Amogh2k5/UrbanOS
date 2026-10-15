with open(r'C:\projects\UrbanOS\tests\test_flood_agent_v3.py', 'r', encoding='utf-8') as f:
    content = f.read()

import re
matches = list(re.finditer(r'confidence="high"', content))
with open('conf_check.txt', 'w', encoding='utf-8') as out:
    out.write(f'Found {len(matches)} occurrences\n')
    for i, m in enumerate(matches):
        start = max(0, m.start()-50)
        end = min(len(content), m.end()+50)
        ctx = content[start:end].replace('\n', ' ').replace('\r', ' ')
        out.write(f'{i+1}. Pos {m.start()}: {ctx}\n---\n')
print('Done')