with open(r'tests\test_flood_agent_v3.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines, 1):
    if 'confidence="high",' in line and i > 100:
        print(f'Line {i}: {line.strip()}')