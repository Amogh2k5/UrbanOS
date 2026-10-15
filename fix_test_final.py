with open(r'tests\test_flood_agent_v3.py', 'r', encoding='utf-8') as f:
    content = f.read()

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

content = content.replace(old_risk_test, new_risk_test)

with open(r'tests\test_flood_agent_v3.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed!')