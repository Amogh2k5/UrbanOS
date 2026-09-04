"""Leakage-safe chronological split (spec §8.1).

Each forecast issuance is assigned to a split by `t0.date()` (per spec §8.1).
The splits live entirely inside the weather-feature intersection:
    train      2016-04-01 → 2021-12-31 23:00
    validation 2022-01-01 → 2023-06-30 23:00
    test       2023-07-01 → 2024-12-31 23:00

Leakage guards (spec §4, §8.3): every feature in a split row is computed from
data at-or-before t0; targets from strictly-after t0. These are enforced in
features.py; splits.py ONLY slices the row set by issuance_date.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import pandas as pd


@dataclass
class SplitInfo:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    val_start: pd.Timestamp
    val_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    train_rows: int
    val_rows: int
    test_rows: int
    train_dates: tuple
    val_dates: tuple
    test_dates: tuple

    def as_dict(self) -> dict:
        return {
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "val_start": self.val_start.isoformat(),
            "val_end": self.val_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
            "train_rows": self.train_rows,
            "val_rows": self.val_rows,
            "test_rows": self.test_rows,
            "train_dates": [d.isoformat() for d in self.train_dates],
            "val_dates": [d.isoformat() for d in self.val_dates],
            "test_dates": [d.isoformat() for d in self.test_dates],
        }


def _to_ts(s: str, end_of_day: bool = False) -> pd.Timestamp:
    """Parse a spec split-boundary string into a tz-aware Timestamp.

    The strings are date-only ("YYYY-MM-DD") or full ("YYYY-MM-DD HH:MM:SS") per the spec.
    All times are interpreted as Asia/Singapore.
    """
    ts = pd.Timestamp(s)
    if ts.tzinfo is None:
        ts = ts.tz_localize("Asia/Singapore")
    return ts


def split_modelling_df(
    df: pd.DataFrame,
    train_start: str,
    train_end: str,
    val_start: str,
    val_end: str,
    test_start: str,
    test_end: str,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, SplitInfo]:
    """Slice the modelling df by issuance_date into train/val/test.

    Boundaries are inclusive on both ends (per spec §8.1 table).
    """
    ts_train_start = _to_ts(train_start)
    ts_train_end = _to_ts(train_end)
    ts_val_start = _to_ts(val_start)
    ts_val_end = _to_ts(val_end)
    ts_test_start = _to_ts(test_start)
    ts_test_end = _to_ts(test_end)

    # issuance_date is a tz-aware date-at-midnight (00:00 Asia/Singapore) — so we compare by
    # comparing t0 (the actual issuance timestamp) against inclusive [start, end] windows.
    t0 = df["t0"]

    train_mask = (t0 >= ts_train_start) & (t0 <= ts_train_end)
    val_mask = (t0 >= ts_val_start) & (t0 <= ts_val_end)
    test_mask = (t0 >= ts_test_start) & (t0 <= ts_test_end)

    train_df = df.loc[train_mask].copy()
    val_df = df.loc[val_mask].copy()
    test_df = df.loc[test_mask].copy()

    def _dates_of(d: pd.DataFrame) -> tuple:
        if d.empty:
            return tuple()
        return tuple(sorted(d["issuance_date"].dt.tz_convert("Asia/Singapore").unique()))

    info = SplitInfo(
        train_start=ts_train_start,
        train_end=ts_train_end,
        val_start=ts_val_start,
        val_end=ts_val_end,
        test_start=ts_test_start,
        test_end=ts_test_end,
        train_rows=len(train_df),
        val_rows=len(val_df),
        test_rows=len(test_df),
        train_dates=_dates_of(train_df),
        val_dates=_dates_of(val_df),
        test_dates=_dates_of(test_df),
    )
    return train_df, val_df, test_df, info
