import re

with open(r'C:\projects\UrbanOS\tests\test_flood_agent_v3.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Fix imports
content = content.replace(
'''from backend.app.environment.flood.agent import (
    FloodAgentState,
    create_flood_agent_v3,
    load_past_flood_events,
    fetch_singapore_rainfall,
    fetch_malaysia_rainfall,
    fetch_sumatra_forecast,
    fetch_pub_alerts,
    fetch_nea_weather,
    assess_risk,
    build_report,
    run_flood_agent_v3,
    _CATALOGUE_PATH,
    _analyze_singapore_rainfall,
    _analyze_nea_weather,
)''',
'''from backend.app.environment.flood.agent import (
    FloodAgentState,
    create_flood_agent_v3,
    load_past_flood_events,
    fetch_singapore_rainfall,
    fetch_sumatra_forecast,
    fetch_pub_alerts,
    fetch_nea_weather,
    assess_risk,
    build_report,
    run_flood_agent_v3,
    _CATALOGUE_PATH,
    _analyze_singapore_rainfall,
    _analyze_nea_weather,
)''')

# Fix risk_rules import
content = content.replace(
'''from backend.app.environment.flood.config.risk_rules import (
    MALAYSIA_WEIGHT,
    PUB_ALERT_HIGH_WEIGHT,
    PUB_ALERT_MODERATE_WEIGHT,
    PUB_MULTIPLE_ALERTS_BONUS,
    RISK_THRESHOLDS,
)''',
'''from backend.app.environment.flood.config.risk_rules import (
    PUB_ALERT_HIGH_WEIGHT,
    PUB_ALERT_MODERATE_WEIGHT,
    PUB_ALERT_LOW_WEIGHT,
    PUB_MULTIPLE_ALERTS_BONUS,
    RISK_THRESHOLDS,
)''')

# Fix models import
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

# Remove test_fetch_malaysia_rainfall_offline
import re
content = re.sub(r'def test_fetch_malaysia_rainfall_offline\(self\):.*?(?=\n    def test_)', '', content, flags=re.DOTALL)

# Remove test_assess_risk_malaysia_heavy_rainfall
content = re.sub(r'def test_assess_risk_malaysia_heavy_rainfall\(self\):.*?(?=\n    def test_)', '', content, flags=re.DOTALL)

# Remove malaysia_evidence references in test calls
content = re.sub(r'malaysia_evidence=\{.*?available.*?False[^}]*\},\s*\n', '', content)
content = re.sub(r'malaysia_evidence=\{.*?available.*?True[^}]*\},\s*\n', '', content)

# Remove MALAYSIA_WEIGHT reference
content = content.replace('MALAYSIA_WEIGHT,', '')

# Fix risk_rules import test
old_risk_test = '''    def test_risk_rules_import(self):
        from backend.app.environment.flood.config.risk_rules import (
            MALAYSIA_WEIGHT,
            PUB_ALERT_HIGH_WEIGHT,
            PUB_ALERT_MODERATE_WEIGHT,
            PUB_MULTIPLE_ALERTS_BONUS,
            RISK_THRESHOLDS,
        )
        assert 0 < MALAYSIA_WEIGHT < 1
        assert 0 < PUB_ALERT_HIGH_WEIGHT < 1
        assert 0 < PUB_ALERT_MODERATE_WEIGHT < 1
        assert 0 < PUB_ALERT_LOW_WEIGHT < 1
        assert PUB_MULTIPLE_ALERTS_BONUS > 0
        assert RISK_THRESHOLDS["LOW"] == 0.0
        assert RISK_THRESHOLDS["MODERATE"] == 0.4
        assert RISK_THRESHOLDS["HIGH"] == 0.7
        assert RISK_THRESHOLDS["CRITICAL"] == 1.0
        assert RISK_THRESHOLDS["UNKNOWN"] == -1.0'''

new_risk_test = '''    def test_risk_rules_import(self):
        from backend.app.environment.flood.config.risk_rules import (
            PUB_ALERT_HIGH_WEIGHT,
            PUB_ALERT_MODERATE_WEIGHT,
            PUB_ALERT_LOW_WEIGHT,
            PUB_MULTIPLE_ALERTS_BONUS,
            RISK_THRESHOLDS,
        )
        assert 0 < PUB_ALERT_HIGH_WEIGHT < 1
        assert 0 < PUB_ALERT_MODERATE_WEIGHT < 1
        assert 0 < PUB_ALERT_LOW_WEIGHT < 1
        assert PUB_MULTIPLE_ALERTS_BONUS > 0
        assert RISK_THRESHOLDS["LOW"] == 0.0
        assert RISK_THRESHOLDS["MODERATE"] == 0.4
        assert RISK_THRESHOLDS["HIGH"] == 0.7
        assert RISK_THRESHOLDS["CRITICAL"] == 1.0
        assert RISK_THRESHOLDS["UNKNOWN"] == -1.0'''

with open(r'C:\projects\UrbanOS\tests\test_flood_agent_v3.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
'''from backend.app.environment.flood.agent import (
    FloodAgentState,
    create_flood_agent_v3,
    load_past_flood_events,
    fetch_singapore_rainfall,
    fetch_malaysia_rainfall,
    fetch_sumatra_forecast,
    fetch_pub_alerts,
    fetch_nea_weather,
    assess_risk,
    build_report,
    run_flood_agent_v3,
    _CATALOGUE_PATH,
    _analyze_singapore_rainfall,
    _analyze_nea_weather,
)''',
'''from backend.app.environment.flood.agent import (
    FloodAgentState,
    create_flood_agent_v3,
    load_past_flood_events,
    fetch_singapore_rainfall,
    fetch_sumatra_forecast,
    fetch_pub_alerts,
    fetch_nea_weather,
    assess_risk,
    build_report,
    run_flood_agent_v3,
    _CATALOGUE_PATH,
    _analyze_singapore_rainfall,
    _analyze_nea_weather,
)''')

content = content.replace(
'''from backend.app.environment.flood.config.risk_rules import (
    MALAYSIA_WEIGHT,
    PUB_ALERT_HIGH_WEIGHT,
    PUB_ALERT_MODERATE_WEIGHT,
    PUB_MULTIPLE_ALERTS_BONUS,
    RISK_THRESHOLDS,
)''',
'''from backend.app.environment.flood.config.risk_rules import (
    PUB_ALERT_HIGH_WEIGHT,
    PUB_ALERT_MODERATE_WEIGHT,
    PUB_ALERT_LOW_WEIGHT,
    PUB_MULTIPLE_ALERTS_BONUS,
    RISK_THRESHOLDS,
)''')

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

# Remove test_fetch_malaysia_rainfall_offline
content = re.sub(r'def test_fetch_malaysia_rainfall_offline\(self\):.*?(?=\n    def test_)', '', content, flags=re.DOTALL)

# Remove test_assess_risk_malaysia_heavy_rainfall
content = re.sub(r'def test_assess_risk_malaysia_heavy_rainfall\(self\):.*?(?=\n    def test_)', '', content, flags=re.DOTALL)

# Remove malaysia_evidence references
content = re.sub(r'malaysia_evidence=\{.*?available.*?False[^}]*\},\s*\n', '', content)
content = re.sub(r'malaysia_evidence=\{.*?available.*?True[^}]*\},\s*\n', '', content)

# Remove MALAYSIA_WEIGHT reference
content = content.replace('MALAYSIA_WEIGHT,', '')

# Fix risk_rules import test
old_risk_test = '''    def test_risk_rules_import(self):
        from backend.app.environment.flood.config.risk_rules import (
            MALAYSIA_WEIGHT,
            PUB_ALERT_HIGH_WEIGHT,
            PUB_ALERT_MODERATE_WEIGHT,
            PUB_MULTIPLE_ALERTS_BONUS,
            RISK_THRESHOLDS,
        )
        assert 0 < MALAYSIA_WEIGHT < 1
        assert 0 < PUB_ALERT_HIGH_WEIGHT < 1
        assert 0 < PUB_ALERT_MODERATE_WEIGHT < 1
        assert 0 < PUB_ALERT_LOW_WEIGHT < 1
        assert PUB_MULTIPLE_ALERTS_BONUS > 0
        assert RISK_THRESHOLDS["LOW"] == 0.0
        assert RISK_THRESHOLDS["MODERATE"] == 0.4
        assert RISK_THRESHOLDS["HIGH"] == 0.7
        assert RISK_THRESHOLDS["CRITICAL"] == 1.0
        assert RISK_THRESHOLDS["UNKNOWN"] == -1.0'''

new_risk_test = '''    def test_risk_rules_import(self):
        from backend.app.environment.flood.config.risk_rules import (
            PUB_ALERT_HIGH_WEIGHT,
            PUB_ALERT_MODERATE_WEIGHT,
            PUB_ALERT_LOW_WEIGHT,
            PUB_MULTIPLE_ALERTS_BONUS,
            RISK_THRESHOLDS,
        )
        assert 0 < PUB_ALERT_HIGH_WEIGHT < 1
        assert 0 < PUB_ALERT_MODERATE_WEIGHT < 1
        assert 0 < PUB_ALERT_LOW_WEIGHT < 1
        assert PUB_MULTIPLE_ALERTS_BONUS > 0
        assert RISK_THRESHOLDS["LOW"] == 0.0
        assert RISK_THRESHOLDS["MODERATE"] == 0.4
        assert RISK_THRESHOLDS["HIGH"] == 0.7
        assert RISK_THRESHOLDS["CRITICAL"] == 1.0
        assert RISK_THRESHOLDS["UNKNOWN"] == -1.0'''

with open(r'C:\projects\UrbanOS\tests\test_flood_agent_v3.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
'''from backend.app.environment.flood.agent import (
    FloodAgentState,
    create_flood_agent_v3,
    load_past_flood_events,
    fetch_singapore_rainfall,
    fetch_malaysia_rainfall,
    fetch_sumatra_forecast,
    fetch_pub_alerts,
    fetch_nea_weather,
    assess_risk,
    build_report,
    run_flood_agent_v3,
    _CATALOGUE_PATH,
    _analyze_singapore_rainfall,
    _analyze_nea_weather,
)''',
'''from backend.app.environment.flood.agent import (
    FloodAgentState,
    create_flood_agent_v3,
    load_past_flood_events,
    fetch_singapore_rainfall,
    fetch_sumatra_forecast,
    fetch_pub_alerts,
    fetch_nea_weather,
    assess_risk,
    build_report,
    run_flood_agent_v3,
    _CATALOGUE_PATH,
    _analyze_singapore_rainfall,
    _analyze_nea_weather,
)''')

content = content.replace(
'''from backend.app.environment.flood.config.risk_rules import (
    MALAYSIA_WEIGHT,
    PUB_ALERT_HIGH_WEIGHT,
    PUB_ALERT_MODERATE_WEIGHT,
    PUB_MULTIPLE_ALERTS_BONUS,
    RISK_THRESHOLDS,
)''',
'''from backend.app.environment.flood.config.risk_rules import (
    PUB_ALERT_HIGH_WEIGHT,
    PUB_ALERT_MODERATE_WEIGHT,
    PUB_ALERT_LOW_WEIGHT,
    PUB_MULTIPLE_ALERTS_BONUS,
    RISK_THRESHOLDS,
)''')

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

content = re.sub(r'def test_fetch_malaysia_rainfall_offline\(self\):.*?(?=\n    def test_)', '', content, flags=re.DOTALL)
content = re.sub(r'def test_assess_risk_malaysia_heavy_rainfall\(self\):.*?(?=\n    def test_)', '', content, flags=re.DOTALL)
content = re.sub(r'malaysia_evidence=\{.*?available.*?False[^}]*\},\s*\n', '', content)
content = re.sub(r'malaysia_evidence=\{.*?available.*?True[^}]*\},\s*\n', '', content)
content = content.replace('MALAYSIA_WEIGHT,', '')
content = content.replace(old_risk_test, new_risk_test)

with open(r'C:\projects\UrbanOS\tests\test_flood_agent_v3.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done!')