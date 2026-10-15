with open(r'C:\projects\UrbanOS\backend\app\environment\flood\agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove Malaysia imports
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

content = content.replace(
'''from backend.app.environment.flood.config.risk_rules import (
    RISK_THRESHOLDS, SINGAPORE_RAINFALL_RULES, REGIONAL_RULES, PUB_ALERT_RULES,
    CALIBRATION_METADATA, SINGAPORE_1H_MODERATE, SINGAPORE_1H_HEAVY, SINGAPORE_1H_EXTREME,
    SINGAPORE_3H_HEAVY, SINGAPORE_6H_HEAVY, SINGAPORE_24H_HEAVY,
    SINGAPORE_15M_MODERATE, SINGAPORE_15M_HEAVY, SINGAPORE_15M_EXTREME,
    SINGAPORE_5M_MODERATE, SINGAPORE_5M_HEAVY, SINGAPORE_5M_EXTREME,
    SINGAPORE_STATIONS_WIDESPREAD, SINGAPORE_STATIONS_EXTENSIVE,
    MALAYSIA_WEIGHT, SUMATRA_WEIGHT, SUMATRA_SQUALL_WEIGHT, MONSOON_SURGE_WEIGHT,
    PUB_ALERT_HIGH_WEIGHT, PUB_ALERT_MODERATE_WEIGHT, PUB_ALERT_LOW_WEIGHT,
    PUB_MULTIPLE_ALERTS_BONUS,
)''',
'''from backend.app.environment.flood.config.risk_rules import (
    RISK_THRESHOLDS, SINGAPORE_RAINFALL_RULES, REGIONAL_RULES, PUB_ALERT_RULES,
    CALIBRATION_METADATA, SINGAPORE_1H_MODERATE, SINGAPORE_1H_HEAVY, SINGAPORE_1H_EXTREME,
    SINGAPORE_3H_HEAVY, SINGAPORE_6H_HEAVY, SINGAPORE_24H_HEAVY,
    SINGAPORE_15M_MODERATE, SINGAPORE_15M_HEAVY, SINGAPORE_15M_EXTREME,
    SINGAPORE_5M_MODERATE, SINGAPORE_5M_HEAVY, SINGAPORE_5M_EXTREME,
    SINGAPORE_STATIONS_WIDESPREAD, SINGAPORE_STATIONS_EXTENSIVE,
    SUMATRA_WEIGHT, SUMATRA_SQUALL_WEIGHT, MONSOON_SURGE_WEIGHT,
    PUB_ALERT_HIGH_WEIGHT, PUB_ALERT_MODERATE_WEIGHT, PUB_ALERT_LOW_WEIGHT,
    PUB_MULTIPLE_ALERTS_BONUS,
)''')

# Remove Malaysia/JOHOR references in code (not comments/docstrings)
import re

# Remove Malaysia/JOHOR from code (keep in comments/docstrings)
def remove_malaysia_code(content):
    lines = content.split('\n')
    new_lines = []
    for line in content.split('\n'):
        stripped = line.strip()
        # Skip if it's a comment or docstring
        stripped = line.strip()
        if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
            new_lines.append(line)
            continue
        # Remove Malaysia/JOHOR references from code
        if re.search(r'(Malaysia|MALAYSIA|Johor|JOHOR|malaysia|johor)', line) and not (line.strip().startswith('#') or line.strip().startswith('"""') or line.strip().startswith("'''")):
            # Replace Malaysia references with empty or appropriate replacement
            line = re.sub(r'\bMalaysia\b', '', line, flags=re.IGNORECASE)
            line = re.sub(r'\bJohor\b', '', line, flags=re.IGNORECASE)
            line = re.sub(r'\bMALAYSIA\b', '', line, flags=re.IGNORECASE)
            line = re.sub(r'\bJOHOR\b', '', line, flags=re.IGNORECASE)
            # Clean up any double spaces
            line = re.sub(r'\s+', ' ', line).strip()
            if line:
                new_lines.append(line + '\n')
        else:
            new_lines.append(line)
    return '\n'.join(new_lines)

with open(r'C:\projects\UrbanOS\backend\app\environment\flood\agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Apply fixes step by step
# 1. Fix imports
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

content = content.replace(
'''from backend.app.environment.flood.config.risk_rules import (
    RISK_THRESHOLDS, SINGAPORE_RAINFALL_RULES, REGIONAL_RULES, PUB_ALERT_RULES,
    CALIBRATION_METADATA, SINGAPORE_1H_MODERATE, SINGAPORE_1H_HEAVY, SINGAPORE_1H_EXTREME,
    SINGAPORE_3H_HEAVY, SINGAPORE_6H_HEAVY, SINGAPORE_24H_HEAVY,
    SINGAPORE_15M_MODERATE, SINGAPORE_15M_HEAVY, SINGAPORE_15M_EXTREME,
    SINGAPORE_5M_MODERATE, SINGAPORE_5M_HEAVY, SINGAPORE_5M_EXTREME,
    SINGAPORE_STATIONS_WIDESPREAD, SINGAPORE_STATIONS_EXTENSIVE,
    MALAYSIA_WEIGHT, SUMATRA_WEIGHT, SUMATRA_SQUALL_WEIGHT, MONSOON_SURGE_WEIGHT,
    PUB_ALERT_HIGH_WEIGHT, PUB_ALERT_MODERATE_WEIGHT, PUB_ALERT_LOW_WEIGHT,
    PUB_MULTIPLE_ALERTS_BONUS,
)''',
'''from backend.app.environment.flood.config.risk_rules import (
    RISK_THRESHOLDS, SINGAPORE_RAINFALL_RULES, REGIONAL_RULES, PUB_ALERT_RULES,
    CALIBRATION_METADATA, SINGAPORE_1H_MODERATE, SINGAPORE_1H_HEAVY, SINGAPORE_1H_EXTREME,
    SINGAPORE_3H_HEAVY, SINGAPORE_6H_HEAVY, SINGAPORE_24H_HEAVY,
    SINGAPORE_15M_MODERATE, SINGAPORE_15M_HEAVY, SINGAPORE_15M_EXTREME,
    SINGAPORE_5M_MODERATE, SINGAPORE_5M_HEAVY, SINGAPORE_5M_EXTREME,
    SINGAPORE_STATIONS_WIDESPREAD, SINGAPORE_STATIONS_EXTENSIVE,
    SUMATRA_WEIGHT, SUMATRA_SQUALL_WEIGHT, MONSOON_SURGE_WEIGHT,
    PUB_ALERT_HIGH_WEIGHT, PUB_ALERT_MODERATE_WEIGHT, PUB_ALERT_LOW_WEIGHT,
    PUB_MULTIPLE_ALERTS_BONUS,
)''')

# Remove fetch_malaysia_rainfall function and its call
import re
content = re.sub(r'# ============================================================\s*# NODE 3: FETCH_MALAYSIA_RAINFALL\s*# ============================================================\s*def fetch_malaysia_rainfall\(state: FloodAgentState\) -> FloodAgentState:.*?return state\s*\n', '', content, flags=re.DOTALL)

# Remove the call to fetch_malaysia_rainfall in the workflow
content = re.sub(r'workflow\.add_node\("FETCH_MY_RAINFALL", fetch_malaysia_rainfall\)\s*\n', '', content)
content = re.sub(r'workflow\.add_edge\("FETCH_SG_RAINFALL", "FETCH_MY_RAINFALL"\)\s*\n', '', content)
content = re.sub(r'workflow\.add_edge\("FETCH_MY_RAINFALL", "FETCH_SU_FORECAST"\)\s*\n', 'workflow.add_edge("FETCH_SG_RAINFALL", "FETCH_SU_FORECAST")\n', content)

# Remove malaysia_rainfall and malaysia_rainfall_error from FloodAgentState
content = content.replace('    malaysia_rainfall: Optional[MalaysiaRainfallSnapshot] = None\n', '')
content = content.replace('    malaysia_rainfall_error: Optional[str] = None\n', '')

# Remove malaysia_evidence from state
content = content.replace('    malaysia_evidence: Optional[Dict[str, Any]] = None\n', '')

# Remove malaysia_evidence usage in build_report
content = content.replace('state.malaysia_evidence.get("available") if state.malaysia_evidence else False', 'False')
content = content.replace('state.malaysia_evidence.get("weather_systems", []) if state.malaysia_evidence else []', '[]')
content = content.replace('malaysia_rainfall=my_evidence,', '')
content = content.replace('malaysia_rainfall=my_evidence,', '')

# Remove Malaysia references from risk assessment
content = re.sub(r'# --- MALAYSIA/JOHOR RAINFALL \(SUPPORTING\) ---\s*\n\s*my_evidence = state\.malaysia_evidence or \{\}\s*\n\s*if my_available:\s*\n.*?else:\s*\n\s*risk_factors\.append\(f"Malaysia/Johor rainfall: UNAVAILABLE.*?\)\)', '', content, flags=re.DOTALL)

# Remove Malaysia from risk rules imports
content = content.replace(
'''from backend.app.environment.flood.config.risk_rules import (
    RISK_THRESHOLDS, SINGAPORE_RAINFALL_RULES, REGIONAL_RULES, PUB_ALERT_RULES,
    CALIBRATION_METADATA, SINGAPORE_1H_MODERATE, SINGAPORE_1H_HEAVY, SINGAPORE_1H_EXTREME,
    SINGAPORE_3H_HEAVY, SINGAPORE_6H_HEAVY, SINGAPORE_24H_HEAVY,
    SINGAPORE_15M_MODERATE, SINGAPORE_15M_HEAVY, SINGAPORE_15M_EXTREME,
    SINGAPORE_5M_MODERATE, SINGAPORE_5M_HEAVY, SINGAPORE_5M_EXTREME,
    SINGAPORE_STATIONS_WIDESPREAD, SINGAPORE_STATIONS_EXTENSIVE,
    MALAYSIA_WEIGHT, SUMATRA_WEIGHT, SUMATRA_SQUALL_WEIGHT, MONSOON_SURGE_WEIGHT,
    PUB_ALERT_HIGH_WEIGHT, PUB_ALERT_MODERATE_WEIGHT, PUB_ALERT_LOW_WEIGHT,
    PUB_MULTIPLE_ALERTS_BONUS,
)''',
'''from backend.app.environment.flood.config.risk_rules import (
    RISK_THRESHOLDS, SINGAPORE_RAINFALL_RULES, REGIONAL_RULES, PUB_ALERT_RULES,
    CALIBRATION_METADATA, SINGAPORE_1H_MODERATE, SINGAPORE_1H_HEAVY, SINGAPORE_1H_EXTREME,
    SINGAPORE_3H_HEAVY, SINGAPORE_6H_HEAVY, SINGAPORE_24H_HEAVY,
    SINGAPORE_15M_MODERATE, SINGAPORE_15M_HEAVY, SINGAPORE_15M_EXTREME,
    SINGAPORE_5M_MODERATE, SINGAPORE_5M_HEAVY, SINGAPORE_5M_EXTREME,
    SINGAPORE_STATIONS_WIDESPREAD, SINGAPORE_STATIONS_EXTENSIVE,
    SUMATRA_WEIGHT, SUMATRA_SQUALL_WEIGHT, MONSOON_SURGE_WEIGHT,
    PUB_ALERT_HIGH_WEIGHT, PUB_ALERT_MODERATE_WEIGHT, PUB_ALERT_LOW_WEIGHT,
    PUB_MULTIPLE_ALERTS_BONUS,
)''')

# Remove Malaysia from REGIONAL_RULES in risk_rules.py - will be done separately

# Remove Malaysia from agent.py docstring
content = content.replace('LIVE WEATHER OBSERVATIONS (Singapore, Malaysia/Johor, Sumatra) � CURRENT FLOOD RISK', 'LIVE WEATHER OBSERVATIONS (Singapore, Sumatra) � CURRENT FLOOD RISK')
content = content.replace('2. Fetch live Malaysia/Johor rainfall (MetMalaysia API)\n', '')
content = content.replace('3. Fetch live Sumatra rainfall (BMKG API)\n', '2. Fetch live Sumatra rainfall (BMKG API)\n')
content = content.replace('4. Fetch PUB flood alerts\n', '3. Fetch PUB flood alerts\n')
content = content.replace('5. Fetch NEA 24h weather forecast\n', '4. Fetch NEA 24h weather forecast\n')

# Remove Malaysia from risk assessment comments
content = content.replace('- Malaysia/Johor rainfall = SUPPORTING (weight 0.3)\n', '')

# Write the fixed content
with open(r'C:\projects\UrbanOS\backend\app\environment\flood\agent.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed agent.py!')