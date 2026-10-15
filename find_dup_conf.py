with open(r'C:\projects\UrbanOS\tests\test_flood_agent_v3.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find duplicate confidence
import re
for m in re.finditer(r'confidence="high"', content):
    start = max(0, m.start()-50)
    end = min(len(content), m.end()+50)
    ctx = content[start:end].replace('\n', ' ').replace('\r', '')
    print(f'Pos {m.start()}: {ctx}')
    print('---')