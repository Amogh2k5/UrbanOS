with open(r'backend\app\environment\flood\agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the Malaysia evidence block
old = '''        # Build Malaysia evidence
        my_evidence = None
        if False:
            me = state.malaysia_evidence
            my_evidence = MalaysiaRainfallEvidence(
                available=True,
                source=me.get("source", ""),
                max_1h_mm=me.get("max_1h_mm", 0),
                stations_reporting=len(me.get("stations", {})),
                weather_systems=me.get("weather_systems", []),
            )
my_evidence = None'''

new = '''        # Malaysia excluded from flood risk assessment
        my_evidence = None'''

content = content.replace(old, new)

with open(r'backend\app\environment\flood\agent.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed!')