with open(r'C:\projects\UrbanOS\tests\test_flood_agent_v3.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix duplicate confidence parameter
content = content.replace(
    'confidence="high",\n            confidence="high",',
    'confidence="high",'
)

with open(r'C:\projects\UrbanOS\tests\test_flood_agent_v3.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed!')