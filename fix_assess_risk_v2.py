with open(r'backend\app\environment\flood\agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the assess_risk function - replace the entire try block
old_assess = '''    try:
        risk_score = 0.0
        risk_factors: List[str] = []
        affected_zones: List[str] = []

        # Track evidence availability
        sg_available = state.singapore_rainfall is not None and state.singapore_rainfall.is_live
        my_available = state.malaysia_evidence and state.malaysia_evidence.get("available")
        su_available = state.sumatra_rainfall is not None and state.sumatra_rainfall.is_live
        pub_available = len(state.pub_alerts) > 0
        nea_available = state.nea_weather is not None and state.nea_weather.is_live

        # --- SINGAPORE RAINFALL (PRIMARY SIGNAL) ---
        sg_evidence = _analyze_singapore_rainfall(state.singapore_rainfall)
        state.singapore_evidence = sg_evidence

        if sg_available:
            # Run prediction (uses 5-min live readings)
            max_5m = sg_evidence.get("peak_5m_mm", 0)
            stations_rain = sg_evidence.get("stations_with_rain", 0)
            stations_total = sg_evidence.get("stations_reporting", 0)

            # 5-minute intensity thresholds (direct from live API)
            if max_5m >= SINGAPORE_5M_EXTREME:
                risk_score += 0.75
                risk_factors.append(f"Extreme 5-min intensity: {max_5m:.1f}mm/5min (threshold: {SINGAPORE_5M_EXTREME}mm)")
            elif max_5m >= SINGAPORE_5M_HEAVY:
                risk_score += 0.5
                risk_factors.append(f"Heavy 5-min intensity: {max_5m:.1f}mm/5min (threshold: {SINGAPORE_5M_HEAVY}mm)")
            elif max_5m >= SINGAPORE_5M_MODERATE:
                risk_score += 0.25
                risk_factors.append(f"Moderate 5-min intensity: {max_5m:.1f}mm/5min (threshold: {SINGAPORE_5M_MODERATE}mm)")

            # Spatial coverage
            if stations_rain >= SINGAPORE_STATIONS_EXTENSIVE:
                risk_score += 0.2
                risk_factors.append(f"Extensive spatial coverage: {stations_rain}/{stations_total} stations with rain")
            elif stations_rain >= SINGAPORE_STATIONS_WIDESPREAD:
                risk_score += 0.1
                risk_factors.append(f"Widespread rainfall: {stations_rain}/{stations_total} stations with rain")

            risk_factors.append(f"Singapore: peak_5m={max_5m:.1f}mm, stations_wet={stations_rain}/{stations_total}")
        else:
            risk_factors.append("Singapore rainfall: UNAVAILABLE (offline or API error)")

        # --- MALAYSIA/JOHOR RAINFALL (SUPPORTING) ---
        my_evidence = state.malaysia_evidence or {}
        if my_available:
            max_1h = my_evidence.get("max_1h_mm", 0)
            if max_1h >= 50:
                risk_score += MALAYSIA_WEIGHT * 0.5
                risk_factors.append(f"Johor heavy rainfall: {max_1h:.1f}mm (weight: {MALAYSIA_WEIGHT})")
            elif max_1h >= 30:
                risk_score += MALAYSIA_WEIGHT * 0.2
                risk_factors.append(f"Johor moderate rainfall: {max_1h:.1f}mm")
        else:
            risk_factors.append(f"Malaysia/Johor rainfall: UNAVAILABLE ({my_evidence.get('error', 'no data')})")

        # --- SUMATRA FORECAST (SUPPORTING) ---
        su_snapshot = state.sumatra_rainfall
        if su_available:
            # Aggregate across all groups
            max_rain = 0.0
            has_rain_any = False
            for group in su_snapshot.groups.values():
                if group.has_rain:
                    has_rain_any = True
                if group.max_rainfall_mm > max_rain:
                    max_rain = group.max_rainfall_mm

            if max_rain >= 50:
                risk_score += SUMATRA_WEIGHT * 0.5
                risk_factors.append(f"Sumatra heavy rainfall: {max_rain:.1f}mm (weight: {SUMATRA_WEIGHT})")
            elif max_rain >= 30:
                risk_score += SUMATRA_WEIGHT * 0.2
                risk_factors.append(f"Sumatra moderate rainfall: {max_rain:.1f}mm")

            # Check for squall signature
            squall_groups = 0
            for group in su_snapshot.groups.values():
                if group.has_rain and group.max_rainfall_mm > 10:
                    squall_groups += 1

            if squall_groups >= 2:
                risk_score += SUMATRA_SQUALL_WEIGHT * 0.3
                risk_factors.append(f"Sumatra squall signature: {squall_groups} groups with rain (weight: {SUMATRA_SQUALL_WEIGHT})")

            risk_factors.append(f"Sumatra: max_rain={max_rain:.1f}mm, rain_groups={sum(1 for g in su_snapshot.groups.values() if g.has_rain)}")
        else:
            su_snapshot = state.sumatra_rainfall
            err_msg = getattr(su_snapshot, 'error', 'no data') if su_snapshot else 'no data'
            risk_factors.append(f"Sumatra forecast: UNAVAILABLE ({err_msg})")

        # --- REGIONAL WEATHER SYSTEMS (NEA 24h FORECAST) ---
        nea_evidence = _analyze_nea_weather(state.nea_weather)
        state.regional_weather_status = nea_evidence

        if nea_available:
            forecast_code = nea_evidence.get("forecast_code")
            wind_dir = nea_evidence.get("wind_direction")

            if forecast_code == "SQ":  # Sumatra Squall
                risk_score += SUMATRA_SQUALL_WEIGHT
                risk_factors.append(f"NEA forecast: Sumatra Squall (weight: {SUMATRA_SQUALL_WEIGHT})")
            elif forecast_code in ["TS", "TL", "TRW"]:  # Thunderstorms
                risk_score += 0.2
                risk_factors.append(f"NEA forecast: Thunderstorms ({forecast_code})")

            if wind_dir and wind_dir in ["SW", "WSW", "SSW"]:
                risk_score += 0.15
                risk_factors.append(f"SW wind direction: {wind_dir} (favors Sumatra squall approach)")

            # Monsoon surge detection (simplified)
            if forecast_code in ["MS", "MNS"] or "monsoon" in str(forecast_code).lower():
                risk_score += MONSOON_SURGE_WEIGHT
                risk_factors.append(f"Monsoon surge conditions (weight: {MONSOON_SURGE_WEIGHT})")
        else:
            risk_factors.append("Regional weather systems: UNAVAILABLE")

        # --- PUB ALERTS (CONFIRMATION) ---
        high_alerts = sum(1 for a in state.pub_alerts if a.get("severity", "").lower() == "high")
        moderate_alerts = sum(1 for a in state.pub_alerts if a.get("severity", "").lower() == "moderate")
        total_alerts = len(state.pub_alerts)

        if pub_available:
            for alert in state.pub_alerts:
                zone_name = alert.get("zone_name")
                if zone_name and zone_name != "unknown":
                    affected_zones.append(zone_name)

            if high_alerts > 0:
                risk_score += PUB_ALERT_HIGH_WEIGHT
                risk_factors.append(f"PUB HIGH alert(s): {high_alerts} (weight: {PUB_ALERT_HIGH_WEIGHT})")
            elif moderate_alerts > 0:
                risk_score += PUB_ALERT_MODERATE_WEIGHT
                risk_factors.append(f"PUB MODERATE alert(s): {moderate_alerts} (weight: {PUB_ALERT_MODERATE_WEIGHT})")
            elif total_alerts > 0:
                risk_score += PUB_ALERT_LOW_WEIGHT
                risk_factors.append(f"PUB alert(s): {total_alerts} (weight: {PUB_ALERT_LOW_WEIGHT})")

            if total_alerts >= 2:
                risk_score += PUB_MULTIPLE_ALERTS_BONUS * (total_alerts - 1)
                risk_factors.append(f"Multiple PUB alerts: +{PUB_MULTIPLE_ALERTS_BONUS * (total_alerts - 1):.2f} bonus")

        # --- MAP SCORE TO RISK LEVEL ---
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

    return state

new_assess = '''    try:
        risk_score = 0.0
        risk_factors: List[str] = []
        affected_zones: List[str] = []

        # Track evidence availability
        sg_available = state.singapore_rainfall is not None and state.singapore_rainfall.is_live
        su_available = state.sumatra_rainfall is not None and state.sumatra_rainfall.is_live
        pub_available = len(state.pub_alerts) > 0
        nea_available = state.nea_weather is not None and state.nea_weather.is_live

        # --- SINGAPORE RAINFALL (PRIMARY SIGNAL) ---
        sg_evidence = _analyze_singapore_rainfall(state.singapore_rainfall)
        state.singapore_evidence = sg_evidence

        if sg_available:
            # Run prediction (uses 5-min live readings)
            max_5m = sg_evidence.get("peak_5m_mm", 0)
            stations_rain = sg_evidence.get("stations_with_rain", 0)
            stations_total = sg_evidence.get("stations_reporting", 0)

            # 5-minute intensity thresholds (direct from live API)
            if max_5m >= SINGAPORE_5M_EXTREME:
                risk_score += 0.75
                risk_factors.append(f"Extreme 5-min intensity: {max_5m:.1f}mm/5min (threshold: {SINGAPORE_5M_EXTREME}mm)")
            elif max_5m >= SINGAPORE_5M_HEAVY:
                risk_score += 0.5
                risk_factors.append(f"Heavy 5-min intensity: {max_5m:.1f}mm/5min (threshold: {SINGAPORE_5M_HEAVY}mm)")
            elif max_5m >= SINGAPORE_5M_MODERATE:
                risk_score += 0.25
                risk_factors.append(f"Moderate 5-min intensity: {max_5m:.1f}mm/5min (threshold: {SINGAPORE_5M_MODERATE}mm)")

            # Spatial coverage
            if stations_rain >= SINGAPORE_STATIONS_EXTENSIVE:
                risk_score += 0.2
                risk_factors.append(f"Extensive spatial coverage: {stations_rain}/{stations_total} stations with rain")
            elif stations_rain >= SINGAPORE_STATIONS_WIDESPREAD:
                risk_score += 0.1
                risk_factors.append(f"Widespread rainfall: {stations_rain}/{stations_total} stations with rain")

            risk_factors.append(f"Singapore: peak_5m={max_5m:.1f}mm, stations_wet={stations_rain}/{stations_total}")
        else:
            risk_factors.append("Singapore rainfall: UNAVAILABLE (offline or API error)")

        # --- SUMATRA FORECAST (SUPPORTING) ---
        su_snapshot = state.sumatra_rainfall
        if su_available:
            # Aggregate speed across all groups
            max_rain = 0.0
            has_rain_any = False
            for group in su_snapshot.groups.values():
                if group.has_rain:
                    has_rain_any = True
                if group.max_rainfall_mm > max_rain:
                    max_rain = group.max_rainfall_mm

            if max_rain >= 50:
                risk_score += SUMATRA_WEIGHT * 0.5
                risk_factors.append(f"Sumatra heavy rainfall: {max_rain:.1f}mm (weight: {SUMATRA_WEIGHT})")
            elif max_rain >= 30:
                risk_score += SUMATRA_WEIGHT * 0.2
                risk_factors.append(f"Sumatra moderate rainfall: {max_rain:.1f}mm")

            # Check for squall signature
            squall_groups = 0
            for group in su_snapshot.groups.values():
                if group.has_rain and group.max_rainfall_mm > 10:
                    squall_groups += 1

            if squall_groups >= 2:
                risk_score += SUMATRA_SQUALL_WEIGHT * 0.3
                risk_factors.append(f"Sumatra squall signature: {squall_groups} groups with rain (weight: {SUMATRA_SQUALL_WEIGHT})")

            risk_factors.append(f"Sumatra: max_rain={max_rain:.1f}mm, rain_groups={sum(1 for g in su_snapshot.groups.values() if g.has_rain)}")
        else:
            su_snapshot = state.sumatra_rainfall
            err_msg = getattr(su_snapshot, 'error', 'no data') if su_snapshot else 'no data'
            risk_factors.append(f"Sumatra forecast: UNAVAILABLE ({err_msg})")

        # --- REGIONAL WEATHER SYSTEMS (NEA 24h FORECAST) ---
        nea_evidence = _analyze_nea_weather(state.nea_weather)
        state.regional_weather_status = nea_evidence

        if nea_available:
            forecast_code = nea_evidence.get("forecast_code")
            wind_dir = nea_evidence.get("wind_direction")

            if forecast_code == "SQ":  # Sumatra Squall
                risk_score += SUMATRA_SQUALL_WEIGHT
                risk_factors.append(f"NEA forecast: Sumatra Squall (weight: {SUMATRA_SQUALL_WEIGHT})")
            elif forecast_code in ["TS", "TL", "TRW"]:  # Thunderstorms
                risk_score += 0.2
                risk_factors.append(f"NEA forecast: Thunderstorms ({forecast_code})")

            if wind_dir and wind_dir in ["SW", "WSW", "SSW"]:
                risk_score += 0.15
                risk_factors.append(f"SW wind direction: {wind_dir} (favors Sumatra squall approach)")

            # Monsoon surge detection (simplified)
            if forecast_code in ["MS", "MNS"] or "monsoon" in str(forecast_code).lower():
                risk_score += MONSOON_SURGE_WEIGHT
                risk_factors.append(f"Monsoon surge conditions (weight: {MONSOON_SURGE_WEIGHT})")
        else:
            risk_factors.append("Regional weather systems: UNAVAILABLE")

        # --- PUB ALERTS (CONFIRMATION) ---
        high_alerts = sum(1 for a in state.pub_alerts if a.get("severity", "").lower() == "high")
        moderate_alerts = sum(1 for a in state.pub_alerts if a.get("severity", "").lower() == "moderate")
        total_alerts = len(state.pub_alerts)

        if pub_available:
            for alert in state.pub_alerts:
                zone_name = alert.get("zone_name")
                if zone_name and zone_name != "unknown":
                    affected_zones.append(zone_name)

            if high_alerts > 0:
                risk_score += PUB_ALERT_HIGH_WEIGHT
                risk_factors.append(f"PUB HIGH alert(s): {high_alerts} (weight: {PUB_ALERT_HIGH_WEIGHT})")
            elif moderate_alerts > 0:
                risk_score += PUB_ALERT_MODERATE_WEIGHT
                risk_factors.append(f"PUB MODERATE alert(s): {moderate_alerts} (weight: {PUB_ALERT_MODERATE_WEIGHT})")
            elif total_alerts > 0:
                risk_score += PUB_ALERT_LOW_WEIGHT
                risk_factors.append(f"PUB alert(s): {total_alerts} (weight: {PUB_ALERT_LOW_WEIGHT})")

            if total_alerts >= 2:
                risk_score += PUB_MULTIPLE_ALERTS_BONUS * (total_alerts - 1)
                risk_factors.append(f"Multiple PUB alerts: +{PUB_MULTIPLE_ALERTS_BONUS * (total_alerts - 1):.2f} bonus")

        # --- MAP SCORE TO RISK LEVEL ---
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
        if not sg_available and not su_available and not pub_available:
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

    return state

with open(r'backend\app\environment\flood\agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(old_assess, new_assess)

with open(r'backend\app\environment\flood\agent.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed assess_risk function!')