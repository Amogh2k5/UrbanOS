"""
Flood Risk Rules Configuration — Derived from Historical Analysis

This module documents the manual risk thresholds used by the Flood Agent V3.
All thresholds are derived from historical NEA rainfall data (2020, 2021, 2024)
and documented flood events in the curated catalogue (78 events, 37 with rainfall data).

IMPORTANT:
- These are MVP operational rules, NOT statistically validated ML thresholds.
- Sample size is small (37 rainfall-documented flood events).
- Historical data has gaps and limitations (see calibration report).
- Rules should be recalibrated as more live data accumulates.

Source data:
- NEA 5-min rainfall: 2020 (550k records), 2021 (60k records), 2024 (150k records)
- Flood catalogue: 78 events (1954-2025), 37 with quantitative rainfall
- PUB expert panel reports, NEA Annual Climate Assessment Reports, news archives
"""

from dataclasses import dataclass
from typing import Literal


# ============================================================
# SINGAPORE RAINFALL THRESHOLDS
# ============================================================
# Derived from: 2020 extreme events (Jan 2020 monsoon surge, Jun 2020 Sumatra squall)
#               2021 moderate year (Aug 2021 IOD-driven)
#               2024 moderate year
#
# Flood events with 1h rainfall:
# - 2020-01-28/29: 86mm (S89), 80mm (S60), 76mm (S117) - widespread flash floods
# - 2020-04-30: 128mm/0.5h (256 mm/hr intensity) - Paya Lebar/Punggol
# - 2020-06-23: 67mm/1h (Sumatra squall) - Jurong/Bedok/Changi
# - 2020-08: 106mm/1h (Bedok South) - one of 6 days in 2020 with >70mm/1h
# - 2020-11-02: 131mm/3.5h - Upper Paya Lebar
# - 2021-08-24: 247mm/24h (Mandai) - IOD driver
# - 2022-02-27: 142mm/3.33h - Ubi/Eunos
# - 2022-10-05: 138mm (Sumatra squall) - Pasir Panjang
# - 2023-02-28: 225mm/24h (Kallang) - NE monsoon surge
# - 2024-05-04: 107mm/6h - Mountbatten/Tanjong Katong
# - 2025-04-20: 113mm/2.17h - Bukit Timah

# 1-hour rainfall thresholds (mm)
# Based on: 99.9th percentile of hourly rain = ~29mm (2020), flood events start ~30mm
SINGAPORE_1H_MODERATE = 30   # ~99th percentile; heavy rain warning
SINGAPORE_1H_HEAVY = 50      # Flood events observed; PUB flash flood threshold ~50-70mm
SINGAPORE_1H_EXTREME = 70    # Multiple flood events at 67-86mm/1h; "6 days in 2020 with >70mm"

# 3-hour rainfall thresholds (mm)
# 2020: max 3h = ~100mm during Jan 2020 event
# Flood events: 2020-11-02 (131mm/3.5h), 2022-02-27 (142mm/3.33h)
SINGAPORE_3H_MODERATE = 50
SINGAPORE_3H_HEAVY = 100
SINGAPORE_3H_EXTREME = 150

# 6-hour rainfall thresholds (mm)
# Flood events: 2024-05-04 (107mm/6h), 2025-04-20 (113mm/2.17h)
SINGAPORE_6H_MODERATE = 75
SINGAPORE_6H_HEAVY = 150
SINGAPORE_6H_EXTREME = 200

# 24-hour rainfall thresholds (mm)
# Widespread flood events: 2021-01-01 (318mm/48h), 2023-02-28 (225mm/24h), 2025-01-10 (241mm/24h)
SINGAPORE_24H_MODERATE = 100
SINGAPORE_24H_HEAVY = 200
SINGAPORE_24H_EXTREME = 300

# 5-minute rainfall intensity thresholds (mm per 5-min interval)
# 2020: max 5-min = 8.8mm (S115); 2024: max 5-min = 8.8mm (S115)
# These are DIRECT 5-minute readings, NOT extrapolated
SINGAPORE_5M_MODERATE = 3.0   # ~95th percentile of wet 5-min readings
SINGAPORE_5M_HEAVY = 5.0      # PUB flash flood proxy; 5mm/5min = 60mm/hr intensity
SINGAPORE_5M_EXTREME = 8.0    # Near maximum observed (8.8mm in 2020/2024)

# 15-minute rainfall thresholds (mm per 15-min interval) - for future use when historical aggregation available
SINGAPORE_15M_MODERATE = 10
SINGAPORE_15M_HEAVY = 20
SINGAPORE_15M_EXTREME = 30

