content = content.replace(
    'state.malaysia_evidence.get("available") if state.malaysia_evidence else False',
    'False'
)

content = content.replace(
    'state.malaysia_evidence.get("weather_systems", []) if state.malaysia_evidence else []',
    '[]'
)

with open(r'C:\projects\UrbanOS\backend\app\environment\flood\agent.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed!')