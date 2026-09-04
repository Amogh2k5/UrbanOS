"""Weather 24h ingestion helper + latest-forecast summary builder.

The NEA Weather 24h dataset contains *forecasts*, not observations. Per the project
Weather decision, UrbanOS consumes the NEA 24h forecast directly as the weather
information available to the Environment domain; no separate "weather prediction"
model is trained.

This module:
  1. Calls `ml.phase1_pm25.ingest_weather` (reuses the audit-compliant ingestion
     that handles the year-offset bug and the separator drift).
  2. Selects the latest NEA forecast issue with `timestamp <= t0` (matching the
     PM2.5 leakage-safe feature builder).
  3. Returns a WeatherForecastSummary structured result + per-target-window
     regional codes (for data_quality flags).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from backend.app.environment.result import WeatherForecastSummary
from ml.pm25.ingest_weather import ingest_weather

SG_TZ = "Asia/Singapore"
WEATHER_SOURCE = "NEA Historical24hourWeatherForecast"


@dataclass
class WeatherDiagnostics:
    n_files_read: int
    national_rows: int
    period_rows: int
    year_offset_rows: int
    has_forecast_at_t0: bool
    latest_issue_delta_hours: Optional[float]  # how stale latest issue is vs t0


def load_weather(weather_dir: Path):
    """Run ingestion. Returns (national_df, period_df, report)."""
    return ingest_weather(str(weather_dir))


def latest_forecast_summary(
    national: pd.DataFrame,
    t0: pd.Timestamp,
    period: Optional[pd.DataFrame] = None,
) -> Tuple[Optional[WeatherForecastSummary], Optional[pd.Timestamp]]:
    """Find the latest NEA forecast issue with `timestamp <= t0` and return its summary.

    The national table holds one row per `(date, timestamp)` with the national forecast
    fields (temp/RH/wind/code) but does NOT carry `valid_period_start/end` (those live in
    the period table). If `period` is provided, the latest issue's earliest valid_period_start
    and latest valid_period_end are joined into the summary.

    Returns (summary_or_None, latest_issue_timestamp_or_None).
    """
    if national.empty:
        return None, None

    # Ensure tz-aware
    ts_col = national["timestamp"]
    if ts_col.dt.tz is None:
        ts_col = ts_col.dt.tz_localize(SG_TZ)
    else:
        ts_col = ts_col.dt.tz_convert(SG_TZ)

    eligible = national[ts_col <= t0]
    if eligible.empty:
        return None, None

    latest = eligible.sort_values("timestamp").iloc[-1]
    latest_ts = pd.Timestamp(latest["timestamp"])

    # valid_period_* come from the period table for the same issue timestamp.
    vps = vpe = None
    if period is not None and not period.empty:
        per_ts = period["timestamp"]
        if per_ts.dt.tz is None:
            per_ts = per_ts.dt.tz_localize(SG_TZ)
        else:
            per_ts = per_ts.dt.tz_convert(SG_TZ)
        matching = period[per_ts == latest_ts]
        if not matching.empty:
            # Earliest valid_period_start and latest valid_period_end across
            # the sub-period rows for this issue: the full coverage window.
            start_vals = matching["valid_period_start"].dropna()
            end_vals = matching["valid_period_end"].dropna()
            if not start_vals.empty:
                vps = pd.Timestamp(start_vals.min())
                if vps.tzinfo is None:
                    vps = vps.tz_localize(SG_TZ)
                else:
                    vps = vps.tz_convert(SG_TZ)
            if not end_vals.empty:
                vpe = pd.Timestamp(end_vals.max())
                if vpe.tzinfo is None:
                    vpe = vpe.tz_localize(SG_TZ)
                else:
                    vpe = vpe.tz_convert(SG_TZ)

    summary = WeatherForecastSummary(
        source=WEATHER_SOURCE,
        forecast_issue_timestamp=latest_ts,
        valid_period_start=vps,
        valid_period_end=vpe,
        national_forecast_code=_str(latest, "forecast_code"),
        national_forecast_text=_str(latest, "forecast_text"),
        temperature_high_c=_num(latest, "temperature_high"),
        temperature_low_c=_num(latest, "temperature_low"),
        relative_humidity_high_pct=_num(latest, "relative_humidity_high"),
        relative_humidity_low_pct=_num(latest, "relative_humidity_low"),
        wind_speed_high_kmh=_num(latest, "wind_speed_high"),
        wind_speed_low_kmh=_num(latest, "wind_speed_low"),
        wind_direction=_str(latest, "wind_speed_direction"),
    )
    return summary, latest_ts


def _str(latest_row: pd.Series, col: str) -> Optional[str]:
    val = latest_row.get(col)
    if pd.isna(val):
        return None
    return str(val)


def _num(latest_row: pd.Series, col: str) -> Optional[float]:
    val = latest_row.get(col)
    if pd.isna(val):
        return None
    return float(val)
