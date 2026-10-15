with open(r'backend\app\environment\flood\agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the assess_risk function - risk_level is not defined in all code paths
# Find the assess_risk function and fix the risk_level assignment

# The issue is that risk_level is only defined in some branches
# Need to ensure risk_level is always defined before use

# Fix the risk_level assignment logic
old_risk_logic = '''        # --- MAP SCORE TO RISK LEVEL ---
        if risk_score >= RISK_THRESHOLDS["CRITICAL"]:
            risk_level = FloodRiskLevel.CRITICAL
        elif risk_score >= RISK_THRESHOLDS["HIGH"]:
            risk_level = FloodRiskLevel.HIGH
        elif risk_score >= RISK_THRESHOLDS["MODERATE"]:
            risk_level = FloodRiskLevel.MODERATE
        elif risk_score >= RISK_THRESHOLDS["LOW"]:
            risk_level = FloodRiskLevel.LOW
        else:
            risk_level = FloodRiskLevel.LOW

        # API unavailable handling
        if not sg_available and not my_available and not su_available and not pub_available:
            risk_level = FloodRiskLevel.UNKNOWN
            risk_factors.append("All primary data sources unavailable")

        state.risk_level = risk_level
        state.risk_score = min(risk_score, 2.0)  # Cap at 2.0
        state.primary_risk_factors = list(dict.fromkeys(risk_factors))  # Dedupe
        state.affected_zones = list(dict.fromkeys(affected_zones))

        log.info(f"Risk assessment: {risk_level.value} (score={risk_score:.2f})")
        for f in state.primary_risk_factors:
            log.debug(f"  Factor: {f}")

    except Exception as e:
        state.errors.append(f"Risk assessment failed: {e}")
        log.exception("Error assessing risk")

    return state'''

new_risk_logic = '''        # --- MAP SCORE TO RISK LEVEL ---
        if risk_score >= RISK_THRESHOLDS["CRITICAL"]:
            risk_level = FloodRiskLevel.CRITICAL
        elif risk_score >= RISK_THRESHOLDS["HIGH"]:
            risk_level = FloodRiskLevel.HIGH
        elif risk_score >= RISK_THRESHOLDS["MODERATE"]:
            risk_level = FloodRiskLevel.MODERATE
        elif risk_score >= RISK_THRESHOLDS["LOW"]:
            risk_level = FloodRiskLevel.LOW
        else:
            risk_level = FloodRiskLevel.LOW

        # API unavailable handling
        if not sg_available and not my_available and not su_available and not pub_available:
            risk_level = FloodRiskLevel.UNKNOWN
            risk_factors.append("All primary data sources unavailable")

        state.risk_level = risk_level
        state.risk_score = min(risk_score, 2.0)  # Cap at 2.0
        state.primary_risk_factors = list(dict.fromkeys(risk_factors))  # Dedupe
        state.affected_zones = list(dict.fromkeys(affected_zones))

        log.info(f"Risk assessment: {risk_level.value} (score={risk_score:.2f})")
        for f in state.primary_risk_factors:
            log.debug(f"  Factor: {f}")

    except Exception as e:
        state.errors.append(f"Risk assessment failed: {e}")
        log.exception("Error assessing risk")

    return state'''

with open(r'backend\app\environment\flood\agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(old_risk_logic, new_risk_logic)

with open(r'backend\app\environment\flood\agent.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed risk_level logic!')