"""Chronological split for the weather ML modelling dataset (Phase 1B).

Mirrors the Phase 1 PM2.5 split convention: split by `issuance_date` (calendar
date D of t0 = D 23:00 Asia/Singapore). Train → validation → test are contiguous,
non-overlapping windows. No shuffling.
"""

from __future__ import annotations

from typing import Tuple

import pandas as pd


SG_TZ = "Asia/Singapore"


def _parse(s: str) -> pd.Timestamp:
    ts = pd.Timestamp(s)
    if ts.tzinfo is None:
        ts = ts.tz_localize(SG_TZ)
    return ts


def split_modelling_df(
    df: pd.DataFrame,
    train_start: str,
    train_end: str,
    val_start: str,
    val_end: str,
    test_start: str,
    test_end: str,
    require_targets: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train_s = _parse(train_start).normalize()
    train_e = _parse(train_end)
    val_s = _parse(val_start).normalize()
    val_e = _parse(val_end)
    test_s = _parse(test_start).normalize()
    test_e = _parse(test_end)

    # Split on `issuance_date` (calendar date D of t0)
    idx = df["issuance_date"]
    train_mask = (idx >= train_s) & (idx <= train_e.normalize())
    val_mask = (idx >= val_s) & (idx <= val_e.normalize())
    test_mask = (idx >= test_s) & (idx <= test_e.normalize())

    train = df[train_mask].copy()
    val = df[val_mask].copy()
    test = df[test_mask].copy()

    if require_targets:
        # Drop rows without a usable target (no NEA forecast issued the next day)
        all_tgts = ["temperature_high_next_day", "forecast_code_next_day"]
        for sub, name in ((train, "train"), (val, "val"), (test, "test")):
            # Required: at least one regression target present
            pass  # filtering below
        train = train.dropna(subset=["temperature_high_next_day"]).copy()
        val = val.dropna(subset=["temperature_high_next_day"]).copy()
        test = test.dropna(subset=["temperature_high_next_day"]).copy()

    train = train.sort_values("t0").reset_index(drop=True)
    val = val.sort_values("t0").reset_index(drop=True)
    test = test.sort_values("t0").reset_index(drop=True)
    return train, val, test
