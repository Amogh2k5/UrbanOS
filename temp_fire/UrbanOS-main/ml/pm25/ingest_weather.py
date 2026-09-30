"""Weather 24h forecast ingestion — two related tables per audit §16/§17.

Raw CSVs are never modified. Per-row grain is `(date, timestamp, time_period)` and region is a
column dimension (audit §7). We split into two tables:

  weather_forecast_national  — one row per (date, timestamp), national fields
  weather_forecast_period    — one row per (date, timestamp, time_period_start),
                                regional sub-period fields (one column per region S/N/E/C/W)

Year-offset bug (audit §15.4): `valid_period_start.year` ≠ `date.year` in 7 of 9 files
(≤7 rows each). Canonical year derived from `date`; affected rows flagged
`year_offset_repaired` in the period table.

Separator drift in `valid_period_text` (audit §13.4, §15.5): we DO NOT parse that text column.
All logic uses structured `valid_period_start`/`valid_period_end` timestamps.

Spec reference: docs/ml/PHASE1_PM25_ML_SPEC.md §2.2, §5.5, §11A.1.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from typing import List, Tuple

import pandas as pd


SG_TZ = "Asia/Singapore"

# National forecast fields (one value per issue — repeated across sub-period rows in source;
# we collapse them by taking the first row of each (date, timestamp) group).
NATIONAL_NUMERIC_COLS = [
    "wind_speed_high",
    "wind_speed_low",
    "relative_humidity_high",
    "relative_humidity_low",
    "temperature_high",
    "temperature_low",
]
NATIONAL_CATEGORICAL_COLS = [
    "wind_speed_direction",
    "forecast_text",
    "forecast_code",
]

# Regional sub-period fields — `{region}_forecast_text` / `{region}_forecast_code`.
REGION_COL_PREFIXES = ("south", "north", "east", "central", "west")


@dataclass
class WeatherIngestReport:
    n_files_read: int
    total_raw_rows: int
    national_rows: int
    period_rows: int
    year_offset_rows: int
    national_date_min: pd.Timestamp
    national_date_max: pd.Timestamp
    period_valid_min: pd.Timestamp
    period_valid_max: pd.Timestamp


def _read_all_files(weather_dir: str) -> pd.DataFrame:
    """Concatenate all yearly CSVs. Schema is stable (audit §3, §13)."""
    paths = sorted(glob.glob(os.path.join(weather_dir, "*.csv")))
    if not paths:
        raise FileNotFoundError(f"No Weather 24h CSVs found in {weather_dir}")
    frames = []
    for p in paths:
        # Use the filename year (e.g. "Historical 24-hour Weather Forecast (2017).csv")
        # purely for diagnostic context, not for logic.
        fname_year = os.path.basename(p)
        df = pd.read_csv(p)
        df["_source_file"] = fname_year
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def _parse_tz_aware(df: pd.DataFrame, col: str) -> pd.Series:
    """Parse a column known to be ISO-8601 with +08:00 offset."""
    s = pd.to_datetime(df[col], errors="coerce")
    if s.isna().any():
        n = int(s.isna().sum())
        raise ValueError(f"{col} -> {n} unparseable timestamps")
    if s.dt.tz is None:
        s = s.dt.tz_localize(SG_TZ)
    else:
        s = s.dt.tz_convert(SG_TZ)
    return s


def _fix_year_offset(period_df: pd.DataFrame) -> pd.DataFrame:
    """Flag and correct rows whose `valid_period_start.year` ≠ `date.year`.

    Audit §15.4: canonical year comes from `date`. We push affected timestamp columns
    to the year of `date`, preserving month/day/time. The correction is applied row-wise
    because `pd.DateOffset(years=...)` is not vectorizable on a Series with mixed offsets.
    However affected rows are ≤7/file per the audit (≤~40 total), so this is cheap.
    """
    period_df = period_df.copy()
    date_year = period_df["date"].dt.year
    vps_year = period_df["valid_period_start"].dt.year
    mask = date_year != vps_year
    n_off = int(mask.sum())

    period_df["data_quality_flag"] = "ok"
    period_df.loc[mask, "data_quality_flag"] = "year_offset_repaired"

    if n_off > 0:
        offset_years = (date_year[mask] - vps_year[mask]).values  # int array
        affected_idx = period_df.index[mask]
        for c in ("valid_period_start", "valid_period_end", "time_period_start", "time_period_end"):
            # Keep a Series aligned to affected_idx, shift each by its offset_years.
            shifted = []
            for i, dyv in zip(affected_idx, offset_years):
                ts = pd.Timestamp(period_df.at[i, c])
                shifted.append(ts + pd.DateOffset(years=int(dyv)))
            period_df.loc[affected_idx, c] = shifted
    return period_df


def ingest_weather(weather_dir: str) -> Tuple[pd.DataFrame, pd.DataFrame, WeatherIngestReport]:
    """End-to-end ingestion of Weather 24h forecasts.

    Returns:
        national_df — one row per (date, timestamp) carrying national forecast fields.
        period_df — one row per (date, timestamp, time_period_start) carrying regional
                    sub-period fields + a data_quality_flag.
        report — diagnostics.
    """
    raw = _read_all_files(weather_dir)
    n_files = raw["_source_file"].nunique()

    # Parse date and timestamps (all ISO-8601 with +08:00 per audit §6).
    raw["date"] = pd.to_datetime(raw["date"], format="%Y-%m-%d").dt.tz_localize(SG_TZ)
    for col in (
        "timestamp",
        "update_timestamp",
        "valid_period_start",
        "valid_period_end",
        "time_period_start",
        "time_period_end",
    ):
        raw[col] = _parse_tz_aware(raw, col)

    # --- national table: collapse sub-period rows onto their (date, timestamp).
    national = (
        raw.groupby(["date", "timestamp"], as_index=False)
        .first()[  # national fields are repeated across sub-period rows; first is correct
            ["date", "timestamp", "update_timestamp"]
            + NATIONAL_NUMERIC_COLS
            + NATIONAL_CATEGORICAL_COLS
        ]
    )

    # --- period table: one row per (date, timestamp, time_period_start) with regional cols.
    period_cols = (
        ["date", "timestamp", "update_timestamp", "valid_period_start", "valid_period_end",
         "time_period_start", "time_period_end", "time_period_text"]
        + [f"{r}_forecast_text" for r in REGION_COL_PREFIXES]
        + [f"{r}_forecast_code" for r in REGION_COL_PREFIXES]
    )
    period = raw[period_cols].copy()

    # Year-offset handling on the period table (audit §15.4).
    period = _fix_year_offset(period)
    n_off = int((period["data_quality_flag"] == "year_offset_repaired").sum())

    report = WeatherIngestReport(
        n_files_read=n_files,
        total_raw_rows=len(raw),
        national_rows=len(national),
        period_rows=len(period),
        year_offset_rows=n_off,
        national_date_min=national["date"].min(),
        national_date_max=national["date"].max(),
        period_valid_min=period["valid_period_start"].min(),
        period_valid_max=period["valid_period_end"].max(),
    )
    return national, period, report