# Spatial coverage thresholds (number of stations)
# 2020: max stations with rain in an hour = 50 (during Jan 2020 event)
# 2024: max = 63, mean wet hours = 23
SINGAPORE_STATIONS_WIDESPREAD = 20   # >=20 stations = widespread coverage
SINGAPORE_STATIONS_EXTENSIVE = 40    # >=40 stations = extensive coverage


# ============================================================
# REGIONAL WEATHER EVIDENCE WEIGHTS
# ============================================================
# Regional evidence is SUPPORTING ONLY — never automatically creates flood risk
# Weight: 0.0 (ignore) to 1.0 (strong confirmation)

# Malaysia/Johor rainfall evidence
MALAYSIA_WEIGHT = 0.3
MALAYSIA_1H_HEAVY = 50   # mm/1h in Johor
MALAYSIA_24H_HEAVY = 150 # mm/24h in Johor

# Sumatra/Strait of Malacca rainfall evidence
SUMATRA_WEIGHT = 0.3
SUMATRA_1H_HEAVY = 50
SUMATRA_24H_HEAVY = 150

# Regional wind/system evidence
# Sumatra squall detection (from NEA 24h forecast code "SQ")
SUMATRA_SQUALL_WEIGHT = 0.4
MONSOON_SURGE_WEIGHT = 0.4

# Wind direction evidence
# SW/WSW winds bring Sumatra squalls toward Singapore
WIND_SW_WEIGHT = 0.2


# ============================================================
# PUB ALERT WEIGHTS
# ============================================================
# Official PUB alerts are CONFIRMATION of current flooding
PUB_ALERT_HIGH_WEIGHT = 1.0      # HIGH severity alert -> HIGH risk
PUB_ALERT_MODERATE_WEIGHT = 0.7  # MODERATE alert -> MODERATE/HIGH risk
PUB_ALERT_LOW_WEIGHT = 0.5       # LOW/Minor alert -> MODERATE risk
PUB_MULTIPLE_ALERTS_BONUS = 0.2  # Additional per extra alert


# ============================================================
# RISK LEVEL MAPPING
# ============================================================
# Final risk score -> Risk Level
# Score is 0.0 to 1.0+ (can exceed 1.0 with multiple confirmations)

RISK_THRESHOLDS = {
    "LOW": 0.0,           # No significant evidence
    "MODERATE": 0.4,      # Some evidence (heavy rain or single alert)
    "HIGH": 0.7,          # Strong evidence (extreme rain, widespread, or HIGH alert)
    "CRITICAL": 1.0,      # Confirmed flooding (multiple HIGH alerts + extreme rain)
    "UNKNOWN": -1.0,      # API unavailable / insufficient data
}


# ============================================================
# RULE METADATA FOR DOCUMENTATION
# ============================================================

RULE_DOCUMENTATION = {
    "SINGAPORE_1H_MODERATE": {
        "threshold": SINGAPORE_1H_MODERATE,
        "unit": "mm",
        "window": "1 hour",
        "evidence": "99th percentile of hourly rainfall (2020-2024); ~30mm",
        "supporting_events": 12,
        "limitations": "Based on 3 years of station data; 2021 data sparse",
    },
    "SINGAPORE_1H_HEAVY": {
        "threshold": SINGAPORE_1H_HEAVY,
        "unit": "mm",
        "window": "1 hour",
        "evidence": "PUB flash flood threshold; multiple events at 50-70mm/1h (2020-2025)",
        "supporting_events": 8,
        "limitations": "PUB threshold not publicly specified; inferred from events",
    },
    "SINGAPORE_1H_EXTREME": {
        "threshold": SINGAPORE_1H_EXTREME,
        "unit": "mm",
        "window": "1 hour",
        "evidence": "6 days in 2020 with >70mm/1h causing floods; NEA ACAR 2020",
        "supporting_events": 6,
        "limitations": "Single year (2020) dominates; other years lack >70mm hours",
    },
    "SINGAPORE_3H_HEAVY": {
        "threshold": SINGAPORE_3H_HEAVY,
        "unit": "mm",
        "window": "3 hours",
        "evidence": "2020-11-02 (131mm/3.5h), 2022-02-27 (142mm/3.33h) caused floods",
        "supporting_events": 4,
        "limitations": "Few events with 3h duration data",
    },
    "SINGAPORE_24H_HEAVY": {
        "threshold": SINGAPORE_24H_HEAVY,
        "unit": "mm",
        "window": "24 hours",
        "evidence": "Widespread floods at 225-318mm/24h (2021, 2023, 2025)",
        "supporting_events": 5,
        "limitations": "Includes multi-day events; 24h vs 48h ambiguity",
    },
    "SINGAPORE_STATIONS_WIDESPREAD": {
        "threshold": SINGAPORE_STATIONS_WIDESPREAD,
        "unit": "stations",
        "window": "per hour",
        "evidence": "2020 Jan event: 50 stations with rain; 2024 mean wet hour: 23 stations",
        "supporting_events": 3,
        "limitations": "Station network expanded over time (64 stations in 2024)",
    },
}

