with open(r'C:\projects\UrbanOS\backend\app\environment\flood\agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

import re
matches = list(re.finditer(r'Malaysia|MALAYSIA|Johor|JOHOR', content, re.IGNORECASE))
code_refs = []
for m in matches:
    before = content[:m.start()]
    in_string = (before.count('"') % 2 == 1) or (before.count("'") % 2 == 1)
    in_comment = '#' in before.split('\n')[-1]
    if not in_string and not in_comment:
        print(f'Code ref at {m.start()}: {m.group()}')

print('Done checking')