"""Leakage-safe feature builder (spec §3, §4, §5, §11A.1).

Builds the modelling dataset: one row per (issuance_date, region) where
issuance_date = calendar day D of `t0 = D 23:00 Asia/Singapore`.

Columns:
  issuance_date            — date of D (date, tz-aware); also used as split key
  region                   — one of REGIONS
  t0                       — full timestamp `D 23:00 Asia/Singapore` (tz-aware)
  pm25_next_day_mean       — regression target 1 = mean of PM2.5 over [t0+1h, t0+24h] for that region
  pm25_next_day_max        — regression target 2 = max  of PM2.5 over [t0+1h, t0+24h] for that region

And feature columns:
  pm25_t0                  — pm25_value at t0 (the hour the forecast is issued)
  pm25_lag_24h/48h/72h     — same region, same hour, prior-day values (audit §21-B.1)
  pm25_roll6h_mean/max     — rolling aggregates ending at t0 (audit §21-B.2)
  pm25_roll12h_mean/max
  pm25_roll24h_mean/max
  hour_of_day, day_of_week, month, is_weekend   — deterministic calendar features
  monsoon_flag             — NE/SW/transitional (simple NEA convention; spec VERIFY for exact windows)
  wf_temp_high/low, wf_rh_high/low, wf_wind_high/low, wf_wind_dir, wf_forecast_code
                           — national forecast fields representative of the target window (§5.2)
  wf_region_forecast_code  — the region-specific forecast_code for the target region's `[t0+1h,t0+24h]`
  wf_n_rain_codes          — count of rain-related codes (RA, SH, PS, TL, LR, LS, HS, HR, HG) over the target window
  wf_n_haze_codes          — count of haze-related codes (HZ, HG, HR, HS, HT) over the target window
  wf_window_coverage       — fraction of [t0+1h, t0+24h] hours inside any issued<=t0 forecast
  wf_n_issues_used         — number of distinct forecast issues contributing to target window
  wf_quality_flag          — 'ok' | 'year_offset_repaired' (carried from period table)

Leakage guards (spec §4, §8.3):
  - PM2.5 features computed only from rows with observed_at <= t0
  - Target labels computed only from rows with observed_at >  t0
  - Weather features only from forecasts with issue timestamp <= t0  (regardless of valid_period)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Tuple

import numpy as np
import pandas as pd


SG_TZ = "Asia/Singapore"
TARGET_HORIZON_HOURS = 24  # spec §1.2

RAIN_CODES = {"RA", "SH", "PS", "TL", "LR", "LS", "HS", "HR", "HG"}
HAZE_CODES = {"HZ", "HG", "HR", "HS", "HT"}

# NEA monsoon windows (spec VERIFY: NEA official definitions).
# Boreal winter NE monsoon: Dec–Mar; SW monsoon: Jun–Sep; transitional: Apr/May & Oct/Nov.
def monsoon_flag(date: pd.Timestamp) -> str:
    m = date.month
    if m in (12, 1, 2, 3):
        return "NE"
    if m in (6, 7, 8, 9):
        return "SW"
    return "transitional"


@dataclass
class FeatureReport:
    regional_rows: int  # # of (issuance_date, region) rows produced
    feature_columns: List[str]
    target_columns: List[str]
    feature_null_counts: dict
    rows_with_full_weather_coverage: int
    rows_with_partial_weather_coverage: int
    rows_with_no_weather_coverage: int


# ---------------------------------------------------------------------------
# PM2.5 feature engineering per-region
# ---------------------------------------------------------------------------

def _build_region_pm25_features(pm25_long: pd.DataFrame, region: str, t0s: pd.DatetimeIndex) -> pd.DataFrame:
    """For a single region, given a vector of `t0` timestamps, produce PM2.5 features.

    Returns DataFrame indexed by `t0` with columns: pm25_t0, pm25_lag_24h/48h/72h,
    pm25_roll6h_mean/max, pm25_roll12h_mean/max, pm25_roll24h_mean/max.

    Leakage safety: every lag/rolling statistic is computed over rows with observed_at <= t0
    (we set the rolling window time anchor to `t0` so that `t0+1h` and later are excluded).
    """
    # Restrict to one region, sort by time.
    df = pm25_long.loc[pm25_long["region"] == region, ["observed_at", "pm25_value"]].sort_values("observed_at")
    df = df.set_index("observed_at")

    # Build a uniform hourly series indexed by `observed_at` (with NaNs for the 4 missing hours,
    # per audit §21-A.4 "do not impute"). Reindexing against the full hourly grid makes the
    # lag math correct; we use skipna at the rolling step (min_periods=1).
    full_idx = pd.date_range(df.index.min(), df.index.max(), freq="h", tz=SG_TZ, name="observed_at")
    s = df["pm25_value"].reindex(full_idx)

    out = {}
    out["pm25_t0"] = s.reindex(t0s).values
    # Same-hour lags: subtract lag-hours from t0.
    for lag in (24, 48, 72):
        out[f"pm25_lag_{lag}h"] = s.reindex(t0s - pd.Timedelta(hours=lag)).values
    # Rolling stats ending at t0 INCLUSIVE of t0 (we want features known at t0).
    for win in (6, 12, 24):
        roll = s.rolling(f"{win}h", closed="right")
        roll_mean = roll.mean()
        roll_max = roll.max()
        out[f"pm25_roll{win}h_mean"] = roll_mean.reindex(t0s).values
        out[f"pm25_roll{win}h_max"] = roll_max.reindex(t0s).values

    feats = pd.DataFrame(out, index=pd.Index(t0s, name="t0"))
    return feats


# ---------------------------------------------------------------------------
# Targets per-region
# ---------------------------------------------------------------------------

def _build_region_targets(pm25_long: pd.DataFrame, region: str, t0s: pd.DatetimeIndex) -> pd.DataFrame:
    """For each t0, compute pm25_next_day_mean and pm25_next_day_max over [t0+1h, t0+24h].

    Targets are aggregated from PM2.5 observations strictly after t0 (leakage-safe by construction).
    If an hour in the window is missing (audit §15 — only 4 such hours in 12 years), we compute
    the mean over the available hours (audit §6: "downstream daily aggregation must tolerate them").
    A row is emitted only if at least 1 hour of the target window is present.
    """
    df = pm25_long.loc[pm25_long["region"] == region, ["observed_at", "pm25_value"]].sort_values("observed_at")
    df = df.set_index("observed_at")["pm25_value"]

    rows = []
    for t0 in t0s:
        window_start = t0 + pd.Timedelta(hours=1)
        window_end = t0 + pd.Timedelta(hours=TARGET_HORIZON_HOURS)
        # Slice observations strictly after t0 up to and including window_end.
        sub = df.loc[(df.index > t0) & (df.index <= window_end)]
        if len(sub) == 0:
            rows.append((np.nan, np.nan, 0))
            continue
        rows.append((float(sub.mean()), float(sub.max()), int(len(sub))))
    tgt = pd.DataFrame(
        rows,
        columns=["pm25_next_day_mean", "pm25_next_day_max", "n_target_hours_present"],
        index=pd.Index(t0s, name="t0"),
    )
    return tgt


# ---------------------------------------------------------------------------
# Weather alignment (spec §5.1, §5.2, §3.2 Group C/D)
# ---------------------------------------------------------------------------

def _align_weather_to_t0(
    national: pd.DataFrame,
    period: pd.DataFrame,
    region: str,
    t0s: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Build per-t0 weather features for one region.

    Spec §5: only forecasts with issue `timestamp <= t0` are eligible, and we want features that
    describe the target window [t0+1h, t0+24h] (the day we are forecasting).

    Vectorized implementation: precompute period boundaries + region codes as numpy arrays, then
    for each t0 use searchsorted on `timestamp` (eligible cutoff) and an interval algorithm over
    binary hour masks.
    """
    # ---- national table -----------------------------------------------------------------
    nat = national.sort_values("timestamp").reset_index(drop=True)
    nat_ts = nat["timestamp"].values.astype("datetime64[ns]")  # opaque tz-stripped for fast ops
    # We will keep tz-aware comparisons via Timestamp objects on the t0 side.

    # ---- period table --------------------------------------------------------------------
    per = period.sort_values("timestamp").reset_index(drop=True)
    per_ts = per["timestamp"].values.astype("datetime64[ns]")
    per_vps = per["valid_period_start"].values.astype("datetime64[ns]")
    per_vpe = per["valid_period_end"].values.astype("datetime64[ns]")
    per_region_code = per[f"{region}_forecast_code"].values
    per_dq = per["data_quality_flag"].values

    out_rows = []
    for t0 in t0s:
        t0_np = np.datetime64(t0.tz_convert("UTC").tz_localize(None).value, "ns")
        target_start = np.datetime64((t0 + pd.Timedelta(hours=1)).tz_convert("UTC").tz_localize(None).value, "ns")
        target_end = np.datetime64((t0 + pd.Timedelta(hours=24)).tz_convert("UTC").tz_localize(None).value, "ns")

        # Eligible national: latest issue with timestamp <= t0
        n_nat = np.searchsorted(nat_ts, t0_np, side="right")
        if n_nat == 0:
            out_rows.append(_null_weather_row(region, t0))
            continue
        latest_nat = nat.iloc[n_nat - 1]

        # Eligible period: timestamps <= t0 (and intersect target window)
        n_per = np.searchsorted(per_ts, t0_np, side="right")
        if n_per == 0:
            out_rows.append(_null_weather_row(region, t0))
            continue

        # Among the first n_per eligible periods, intersect with [target_start, target_end).
        vps_slice = per_vps[:n_per]
        vpe_slice = per_vpe[:n_per]
        ok = (vps_slice <= target_end) & (vpe_slice > target_start)
        if not ok.any():
            out_rows.append(_null_weather_row(region, t0))
            # NOTE but we DO still emit national features for these — keep going instead?
            # Spec: weather features include national fields; coverage feature reveals the gap.
            # Better: emit national features with coverage=0 rather than discard.
            out_rows[-1].update({
                "wf_temp_high": float(latest_nat["temperature_high"]),
                "wf_temp_low": float(latest_nat["temperature_low"]),
                "wf_rh_high": float(latest_nat["relative_humidity_high"]),
                "wf_rh_low": float(latest_nat["relative_humidity_low"]),
                "wf_wind_high": float(latest_nat["wind_speed_high"]),
                "wf_wind_low": float(latest_nat["wind_speed_low"]),
                "wf_wind_dir": latest_nat["wind_speed_direction"],
                "wf_forecast_code": latest_nat["forecast_code"],
                "wf_quality_flag": "ok",
            })
            continue

        # For each of the 24 target hours, find the winning issue = the LATEST timestamp among
        # overlapping periods. Use a (n_ok × 24) membership mask.
        ok_idx = np.nonzero(ok)[0]
        vps_ok = vps_slice[ok_idx]
        vpe_ok = vpe_slice[ok_idx]
        ts_ok = per_ts[:n_per][ok_idx]
        codes_ok = per_region_code[:n_per][ok_idx]
        dq_ok = per_dq[:n_per][ok_idx]

        # Build target_hours array (24)
        # Convert target_start to a python Timestamp for arithmetic.
        target_hours_ts = np.array(
            [np.datetime64((t0 + pd.Timedelta(hours=h + 1)).tz_convert("UTC").tz_localize(None).value, "ns")
             for h in range(24)]
        )

        # For each target hour, candidate mask: (vps_ok <= hour) & (vpe_ok > hour)
        latest_issue_per_hour = np.full(24, np.datetime64("", "ns"), dtype="datetime64[ns]")
        winning_code_per_hour = np.empty(24, dtype=object)
        covered_mask = np.zeros(24, dtype=bool)

        # Build hour-by-hour winner using argsort by ts descending; first overlap wins.
        ts_order_asc = np.argsort(ts_ok)
        ts_order_desc = ts_order_asc[::-1]
        vps_ord = vps_ok[ts_order_desc]
        vpe_ord = vpe_ok[ts_order_desc]
        codes_ord = codes_ok[ts_order_desc]
        ts_ord = ts_ok[ts_order_desc]
        for h, th in enumerate(target_hours_ts):
            hit = (vps_ord <= th) & (vpe_ord > th)
            if hit.any():
                covered_mask[h] = True
                latest_issue_per_hour[h] = ts_ord[hit][0]
                winning_code_per_hour[h] = codes_ord[hit][0]

        covered_hours = int(covered_mask.sum())
        n_issues_used = int(len(set(latest_issue_per_hour[covered_mask].tolist())))
        rain = int(sum(1 for c in winning_code_per_hour[covered_mask] if isinstance(c, str) and c in RAIN_CODES))
        haze = int(sum(1 for c in winning_code_per_hour[covered_mask] if isinstance(c, str) and c in HAZE_CODES))

        # Region code of first covered target hour
        if covered_mask.any():
            first_h = int(np.argmax(covered_mask))
            wf_region_code = winning_code_per_hour[first_h]
            if not isinstance(wf_region_code, str):
                wf_region_code = None
        else:
            wf_region_code = None

        wf_window_coverage = covered_hours / TARGET_HORIZON_HOURS

        # Period data-quality flag: propagate if any used period was year_offset_repaired
        per_qual = "year_offset_repaired" if (dq_ok == "year_offset_repaired").any() else "ok"

        out_rows.append({
            "t0": t0,
            "wf_temp_high": float(latest_nat["temperature_high"]),
            "wf_temp_low": float(latest_nat["temperature_low"]),
            "wf_rh_high": float(latest_nat["relative_humidity_high"]),
            "wf_rh_low": float(latest_nat["relative_humidity_low"]),
            "wf_wind_high": float(latest_nat["wind_speed_high"]),
            "wf_wind_low": float(latest_nat["wind_speed_low"]),
            "wf_wind_dir": latest_nat["wind_speed_direction"],
            "wf_forecast_code": latest_nat["forecast_code"],
            "wf_region_forecast_code": wf_region_code,
            "wf_n_rain_codes": rain,
            "wf_n_haze_codes": haze,
            "wf_window_coverage": float(wf_window_coverage),
            "wf_n_issues_used": n_issues_used,
            "wf_quality_flag": per_qual,
        })

    weather_df = pd.DataFrame(out_rows).set_index("t0")
    return weather_df


