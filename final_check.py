with open(r'C:\projects\UrbanOS\backend\app\environment\flood\agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

import re
matches = list(re.finditer(r'Malaysia|MALAYSIA|Johor|JOHOR', content, re.IGNORECASE))
code_refs = []
for m in matches:
    before = content[:m.start()]
    in_comment = '#' in before.split('\n')[-1] or '"""' in before[-100:] or "'''" in before[-100:]
    in_string = (before.count('"') % 2 == 1) or (before.count("'") % 2 == 1)
    if not in_comment and not in_string:
        code_refs.append((m.start(), m.group()))

print(f'Actual code references to Malaysia/Johor: {len(code_refs)}')
for pos, match in code_refs:
    print(f'  Pos {pos}: {match}')

# Check frontend
with open(r'C:\projects\UrbanOS\frontend\src\app\environment\flood\page.tsx', 'r', encoding='utf-8') as f:
    frontend = f.read()

malaysia_refs = len(re.findall(r'Malaysia|malaysia|Johor|johor', frontend, re.IGNORECASE))
print(f'Frontend Malaysia/Johor references: {malaysia_refs}')

print('\nDone!')