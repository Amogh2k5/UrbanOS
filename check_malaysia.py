import re

with open(r'C:\projects\UrbanOS\backend\app\environment\flood\agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

matches = list(re.finditer(r'Malaysia|MALAYSIA|Johor|JOHOR', content, re.IGNORECASE))
code_refs = []
for m in matches:
    before = content[:m.start()]
    in_string = (before.count('"') % 2 == 1) or (before.count("'") % 2 == 1)
    in_comment = '#' in before.split('\n')[-1]
    if not in_string and not in_comment:
        code_refs.append((m.start(), m.group()))

print(f'Code references: {len(code_refs)}')
for pos, match in code_refs:
    print(f'  Pos {pos}: {match}')

# Also check for malaysia_rainfall field references
malaysia_fields = list(re.finditer(r'malaysia_rainfall|malaysia_rainfall_error|malaysia_evidence', content))
print(f'\nMalaysia field references: {len(malaysia_fields)}')
for m in malaysia_fields:
    start = max(0, m.start()-20)
    end = min(len(content), m.end()+20)
    print(f'  Pos {m.start()}: ...{content[m.start()-20:m.start()]}>>>{content[m.start():m.end()]}<<<{content[m.end():m.end()+20]}...')