with open(r'tests\test_flood_agent_v3.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove malaysia_evidence from FloodAgentState constructor calls
import re
content = re.sub(r'malaysia_evidence=\{.*?\},\s*\n', '', content)

with open(r'tests\test_flood_agent_v3.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Removed malaysia_evidence from test cases!')