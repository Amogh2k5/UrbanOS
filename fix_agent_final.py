import re

with open(r'C:\projects\UrbanOS\backend\app\environment\flood\agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: In assess_risk, remove the malaysia_evidence check
content = content.replace(
    'my_available = state.malaysia_evidence and state.malaysia_evidence.get("available")',
    'my_available = False'
)

content = content.replace(
    'if my_available:',
    'if False:'
)

# Fix 2: In build_report, remove malaysia_evidence check
content = content.replace(
    'if state.malaysia_evidence and state.malaysia_evidence.get("available"):',
    'if False:'
)

content = content.replace(
    '            my_evidence = None\n        if state.malaysia_evidence and state.malaysia_evidence.get("available"):\n            me = state.malaysia_evidence\n            my_evidence = MalaysiaRainfallEvidence(\n                available=True,\n                source=me.get("source", ""),\n                max_1h_mm=me.get("max_1h_mm", 0),\n                stations_reporting=len(me.get("stations", {})),\n                weather_systems=me.get("weather_systems", []),\n            )',
    'my_evidence = None'
)

content = content.replace(
    '        else:\n            my_evidence = MalaysiaRainfallEvidence(\n                available=False,\n                source=state.malaysia_evidence.get("source", "") if state.malaysia_evidence else "unavailable",\n                max_1h_mm=0.0,\n                stations_reporting=0,\n                weather_systems=[],\n            )',
    'my_evidence = None'
)

# Remove the MalaysiaRainfallEvidence import if present
content = content.replace(
'''from backend.app.environment.flood.models import (
    FloodReport, PastFloodEvent, ActiveFloodAlert,
    SingaporeRainfallEvidence, MalaysiaRainfallEvidence, SumatraRainfallEvidence,
    RegionalWeatherStatus, FloodRiskLevel
)''',
'''from backend.app.environment.flood.models import (
    FloodReport, PastFloodEvent, ActiveFloodAlert,
    SingaporeRainfallEvidence, SumatraRainfallEvidence,
    RegionalWeatherStatus, FloodRiskLevel
)''')

# Also remove the MalaysiaRainfallEvidence import if it exists
content = content.replace(
'''from backend.app.environment.flood.models import (
    FloodReport, PastFloodEvent, ActiveFloodAlert,
    SingaporeRainfallEvidence, MalaysiaRainfallEvidence, SumatraRainfallEvidence,
    RegionalWeatherStatus, FloodRiskLevel
)''',
'''from backend.app.environment.flood.models import (
    FloodReport, PastFloodEvent, ActiveFloodAlert,
    SingaporeRainfallEvidence, SumatraRainfallEvidence,
    RegionalWeatherStatus, FloodRiskLevel
)''')

# Remove MalaysiaRainfallApiClient import if present
content = content.replace(
'''from backend.app.environment.flood.rainfall_clients import (
    RainfallApiClient, RainfallSnapshot,
    MalaysiaRainfallApiClient, MalaysiaRainfallSnapshot, get_malaysia_rainfall_evidence,
    SumatraForecastApiClient, SumatraForecastSnapshot, get_sumatra_forecast_evidence,
)''',
'''from backend.app.environment.flood.rainfall_clients import (
    RainfallApiClient, RainfallSnapshot,
    SumatraForecastApiClient, SumatraForecastSnapshot, get_sumatra_forecast_evidence,
)''')

# Remove MalaysiaRainfallApiClient from agent.py
content = content.replace(
'''from backend.app.environment.flood.rainfall_clients import (
    RainfallApiClient, RainfallSnapshot,
    MalaysiaRainfallApiClient, MalaysiaRainfallSnapshot, get_malaysia_rainfall_evidence,
    SumatraForecastApiClient, SumatraForecastSnapshot, get_sumatra_forecast_evidence,
)''',
'''from backend.app.environment.flood.rainfall_clients import (
    RainfallApiClient, RainfallSnapshot,
    SumatraForecastApiClient, SumatraForecastSnapshot, get_sumatra_forecast_evidence,
)''')

# Remove fetch_malaysia_rainfall function
import re
content = re.sub(r'# ============================================================\s*# NODE 3: FETCH_MALAYSIA_RAINFALL\s*# ============================================================\s*def fetch_malaysia_rainfall\(state: FloodAgentState\) -> FloodAgentState:.*?return state\s*\n', '', content, flags=re.DOTALL)

# Remove the node from the workflow
content = content.replace('workflow.add_node("FETCH_MY_RAINFALL", fetch_malaysia_rainfall)\n', '')
content = content.replace('workflow.add_edge("FETCH_SG_RAINFALL", "FETCH_MY_RAINFALL")\n', '')
content = content.replace('workflow.add_edge("FETCH_MY_RAINFALL", "FETCH_SU_FORECAST")\n', 'workflow.add_edge("FETCH_SG_RAINFALL", "FETCH_SU_FORECAST")\n')

# Remove malaysia_evidence field from FloodAgentState
content = content.replace('    malaysia_rainfall: Optional[MalaysiaRainfallSnapshot] = None\n', '')
content = content.replace('    malaysia_rainfall_error: Optional[str] = None\n', '')

content = content.replace('    malaysia_evidence: Optional[Dict[str, Any]] = None\n', '')

# Remove malaysia_evidence from build_report
content = content.replace(
'''        # Build Malaysia evidence
        my_evidence = None
        if state.malaysia_evidence and state.malaysia_evidence.get("available"):
            me = state.malaysia_evidence
            my_evidence = MalaysiaRainfallEvidence(
                available=True,
                source=me.get("source", ""),
                max_1h_mm=me.get("max_1h_mm", 0),
                stations_reporting=len(me.get("stations", {})),
                weather_systems=me.get("weather_systems", []),
            )
        else:
            my_evidence = MalaysiaRainfallEvidence(
                available=False,
                source=state.malaysia_evidence.get("source", "") if state.malaysia_evidence else "unavailable",
                max_1h_mm=0.0,
                stations_reporting=0,
                weather_systems=[],
            )''',
'''        my_evidence = None''')

# Remove malaysia_evidence field from FloodAgentState
content = re.sub(r'    malaysia_evidence: Optional\[Dict\[str, Any\]\] = None\n', '', content)
content = content.replace('    malaysia_evidence: Optional[Dict[str, Any]] = None\n', '')

# Remove malaysia_evidence error field
content = content.replace('    malaysia_rainfall_error: Optional[str] = None\n', '')

# Remove malaysia_evidence from build_report
content = content.replace(
'        # Build Malaysia evidence\n'
'        my_evidence = None\n'
'        if state.malaysia_evidence and state.malaysia_evidence.get("available"):\n'
'            me = state.malaysia_evidence\n'
'            my_evidence = MalaysiaRainfallEvidence(\n'
'                available=True,\n'
'                source=me.get("source", ""),\n'
'                max_1h_mm=me.get("max_1h_mm", 0),\n'
'                stations_reporting=len(me.get("stations", {})),\n'
'                weather_systems=me.get("weather_systems", []),\n'
'            )\n'
'        else:\n'
'            my_evidence = MalaysiaRainfallEvidence(\n'
'                available=False,\n'
'                source=state.malaysia_evidence.get("source", "") if state.malaysia_evidence else "unavailable",\n'
'                max_1h_mm=0.0,\n'
'                stations_reporting=0,\n'
'                weather_systems=[],\n'
'            )', 'my_evidence = None')

# Remove malaysia_evidence from report creation
content = content.replace(
'            malaysia_rainfall=my_evidence,',
'')

# Remove malaysia_evidence from state initialization in tests
# This will be handled by test file fixes

# Remove Malaysia from risk assessment
content = content.replace(
'        # --- MALAYSIA/JOHOR RAINFALL (SUPPORTING) ---\n'
'        my_evidence = state.malaysia_evidence or {}\n'
'        if my_available:\n'
'            max_1h = my_evidence.get("max_1h_mm", 0)\n'
'            if max_1h >= 50:\n'
'                risk_score += MALAYSIA_WEIGHT * 0.5\n'
'                risk_factors.append(f"Johor heavy rainfall: {max_1h:.1f}mm (weight: {MALAYSIA_WEIGHT})")\n'
'            elif max_1h >= 30:\n'
'                risk_score += MALAYSIA_WEIGHT * 0.2\n'
'                risk_factors.append(f"Johor moderate rainfall: {max_1h:.1f}mm")\n'
'        else:\n'
'            risk_factors.append(f"Malaysia/Johor rainfall: UNAVAILABLE ({my_evidence.get(\'error\', \'no data\')}")',
'')

# Remove Malaysia from risk_rules imports
# Already handled in risk_rules.py

# Remove Malaysia from REGIONAL_RULES in risk_rules.py (already done)

# Remove Malaysia from agent.py docstring
content = content.replace(
'LIVE WEATHER OBSERVATIONS (Singapore, Malaysia/Johor, Sumatra) � CURRENT FLOOD RISK',
'LIVE WEATHER OBSERVATIONS (Singapore, Sumatra) � CURRENT FLOOD RISK'
)

content = content.replace(
'2. Fetch live Malaysia/Johor rainfall (MetMalaysia API)\n',
'')

content = content.replace(
'3. Fetch live Sumatra rainfall (BMKG API)\n',
'2. Fetch live Sumatra rainfall (BMKG API)\n')

content = content.replace(
'4. Fetch PUB flood alerts\n',
'3. Fetch PUB flood alerts\n')

content = content.replace(
'5. Fetch NEA 24h weather forecast\n',
'4. Fetch NEA 24h weather forecast\n')

# Remove Malaysia from limitations
content = content.replace(
'            "Malaysia/Johor and Sumatra APIs may be unavailable (require credentials)",\n',
'')

# Remove Malaysia from limitations in build_report
content = content.replace(
'            "Malaysia/Johor and Sumatra APIs may be unavailable (require credentials)",\n',
'            "Sumatra API may be unavailable (requires credentials)",\n')

# Write the fixed content
with open(r'C:\projects\UrbanOS\backend\app\environment\flood\agent.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed agent.py!')