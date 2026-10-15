with open(r'C:\projects\UrbanOS\backend\app\environment\flood\agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix malaysia_evidence references in assess_risk
content = content.replace(
    'my_available = state.malaysia_evidence and state.malaysia_evidence.get("available")',
    'my_available = False'
)

content = content.replace(
    'my_evidence = state.malaysia_evidence or {}',
    'my_evidence = {}'
)

content = content.replace(
    'if my_available:',
    'if False:'
)

content = content.replace(
    'if not my_available:',
    'if True:'
)

with open(r'C:\projects\UrbanOS\backend\app\environment\flood\agent.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed!')