"""Leakage-safe feature + target builder for the Phase 1B Weather ML pipeline.

Per-row grain: one row per issuance_date D, where t0 = D 23:00 Asia/Singapore.
Targets: the *next-day* NEA 24h forecast issued at-or-after t0 (the day we want to
predict the NEA forecast for).

Reasoning (Phase 1B audit decision): the Weather 24h dataset is forecasts, not
observations. To produce a *predictable next-day weather target* *without
inventing observations*, we predict what NEA's next-day forecast fields will be,
given the history of NEA forecasts + recent PM2.5 observations (which are real
observations and carry haze/air-quality signal).

Specifically, for each t0 = D 23:00:
  Targets = the national fields of the latest NEA 24h forecast issued on day D+1
            (i.e. `timestamp ∈ [D+1 00:00, D+1 23:59]`). These fields cover the
            calendar day D+1 → D+2 window and represent the NEA next-day forecast.
            If no forecast was issued on D+1, the row is dropped (no target).

  Features = leakage-safe PM2.5 features from Phase 1's features.py + lagged
            NEA forecast fields (issues up to and including t0) + calendar
            features + monsoon flag.

This framing ensures the model supervises against actual NEA outputs, not
fabricated observations, and the prediction task is "what will NEA forecast
tomorrow for the day after?", which is exactly the inference an Environment Agent
needs (tomorrow's weather forecast, today).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
import pandas as pd


SG_TZ = "Asia/Singapore"
TARGET_HORIZON_HOURS = 24  # informational —Prediction horizon is 1 calendar day forward in issuance.

RAIN_CODES = {"RA", "SH", "PS", "TL", "LR", "LS", "HS", "HR", "HG"}
HAZE_CODES = {"HZ", "HG", "HR", "HS", "HT"}


def monsoon_flag(date: pd.Timestamp) -> str:
    m = date.month
    if m in (12, 1, 2, 3):
        return "NE"
    if m in (6, 7, 8, 9):
        return "SW"
    return "transitional"


@dataclass
class FeatureReport:
    rows: int
    feature_columns: List[str]
    target_columns: List[str]
    feature_null_counts: dict
    rows_with_target: int
    rows_missing_target: int


def _national_lag_features(
    national: pd.DataFrame,
    t0s: pd.DatetimeIndex,
    lags_days: Tuple[int, ...] = (1, 2, 7),
) -> pd.DataFrame:
    """Build lagged national forecast features at t0 — values from the latest issue
    with `timestamp <= t0 - N days + 23:00` for N in lags_days, plus the latest
    issue with `timestamp <= t0`.
    """
    nat = national.sort_values("timestamp").reset_index(drop=True)
    if nat["timestamp"].dt.tz is None:
        nat["timestamp"] = nat["timestamp"].dt.tz_localize(SG_TZ)
    else:
        nat["timestamp"] = nat["timestamp"].dt.tz_convert(SG_TZ)

    out_rows = []
    for t0 in t0s:
        row = {"t0": t0}
        # latest issue ≤ t0
        eligible = nat[nat["timestamp"] <= t0]
        if eligible.empty:
            out_rows.append(_null_lag_row(t0, lags_days))
            continue
        latest = eligible.sort_values("timestamp").iloc[-1]
        row.update(_nat_row_to_feat(latest, "wf_now"))  # the "current" NEA issue
        # lag N: latest issue whose `timestamp.day` is at least N calendar days before t0.day
        for n in lags_days:
            cutoff = t0.normalize() - pd.Timedelta(days=n) + pd.Timedelta(hours=23, minutes=59)
            elag = nat[nat["timestamp"] <= cutoff]
            if elag.empty:
                row.update(_null_lag_one(n))
            else:
                lrow = elag.sort_values("timestamp").iloc[-1]
                row.update(_nat_row_to_feat(lrow, f"wf_lag{n}"))
        out_rows.append(row)
    return pd.DataFrame(out_rows).set_index("t0")


def _nat_row_to_feat(latest: pd.Series, prefix: str) -> dict:
    return {
        f"{prefix}_temp_high": _num(latest, "temperature_high"),
        f"{prefix}_temp_low": _num(latest, "temperature_low"),
        f"{prefix}_rh_high": _num(latest, "relative_humidity_high"),
        f"{prefix}_rh_low": _num(latest, "relative_humidity_low"),
        f"{prefix}_wind_high": _num(latest, "wind_speed_high"),
        f"{prefix}_wind_low": _num(latest, "wind_speed_low"),
        f"{prefix}_wind_dir": _str(latest, "wind_speed_direction"),
        f"{prefix}_forecast_code": _str(latest, "forecast_code"),
        f"{prefix}_issue_ts": pd.Timestamp(latest["timestamp"]).isoformat(),
    }


def _num(row: pd.Series, col: str):
    val = row.get(col)
    if pd.isna(val):
        return np.nan
    return float(val)


def _str(row: pd.Series, col: str):
    val = row.get(col)
    if pd.isna(val):
        return None
    return str(val)


def _null_lag_row(t0: pd.Timestamp, lags_days) -> dict:
    row = {"t0": t0}
    row.update(_null_nat_block("wf_now"))
    for n in lags_days:
        row.update(_null_nat_block(f"wf_lag{n}"))
    return row


def _null_lag_one(n: int) -> dict:
    return _null_nat_block(f"wf_lag{n}")


def _null_nat_block(prefix: str) -> dict:
    return {
        f"{prefix}_temp_high": np.nan,
        f"{prefix}_temp_low": np.nan,
        f"{prefix}_rh_high": np.nan,
        f"{prefix}_rh_low": np.nan,
        f"{prefix}_wind_high": np.nan,
        f"{prefix}_wind_low": np.nan,
        f"{prefix}_wind_dir": None,
        f"{prefix}_forecast_code": None,
        f"{prefix}_issue_ts": None,
    }


def _build_targets(
    national: pd.DataFrame,
    t0s: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Build next-day weather targets.

    For each t0 = D 23:00, target = the latest NEA forecast *issued on day D+1*
    (i.e. `timestamp` in [D+1 00:00, D+1 23:59:59]). We use the latest such issue,
    since NEA may issue multiple forecasts that day. The fields taken are the
    `general` forecast extent (national temperature/RH/wind/forecast_code).
    """
    nat = national.sort_values("timestamp").reset_index(drop=True)
    if nat["timestamp"].dt.tz is None:
        nat["timestamp"] = nat["timestamp"].dt.tz_localize(SG_TZ)
    else:
        nat["timestamp"] = nat["timestamp"].dt.tz_convert(SG_TZ)

    out_rows = []
    for t0 in t0s:
        next_day_start = (t0 + pd.Timedelta(days=1)).normalize()
        next_day_end = next_day_start + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        elig = nat[(nat["timestamp"] >= next_day_start) & (nat["timestamp"] <= next_day_end)]
        if elig.empty:
            out_rows.append(_null_target_row(t0))
            continue
        latest = elig.sort_values("timestamp").iloc[-1]
        out_rows.append({
            "t0": t0,
            "temperature_high_next_day": _num(latest, "temperature_high"),
            "temperature_low_next_day": _num(latest, "temperature_low"),
            "relative_humidity_high_next_day": _num(latest, "relative_humidity_high"),
            "relative_humidity_low_next_day": _num(latest, "relative_humidity_low"),
            "wind_speed_high_next_day": _num(latest, "wind_speed_high"),
            "wind_speed_low_next_day": _num(latest, "wind_speed_low"),
            "forecast_code_next_day": _str(latest, "forecast_code"),
            "target_issue_ts": pd.Timestamp(latest["timestamp"]).isoformat(),
        })
    return pd.DataFrame(out_rows).set_index("t0")