def _null_weather_row(region: str, t0: pd.Timestamp) -> dict:
    return {
        "t0": t0,
        "wf_temp_high": np.nan,
        "wf_temp_low": np.nan,
        "wf_rh_high": np.nan,
        "wf_rh_low": np.nan,
        "wf_wind_high": np.nan,
        "wf_wind_low": np.nan,
        "wf_wind_dir": None,
        "wf_forecast_code": None,
        "wf_region_forecast_code": None,
        "wf_n_rain_codes": 0,
        "wf_n_haze_codes": 0,
        "wf_window_coverage": np.nan,
        "wf_n_issues_used": 0,
        "wf_quality_flag": "no_weather",
    }


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------

def _per_region_pm25_features_for_all_regions(
    pm25_long: pd.DataFrame,
    regions: tuple,
    t0s: pd.DatetimeIndex,
) -> pd.DataFrame:
    parts = []
    for r in regions:
        feats = _build_region_pm25_features(pm25_long, r, t0s)
        feats["region"] = r
        feats = feats.reset_index()
        parts.append(feats)
    return pd.concat(parts, ignore_index=True)


def _per_region_targets_for_all_regions(
    pm25_long: pd.DataFrame,
    regions: tuple,
    t0s: pd.DatetimeIndex,
) -> pd.DataFrame:
    parts = []
    for r in regions:
        tgt = _build_region_targets(pm25_long, r, t0s)
        tgt["region"] = r
        tgt = tgt.reset_index()
        parts.append(tgt)
    return pd.concat(parts, ignore_index=True)


