"""Weather ML baselines (Phase 1B).

Three baselines, matching the PM2.5 spec §9 triad:
  W-A persistence        — next-day target = today's NEA forecast field (at-or-before t0)
  W-B climatological     — train-only historical mean by (month, day_of_week) bucket
  W-C trailing-7-day     — mean of target over last 7 forecast issuances at-or-before t0
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def baseline_persistence(
    full_df: pd.DataFrame,
    predict_df: pd.DataFrame,
    target: str,
    source_col: str = None,
) -> pd.Series:
    """Predict target = the NEA `source_col` (or persistence of the target) at/before t0.

    For regression targets, the source col is the same field in the latest NEA issue
    at t0 (e.g. wf_now_temp_high → predicts temperature_high_next_day). For the
    classification target (forecast_code_next_day), the source col is
    `wf_now_forecast_code`.
    """
    if source_col is None:
        # Default source = the matching "wf_now_*" field when present
        src_map = {
            "temperature_high_next_day": "wf_now_temp_high",
            "temperature_low_next_day": "wf_now_temp_low",
            "relative_humidity_high_next_day": "wf_now_rh_high",
            "relative_humidity_low_next_day": "wf_now_rh_low",
            "wind_speed_high_next_day": "wf_now_wind_high",
            "wind_speed_low_next_day": "wf_now_wind_low",
            "forecast_code_next_day": "wf_now_forecast_code",
        }
        source_col = src_map.get(target, target)

    return predict_df[source_col].astype("float64" if target != "forecast_code_next_day" else "object").values


def baseline_climatological(
    train_df: pd.DataFrame,
    predict_df: pd.DataFrame,
    target: str,
) -> pd.Series:
    """Predict target = train-only historical mean by (month, day_of_week) bucket.

    For the classification target, returns the *mode* per bucket (string).
    """
    t = train_df[[target, "month", "day_of_week"]].dropna(subset=[target]).copy()
    if t.empty:
        return pd.Series([np.nan] * len(predict_df))

    if target == "forecast_code_next_day":
        bucket = t["month"].astype(int).astype(str) + "_" + t["day_of_week"].astype(int).astype(str)
        t["_bucket"] = bucket
        # mode per bucket
        modes = t.groupby("_bucket")[target].agg(lambda s: s.mode().iloc[0] if not s.mode().empty else s.iloc[0])
        pred = predict_df.copy()
        pred["_bucket"] = pred["month"].astype(int).astype(str) + "_" + pred["day_of_week"].astype(int).astype(str)
        return pred["_bucket"].map(modes).values

    t["_bucket"] = t["month"].astype(int).astype(str) + "_" + t["day_of_week"].astype(int).astype(str)
    means = t.groupby("_bucket")[target].mean()
    pred = predict_df.copy()
    pred["_bucket"] = pred["month"].astype(int).astype(str) + "_" + pred["day_of_week"].astype(int).astype(str)
    return pred["_bucket"].map(means).values


def baseline_trailing_n(
    full_df: pd.DataFrame,
    predict_df: pd.DataFrame,
    target: str,
    n_days: int = 7,
) -> pd.Series:
    """Predict target = mean of target over last N forecast issuances at-or-before t0."""
    sub = full_df.sort_values("t0")
    t0s_naive = sub["t0"].dt.tz_localize(None).values.astype("datetime64[ns]")
    vals = sub[target].values

    pred_t0s = predict_df["t0"].dt.tz_localize(None).values.astype("datetime64[ns]")
    out = []
    for t0 in pred_t0s:
        ss = np.searchsorted(t0s_naive, t0, side="right")
        # Eligible issuances before current (= exclude current row in full_df, if same t0)
        eli = np.arange(ss)
        # Exclude last one (the row itself) — we want prior issuances only
        eli = eli[eli < ss - 1] if ss > 0 else eli
        if len(eli) == 0:
            out.append(np.nan)
            continue
        chunk = vals[eli[-n_days:]]
        chunk = chunk[~pd.isna(chunk)]
        if len(chunk) == 0:
            out.append(np.nan)
        elif target == "forecast_code_next_day":
            # mode
            from scipy.stats import mode as scimode  # local import; not used at module load
            m = pd.Series(chunk).mode()
            out.append(m.iloc[0] if not m.empty else np.nan)
        else:
            out.append(float(np.mean(chunk)))
    return np.array(out, dtype=object if target == "forecast_code_next_day" else float)
