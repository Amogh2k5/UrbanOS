with open(r'tests\test_flood_agent_v3.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Remove duplicate lines:
# Line 346: duplicate confidence="high",
# Line 344: duplicate overall_city_status="DISRUPTED",

new_lines = []
for i, line in enumerate(lines, 1):
    if i == 344:  # Skip duplicate overall_city_status
        continue
    if i == 346:  # Skip duplicate confidence
        continue
    new_lines.append(line)

with open(r'tests\test_flood_agent_v3.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('Fixed!')