def _per_region_weather_for_all_regions(
    national: pd.DataFrame, period: pd.DataFrame, regions: tuple, t0s: pd.DatetimeIndex
) -> pd.DataFrame:
    parts = []
    for r in regions:
        w = _align_weather_to_t0(national, period, r, t0s)
        w["region"] = r
        w = w.reset_index()
        parts.append(w)
    return pd.concat(parts, ignore_index=True)


def build_modelling_dataset(
    pm25_long: pd.DataFrame,
    national_weather: pd.DataFrame,
    period_weather: pd.DataFrame,
    regions: tuple,
    issuance_dates: pd.DatetimeIndex,  # calendar dates D of t0=D 23:00 (date-only Timestamps)
    forecast_hour: int = 23,
) -> Tuple[pd.DataFrame, FeatureReport]:
    """Build the leakage-safe modelling dataset.

    Args:
      pm25_long: long-format PM2.5 observations (from ingest_pm25.ingest_pm25).
      national_weather, period_weather: from ingest_weather.ingest_weather.
      regions: tuple of region names.
      issuance_dates: calendar dates D. We will compute t0 = D 23:00 Asia/Singapore.

    Returns: (modelling_df, FeatureReport).
    """
    # Build t0 vector
    t0s = pd.DatetimeIndex([
        (pd.Timestamp(d).tz_convert(SG_TZ) if pd.Timestamp(d).tzinfo is not None
         else pd.Timestamp(d).tz_localize(SG_TZ)).replace(hour=forecast_hour, minute=0, second=0)
        for d in issuance_dates
    ])

    pm25_feats = _per_region_pm25_features_for_all_regions(pm25_long, regions, t0s)
    pm25_targets = _per_region_targets_for_all_regions(pm25_long, regions, t0s)
    weather_feats = _per_region_weather_for_all_regions(
        national_weather, period_weather, regions, t0s
    )

    # Merge on (region, t0)
    df = pm25_feats.merge(pm25_targets, on=["region", "t0"], how="inner")
    df = df.merge(weather_feats, on=["region", "t0"], how="left")

    # Add calendar features (deterministic — no leakage)
    df["hour_of_day"] = df["t0"].dt.hour
    df["day_of_week"] = df["t0"].dt.dayofweek  # 0=Mon
    df["month"] = df["t0"].dt.month
    df["is_weekend"] = (df["day_of_week"] >= 5).astype("int8")
    df["monsoon_flag"] = df["t0"].map(monsoon_flag)
    # issuance_date (date-only) — the split key (t0.date() per spec §8.1)
    df["issuance_date"] = df["t0"].dt.tz_convert(SG_TZ).dt.normalize()

    # Final column order
    target_cols = ["pm25_next_day_mean", "pm25_next_day_max", "n_target_hours_present"]
    feature_cols = [
        # PM2.5 lag/rolling
        "pm25_t0",
        "pm25_lag_24h", "pm25_lag_48h", "pm25_lag_72h",
        "pm25_roll6h_mean", "pm25_roll6h_max",
        "pm25_roll12h_mean", "pm25_roll12h_max",
        "pm25_roll24h_mean", "pm25_roll24h_max",
        # Calendar
        "hour_of_day", "day_of_week", "month", "is_weekend", "monsoon_flag",
        # Weather forecast features
        "wf_temp_high", "wf_temp_low", "wf_rh_high", "wf_rh_low",
        "wf_wind_high", "wf_wind_low", "wf_wind_dir",
        "wf_forecast_code", "wf_region_forecast_code",
        "wf_n_rain_codes", "wf_n_haze_codes",
        "wf_window_coverage", "wf_n_issues_used",
        "wf_quality_flag",
    ]
    ordered_cols = ["issuance_date", "region", "t0"] + target_cols + feature_cols
    df = df[ordered_cols]

    report = FeatureReport(
        regional_rows=len(df),
        feature_columns=feature_cols,
        target_columns=target_cols,
        feature_null_counts={c: int(df[c].isna().sum()) for c in feature_cols},
        rows_with_full_weather_coverage=int((df["wf_window_coverage"] == 1.0).sum()),
        rows_with_partial_weather_coverage=int(
            ((df["wf_window_coverage"] < 1.0) & (df["wf_window_coverage"] > 0)).sum()
        ),
        rows_with_no_weather_coverage=int((df["wf_window_coverage"].isna() | (df["wf_window_coverage"] == 0)).sum()),
    )
    return df, report
