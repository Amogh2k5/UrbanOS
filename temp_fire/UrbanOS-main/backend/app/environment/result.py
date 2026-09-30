"""Structured Environment result types (architecture proposal §2 envelope contract).

The output of `EnvironmentModule.run()` is an `EnvironmentReport`, which is the
*environment* domain agent envelope. It is a pure data object: prediction logic
lives in `pm25_predictor.py`, presentation/serialization lives here.

Envelope fields mirror the proposal §2 recommendation contract:
    domain, timestamp, scope, current_state, prediction, evidence,
    schema_version, plus environment-specific `data_quality_flags`.

All datetime fields are tz-aware Asia/Singapore (+08:00) per AGENTS.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

SG_TZ = "Asia/Singapore"
SCHEMA_VERSION = "1.0"


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        from pytz import timezone  # local import; optional dependency
        return timezone(SG_TZ).localize(dt).isoformat()
    return dt.isoformat()


@dataclass
class WeatherForecastSummary:
    """Summary of the NEA 24h forecast covering the target window."""
    source: str  # "NEA Historical24hourWeatherForecast"
    forecast_issue_timestamp: Optional[datetime]   # NEA `timestamp` of latest eligible issue
    valid_period_start: Optional[datetime]        # NEA `valid_period_start` of latest eligible issue
    valid_period_end: Optional[datetime]          # NEA `valid_period_end`   of latest eligible issue
    national_forecast_code: Optional[str]          # `forecast_code` (national)
    national_forecast_text: Optional[str]          # `forecast_text` (national, human readable)
    temperature_high_c: Optional[float]           # °C, NEA convention (assumed, VERIFY per audit)
    temperature_low_c: Optional[float]
    relative_humidity_high_pct: Optional[float]    # %
    relative_humidity_low_pct: Optional[float]
    wind_speed_high_kmh: Optional[float]           # km/h, NEA convention (assumed, VERIFY per audit)
    wind_speed_low_kmh: Optional[float]
    wind_direction: Optional[str]                  # 16-point compass or "VARIABLE"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "forecast_issue_timestamp": _iso(self.forecast_issue_timestamp),
            "valid_period_start": _iso(self.valid_period_start),
            "valid_period_end": _iso(self.valid_period_end),
            "national_forecast_code": self.national_forecast_code,
            "national_forecast_text": self.national_forecast_text,
            "temperature_high_c": self.temperature_high_c,
            "temperature_low_c": self.temperature_low_c,
            "relative_humidity_high_pct": self.relative_humidity_high_pct,
            "relative_humidity_low_pct": self.relative_humidity_low_pct,
            "wind_speed_high_kmh": self.wind_speed_high_kmh,
            "wind_speed_low_kmh": self.wind_speed_low_kmh,
            "wind_direction": self.wind_direction,
        }


@dataclass
class RegionPrediction:
    """One region's PM2.5 prediction (next-day mean + max)."""
    region: str
    selected_model: str  # "catboost" | "bl_persist"
    is_ml_model: bool    # False for persistence fallback
    pm25_next_day_mean: Optional[float]
    pm25_next_day_max: Optional[float]
    # Per-target provenance
    target_models: Dict[str, str] = field(default_factory=dict)
    # The PM2.5 value at t0 used as the persistence fallback (when persistence wins a target).
    persistence_value_pm25_t0: Optional[float] = None
    # Tie-break audit: if a target fell back to persistence because no ML beat it on val.
    fallback_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "region": self.region,
            "selected_model": self.selected_model,
            "is_ml_model": self.is_ml_model,
            "pm25_next_day_mean": self.pm25_next_day_mean,
            "pm25_next_day_max": self.pm25_next_day_max,
            "target_models": dict(self.target_models),
            "persistence_value_pm25_t0": self.persistence_value_pm25_t0,
            "fallback_reason": self.fallback_reason,
        }


@dataclass
class EnvironmentReport:
    """Environment domain agent envelope (proposal §2)."""
    domain: str = "environment"
    schema_version: str = SCHEMA_VERSION
    generated_at: Optional[datetime] = None        # when this report was produced
    prediction_timestamp: Optional[datetime] = None # t0 = D 23:00 Asia/Singapore (issuance)
    forecast_date: Optional[datetime] = None        # calendar date D of issuance
    target_window_start: Optional[datetime] = None  # t0 + 1h
    target_window_end: Optional[datetime] = None    # t0 + 24h

    regions: List[RegionPrediction] = field(default_factory=list)

    weather_forecast: Optional[WeatherForecastSummary] = None

    data_quality_flags: List[str] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)

    # Provenance — what artifacts and ingesters were used
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "schema_version": self.schema_version,
            "generated_at": _iso(self.generated_at),
            "scope": {
                "prediction_timestamp": _iso(self.prediction_timestamp),
                "forecast_date": _iso(self.forecast_date),
                "target_window_start": _iso(self.target_window_start),
                "target_window_end": _iso(self.target_window_end),
                "regions": [r.region for r in self.regions],
            },
            "current_state": {
                "weather_forecast": self.weather_forecast.to_dict() if self.weather_forecast else None,
            },
            "prediction": {
                "regions": [r.to_dict() for r in self.regions],
            },
            "data_quality_flags": list(self.data_quality_flags),
            "evidence": list(self.evidence),
            "provenance": dict(self.provenance),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str, ensure_ascii=False)


def utcnow_sg() -> datetime:
    """Now in Asia/Singapore, tz-aware."""
    from datetime import timezone
    # +08:00 fixed offset is sufficient and avoids pytz/zoneinfo availability concerns.
    return datetime.now(timezone.utc).astimezone(_sg_offset())


def _sg_offset():
    from datetime import timezone, timedelta
    return timezone(timedelta(hours=8), name="Asia/Singapore")
