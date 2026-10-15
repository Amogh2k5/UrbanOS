import re

with open(r'C:\projects\UrbanOS\backend\app\environment\flood\agent.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

with open('malaysia_lines.txt', 'w', encoding='utf-8') as out:
    for i, line in enumerate(lines, 1):
        if re.search(r'Malaysia|MALAYSIA|Johor|JOHOR', line, re.IGNORECASE):
            stripped = line.strip()
            if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            with open('malaysia_lines.txt', 'a', encoding='utf-8') as out:
                out.write(f'Line {i}: {line.strip()}\n')

print('Done')