def _null_target_row(t0: pd.Timestamp) -> dict:
    return {
        "t0": t0,
        "temperature_high_next_day": np.nan,
        "temperature_low_next_day": np.nan,
        "relative_humidity_high_next_day": np.nan,
        "relative_humidity_low_next_day": np.nan,
        "wind_speed_high_next_day": np.nan,
        "wind_speed_low_next_day": np.nan,
        "forecast_code_next_day": None,
        "target_issue_ts": None,
    }


def _pm25_features_for_weather(
    pm25_long: pd.DataFrame,
    t0s: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Aggregate PM2.5 features (national, all regions combined) at each t0.

    For the weather ML task we use national PM2.5 statistics (averaged across all
    5 regions) as features: pm25_nat_t0, lag 24h/72h, roll 24h mean/max. These
    are leakage-safe (computed only from observations with observed_at ≤ t0).
    """
    obs = pm25_long[["observed_at", "pm25_value"]].copy()
    if obs["observed_at"].dt.tz is None:
        obs["observed_at"] = obs["observed_at"].dt.tz_localize(SG_TZ)
    else:
        obs["observed_at"] = obs["observed_at"].dt.tz_convert(SG_TZ)
    obs = obs.sort_values("observed_at")
    # National = mean across regions at each observed hour
    nat_series = obs.groupby("observed_at")["pm25_value"].mean().sort_index()

    full_idx = pd.date_range(nat_series.index.min(), nat_series.index.max(), freq="h", tz=SG_TZ, name="observed_at")
    s = nat_series.reindex(full_idx)

    out_rows = []
    for t0 in t0s:
        out_rows.append({
            "t0": t0,
            "pm25_nat_t0": float(s.reindex([t0]).iloc[0]) if not s.reindex([t0]).empty else np.nan,
            "pm25_nat_lag_24h": float(s.reindex([t0 - pd.Timedelta(hours=24)]).iloc[0])
                                if not s.reindex([t0 - pd.Timedelta(hours=24)]).empty else np.nan,
            "pm25_nat_lag_72h": float(s.reindex([t0 - pd.Timedelta(hours=72)]).iloc[0])
                                if not s.reindex([t0 - pd.Timedelta(hours=72)]).empty else np.nan,
            "pm25_nat_roll24h_mean": float(s.rolling("24h", closed="right").mean().reindex([t0]).iloc[0])
                                     if not s.rolling("24h", closed="right").mean().reindex([t0]).empty else np.nan,
            "pm25_nat_roll24h_max": float(s.rolling("24h", closed="right").max().reindex([t0]).iloc[0])
                                    if not s.rolling("24h", closed="right").max().reindex([t0]).empty else np.nan,
        })
    return pd.DataFrame(out_rows).set_index("t0")


def build_modelling_dataset(
    national_weather: pd.DataFrame,
    pm25_long: pd.DataFrame,
    issuance_dates: pd.DatetimeIndex,
    forecast_hour: int = 23,
) -> Tuple[pd.DataFrame, FeatureReport]:
    """Build the leakage-safe modelling dataset for weather ML.

    Args:
        national_weather: output of `ml.phase1_pm25.ingest_weather.ingest_weather` (national df).
        pm25_long:        output of `ml.phase1_pm25.ingest_pm25.ingest_pm25` (long df).
        issuance_dates:   calendar dates D. t0 = D 23:00 Asia/Singapore.
        forecast_hour:    issuance hour (default 23 to match PM2.5 protocol).
    """
    t0s = pd.DatetimeIndex([
        (pd.Timestamp(d).tz_convert(SG_TZ) if pd.Timestamp(d).tzinfo is not None
          else pd.Timestamp(d).tz_localize(SG_TZ)).replace(hour=forecast_hour, minute=0, second=0)
        for d in issuance_dates
    ])

    lag_feats = _national_lag_features(national_weather, t0s)
    pm25_feats = _pm25_features_for_weather(pm25_long, t0s)
    targets = _build_targets(national_weather, t0s)

    df = lag_feats.join(pm25_feats, how="left").join(targets, how="left")

    # Calendar features (deterministic — no leakage)
    df["hour_of_day"] = df.index.hour
    df["day_of_week"] = df.index.dayofweek
    df["month"] = df.index.month
    df["is_weekend"] = (df["day_of_week"] >= 5).astype("int8")
    df["monsoon_flag"] = pd.Series(df.index).map(monsoon_flag).values
    df["issuance_date"] = df.index.tz_convert(SG_TZ).normalize()
    # Promote the t0 index to a regular column and use a default RangeIndex
    df = df.reset_index(drop=True)
    df["t0"] = df["issuance_date"] + pd.Timedelta(hours=forecast_hour)

    # Define the canonical feature column order (model input contract)
    feature_cols = [
        # PM2.5 national features
        "pm25_nat_t0",
        "pm25_nat_lag_24h", "pm25_nat_lag_72h",
        "pm25_nat_roll24h_mean", "pm25_nat_roll24h_max",
        # Calendar
        "hour_of_day", "day_of_week", "month", "is_weekend", "monsoon_flag",
        # NEA forecast — most recent issue ≤ t0
        "wf_now_temp_high", "wf_now_temp_low",
        "wf_now_rh_high", "wf_now_rh_low",
        "wf_now_wind_high", "wf_now_wind_low",
        "wf_now_wind_dir", "wf_now_forecast_code",
        # Lag 1 day
        "wf_lag1_temp_high", "wf_lag1_temp_low",
        "wf_lag1_rh_high", "wf_lag1_rh_low",
        "wf_lag1_wind_high", "wf_lag1_wind_low",
        "wf_lag1_wind_dir", "wf_lag1_forecast_code",
        # Lag 2 days
        "wf_lag2_temp_high", "wf_lag2_temp_low",
        "wf_lag2_rh_high", "wf_lag2_rh_low",
        "wf_lag2_wind_high", "wf_lag2_wind_low",
        "wf_lag2_wind_dir", "wf_lag2_forecast_code",
        # Lag 7 days
        "wf_lag7_temp_high", "wf_lag7_temp_low",
        "wf_lag7_rh_high", "wf_lag7_rh_low",
        "wf_lag7_wind_high", "wf_lag7_wind_low",
        "wf_lag7_wind_dir", "wf_lag7_forecast_code",
    ]
    target_cols = [
        "temperature_high_next_day",
        "temperature_low_next_day",
        "relative_humidity_high_next_day",
        "relative_humidity_low_next_day",
        "wind_speed_high_next_day",
        "wind_speed_low_next_day",
        "forecast_code_next_day",
        "target_issue_ts",
    ]

    ordered = ["issuance_date", "t0"] + target_cols + feature_cols
    # Only keep feature/target cols we declared; drop auxiliary lag issue_ts strings
    df = df[ordered]

    # Rows without a target are dropped (no supervision)
    rows_with_target = int(df["forecast_code_next_day"].notna().sum())
    rows_missing_target = int(df["forecast_code_next_day"].isna().sum())

    report = FeatureReport(
        rows=len(df),
        feature_columns=feature_cols,
        target_columns=target_cols,
        feature_null_counts={c: int(df[c].isna().sum()) for c in feature_cols},
        rows_with_target=rows_with_target,
        rows_missing_target=rows_missing_target,
    )
    return df, report
