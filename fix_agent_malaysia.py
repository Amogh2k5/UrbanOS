with open(r'backend\app\environment\flood\agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the malaysia evidence section - replace the entire problematic block
old_block = '''        # Build Malaysia evidence
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

new_block = '''        # Malaysia excluded from flood risk assessment
        my_evidence = None'''

content = content.replace(old_block, new_block)

with open(r'backend\app\environment\flood\agent.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed!')