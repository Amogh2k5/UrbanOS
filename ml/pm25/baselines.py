"""Baselines per spec §9.

Three baselines, computed for both regression targets (pm25_next_day_mean, pm25_next_day_max):
  B-A persistence       — pm25 over last 24h ending at t0
  B-B climatological    — train-only historical mean by (month, day_of_week) bucket
  B-C trailing-7-day    — mean of target over last 7 forecast issuances

All are leakage-safe: every baseline only uses data available at-or-before t0.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def baseline_persistence(pm25_long: pd.DataFrame, region: str, t0s: pd.DatetimeIndex) -> pd.DataFrame:
    """Predict next-day mean/max = mean/max of last 24h ending at t0.

    Last 24h is the window (t0-24h, t0], i.e. observations with observed_at <= t0 and > t0-24h.
    Leakage-safe by construction.
    """
    sub = pm25_long.loc[pm25_long["region"] == region].set_index("observed_at")["pm25_value"]
    sub = sub.sort_index()

    rows = []
    for t0 in t0s:
        # inclusive of t0 because features use closed="right" semantics
        window = sub.loc[(sub.index > t0 - pd.Timedelta(hours=24)) & (sub.index <= t0)]
        if len(window) == 0:
            mean_p, max_p = np.nan, np.nan
        else:
            mean_p = float(window.mean())
            max_p = float(window.max())
        rows.append({"t0": t0, "pm25_next_day_mean": mean_p, "pm25_next_day_max": max_p})
    return pd.DataFrame(rows).set_index("t0")


def baseline_climatological(
    train_df: pd.DataFrame, region: str, predict_df: pd.DataFrame
) -> pd.DataFrame:
    """Predict target = train historical mean of target for (month, day_of_week) bucket.

    Leakage-safe: train used only; predictions do not see future data.
    """
    t = train_df.loc[train_df["region"] == region]
    if t.empty:
        # Return all-NaN. Preserve tz by constructing from the tz-aware Series ("t0" column).
        n = len(predict_df)
        return pd.DataFrame(
            {"pm25_next_day_mean": [np.nan] * n, "pm25_next_day_max": [np.nan] * n},
            index=pd.Index(predict_df["t0"], name="t0"),
        )

    # Build bucket key (month, day_of_week)
    bucket = (t["month"].astype(int).astype(str) + "_" + t["day_of_week"].astype(int).astype(str))
    t = t.assign(_bucket=bucket)
    bucket_means = t.groupby("_bucket")[["pm25_next_day_mean", "pm25_next_day_max"]].mean()

    # Apply to predict_df
    pred = predict_df.loc[predict_df["region"] == region].copy()
    pred["_bucket"] = pred["month"].astype(int).astype(str) + "_" + pred["day_of_week"].astype(int).astype(str)
    pred = pred.merge(bucket_means, left_on="_bucket", right_index=True, how="left",
                      suffixes=("", "_BL"))
    out = pred[["t0", "pm25_next_day_mean_BL", "pm25_next_day_max_BL"]].set_index("t0")
    out.columns = ["pm25_next_day_mean", "pm25_next_day_max"]
    return out


def baseline_trailing_n(
    full_df: pd.DataFrame, region: str, predict_df: pd.DataFrame, n_days: int = 7
) -> pd.DataFrame:
    """Predict target = mean of target over last N forecast issuances at-or-before t0.

    Uses the full available dataset but only AT-OR-BEFORE t0 (leakage-safe). For training-split
    rows this is in-sample (acceptable for a baseline; we report it transparently).

    TZ-safety note: we deliberately do NOT use `.values.astype('datetime64[ns]')` because that
    returns UTC wall-time stripped of the tz label — not the SGT wall-time we want. Instead,
    `.dt.tz_localize(None)` removes the tz label while keeping the SGT wall-clock values, so the
    subsequent `pd.Timestamp(..., tz="Asia/Singapore")` correctly re-labels them.
    """
    sub = full_df.loc[full_df["region"] == region].sort_values("t0")
    # Strip tz label only, preserving SGT wall-clock (so naive array = SGT wall-clock).
    t0s = sub["t0"].dt.tz_localize(None).values.astype("datetime64[ns]")
    means = sub["pm25_next_day_mean"].values
    maxs = sub["pm25_next_day_max"].values

    pred_t0s = predict_df.loc[predict_df["region"] == region, "t0"].dt.tz_localize(None).values.astype("datetime64[ns]")
    out_rows = []
    for t0 in pred_t0s:
        # Eligible issuances: t0 <= current t0
        mask = t0s <= t0
        # Take the last `n_days` (exclusive of the current one, since current's target is what we predict)
        eli = np.nonzero(mask)[0]
        ss = np.searchsorted(t0s, t0, side="right")
        eli = eli[eli < ss - 1]
        if len(eli) == 0:
            mean_p, max_p = np.nan, np.nan
        else:
            last_n = eli[-n_days:]
            chunk_mean = means[last_n]
            chunk_max = maxs[last_n]
            mean_p = float(np.nanmean(chunk_mean)) if not np.all(np.isnan(chunk_mean)) else np.nan
            max_p = float(np.nanmean(chunk_max)) if not np.all(np.isnan(chunk_max)) else np.nan
        # Re-attach Asia/Singapore tz label.
        out_rows.append({
            "t0": pd.Timestamp(t0).tz_localize("Asia/Singapore"),
            "pm25_next_day_mean": mean_p,
            "pm25_next_day_max": max_p,
        })
    return pd.DataFrame(out_rows).set_index("t0")