# Calibration metadata
CALIBRATION_METADATA = {
    "analysis_date": "2026-08-20",
    "data_sources": [
        "NEA 5-min rainfall: 2020 (550k records, 64 stations), 2021 (60k), 2024 (150k)",
        "Flood catalogue v0.5: 78 events (1954-2025), 37 with quantitative rainfall",
        "NEA Annual Climate Assessment Reports: 2015-2025",
        "PUB Expert Panel Reports, Press Releases, Clarifications",
    ],
    "sample_sizes": {
        "total_flood_events": 78,
        "rainfall_documented": 37,
        "flash_flood_with_rainfall": 29,
        "widespread_flood_with_rainfall": 5,
        "infrastructure_flood": 3,
    },
    "limitations": [
        "Small sample size (37 events with rainfall data) — not statistically robust",
        "2021 and 2024 NEA datasets appear incomplete (60k and 150k vs 550k for 2020)",
        "Station network changed over time (64 stations in 2024 vs fewer historically)",
        "Rainfall duration/intensity often missing from historical reports",
        "Infrastructure floods (3 events) have 0mm rainfall — excluded from rainfall rules",
        "Spatial coverage analysis limited by station density and reporting consistency",
        "No non-flood heavy rainfall events catalogued for comparison (false positive rate unknown)",
        "Thresholds are operational approximations — require live validation",
    ],
    "recommendations": [
        "Recalibrate after 6 months of live API data",
        "Obtain complete NEA historical dataset (paid API) for 2015-2025",
        "Catalogue non-flood heavy rainfall events to estimate false positive rate",
        "Integrate PUB drain water level sensors when available",
        "Validate regional API access for Malaysia/Johor and Sumatra/BMKG",
    ],
}


@dataclass(frozen=True)
class SingaporeRainfallRule:
    """Single Singapore rainfall rule with metadata."""
    name: str
    window: str
    moderate: float
    heavy: float
    extreme: float
    unit: str = "mm"


@dataclass(frozen=True)
class RegionalRule:
    """Regional weather evidence rule."""
    name: str
    source: str
    weight: float
    heavy_threshold: float
    unit: str = "mm"


SINGAPORE_RAINFALL_RULES = [
    SingaporeRainfallRule("1h", "1 hour", SINGAPORE_1H_MODERATE, SINGAPORE_1H_HEAVY, SINGAPORE_1H_EXTREME),
    SingaporeRainfallRule("3h", "3 hours", SINGAPORE_3H_MODERATE, SINGAPORE_3H_HEAVY, SINGAPORE_3H_EXTREME),
    SingaporeRainfallRule("6h", "6 hours", SINGAPORE_6H_MODERATE, SINGAPORE_6H_HEAVY, SINGAPORE_6H_EXTREME),
    SingaporeRainfallRule("24h", "24 hours", SINGAPORE_24H_MODERATE, SINGAPORE_24H_HEAVY, SINGAPORE_24H_EXTREME),
    SingaporeRainfallRule("15m", "15 minutes", SINGAPORE_15M_MODERATE, SINGAPORE_15M_HEAVY, SINGAPORE_15M_EXTREME),
    SingaporeRainfallRule("5m", "5 minutes", SINGAPORE_5M_MODERATE, SINGAPORE_5M_HEAVY, SINGAPORE_5M_EXTREME),
]

REGIONAL_RULES = [
    RegionalRule("Johor Rainfall", "met.gov.my", MALAYSIA_WEIGHT, MALAYSIA_1H_HEAVY),
    RegionalRule("Sumatra Rainfall", "data.bmkg.go.id", SUMATRA_WEIGHT, SUMATRA_1H_HEAVY),
    RegionalRule("Sumatra Squall", "NEA 24h forecast", SUMATRA_SQUALL_WEIGHT, 1.0, "boolean"),
    RegionalRule("Monsoon Surge", "NEA 24h forecast", MONSOON_SURGE_WEIGHT, 1.0, "boolean"),
    RegionalRule("SW Wind", "NEA live weather", WIND_SW_WEIGHT, 1.0, "boolean"),
]

PUB_ALERT_RULES = {
    "HIGH": PUB_ALERT_HIGH_WEIGHT,
    "Moderate": PUB_ALERT_MODERATE_WEIGHT,
    "Low": PUB_ALERT_LOW_WEIGHT,
}