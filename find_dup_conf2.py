import re

with open(r'tests\test_flood_agent_v3.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find all test functions and check for duplicate confidence="high"
pattern = re.compile(r'def test_(\w+)\(self\):')
matches = list(re.finditer(pattern, content))

for m in matches:
    start = m.start()
    next_match = content.find('\n    def test_', m.end())
    if next_match == -1:
        func_body = content[m.end():]
    else:
        func_body = content[m.end():content.find('\n    def test_', m.end())]
    
    conf_count = func_body.count('confidence="high"')
    if conf_count > 1:
        print(f'Function at {pattern.start()} has {conf_count} confidence="high"')
        print(func_body[:500])
        print('---')