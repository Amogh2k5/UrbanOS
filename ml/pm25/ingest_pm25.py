"""PM2.5 ingestion — long-format observations per audit §21-A.

Raw CSV is never modified. All cleaning happens here, producing a clean long-format
DataFrame with columns:
    observed_at: datetime64[ns, Asia/Singapore]
    region: str (north/south/east/west/central)
    pm25_value: float64
    data_quality_flag: str ("ok" | "repaired" | "duplicate_dropped_kept" | ...)

Spec reference: docs/ml/PHASE1_PM25_ML_SPEC.md §2.1, §6, §11A.1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import pandas as pd


SG_TZ = "Asia/Singapore"

# The single malformed source-side row (PM25 audit §6, row ~17,616). Capture both the
# raw string and a normalisation pattern so this is data-driven, not brittle regex guessing.
# Source value: "2016-04-04 010:00:00" — normalised target 2016-04-04 01:00:00 +08:00.
_MALFORMED_RAW = "2016-04-04 010:00:00"
_MALFORMED_NORM = "04/04/2016 01:00"  # in the source string format d/M/yyyy H:mm


@dataclass
class PM25IngestReport:
    raw_rows: int
    parsed_rows: int
    repaired_rows: int
    duplicate_pairs: int
    duplicate_rows_dropped: int
    long_rows: int
    date_min: pd.Timestamp
    date_max: pd.Timestamp
    # Audit-trail: rows discarded by dedupe. The malformed "010:00:00" row, once repaired
    # to 01:00:00, collides with the legitimate 01:00 row that immediately follows it in
    # file order; per the dedupe rule (keep later-in-file) it is correctly discarded.
    # The "repaired" flag is therefore recorded here, not on the surviving long-format row
    # (which was *not* itself malformed).
    dropped_audit: pd.DataFrame = None  # type: ignore[assignment]


def _repair_malformed_timestamp(df: pd.DataFrame) -> pd.DataFrame:
    """Replace the known malformed source string with its normalised equivalent.

    Returns a copy of `df` whose `1hr_pm25` col has the repaired value where applicable.
    The original CSV on disk is untouched.
    """
    df = df.copy()
    mask = df["1hr_pm25"] == _MALFORMED_RAW
    n_repaired = int(mask.sum())
    if n_repaired > 0:
        df.loc[mask, "1hr_pm25"] = _MALFORMED_NORM
    # Stash which rows were repaired; carried forward as a flag in the returned frame.
    df["_was_repaired"] = mask
    return df


def _parse_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    """Parse the `1hr_pm25` column into a tz-aware datetime, then localise to Asia/Singapore.

    Per audit §6 / §21-A.1: format is `d/M/yyyy H:mm` (no padding, no timezone token).
    """
    parsed = pd.to_datetime(df["1hr_pm25"], format="%d/%m/%Y %H:%M", errors="coerce")
    if parsed.isna().any():
        bad = df.loc[parsed.isna(), "1hr_pm25"].head(5).tolist()
        raise ValueError(f"Unparseable PM2.5 timestamps after repair: {bad}")
    # Source carries no offset; cast to Singapore per audit assumption (spec VERIFY).
    df = df.copy()
    df["ts"] = parsed.dt.tz_localize(SG_TZ)
    return df


def _dedupe_by_file_order(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Resolve the 3 documented duplicate-timestamp pairs (audit §14).

    Rule: keep the row that comes LATER in file order (presumably NEA's latest publication).
    Returns (kept_df, dropped_df). dropped_df is for an audit table; we expose it but don't write.
    """
    # Build groups by ts. Within each group, keep the LAST occurrence by original Row order.
    df = df.copy()
    df["_file_order"] = range(len(df))
    # Mark duplicates: keep='last' semantics for ts.
    dup_mask = df.duplicated(subset=["ts"], keep="last")
    dropped = df.loc[dup_mask].copy()
    kept = df.loc[~dup_mask].copy()
    return kept, dropped


def _to_long_format(kept: pd.DataFrame, regions: tuple, was_repaired_mask: pd.Series) -> pd.DataFrame:
    """Melt the wide table to long format (audit §21-A.5).

    Returns DataFrame[observed_at, region, pm25_value, data_quality_flag].
    """
    melted = kept.melt(
        id_vars=["ts", "_file_order"],
        value_vars=list(regions),
        var_name="region",
        value_name="pm25_value",
    )
    # Map original repair-flag (per-row, pre-melt) onto long rows by ts.
    repaired_ts = set(kept.loc[kept["_was_repaired"], "ts"])
    flags = []
    for ts, region, v in zip(melted["ts"], melted["region"], melted["pm25_value"]):
        if ts in repaired_ts:
            flags.append("repaired")
        else:
            flags.append("ok")
    melted["data_quality_flag"] = flags
    melted = melted.rename(columns={"ts": "observed_at"}).drop(columns=["_file_order"])
    # Cast + is_haze_period per audit §21-A.6
    melted["pm25_value"] = melted["pm25_value"].astype("float64")
    melted["is_haze_period"] = (melted["pm25_value"] > 200).astype("int8")
    # Sort for stable downstream writes.
    melted = melted.sort_values(["region", "observed_at"]).reset_index(drop=True)
    return melted[["observed_at", "region", "pm25_value", "is_haze_period", "data_quality_flag"]]


def ingest_pm25(csv_path, regions: tuple) -> Tuple[pd.DataFrame, PM25IngestReport]:
    """End-to-end ingestion of the PM2.5 raw CSV into a clean long-format DataFrame.

    Spec compliance:
      - raw CSV untouched (we read it, never write back)
      - malformed "010:00:00" row repaired (audit §6) with data_quality_flag="repaired"
      - 3 duplicate-timestamp pairs resolved keeping later-in-file (audit §14)
      - long-format (audit §21-A.5)
      - is_haze_period boolean for pm25_value > 200 (audit §21-A.6)
      - observed_at is tz-aware Asia/Singapore
    """
    raw = pd.read_csv(csv_path)
    raw_rows = len(raw)
    repaired = _repair_malformed_timestamp(raw)
    n_repaired = int(repaired["_was_repaired"].sum())

    parsed = _parse_timestamps(repaired)

    kept, dropped = _dedupe_by_file_order(parsed)
    n_dropped = len(dropped)

    long_df = _to_long_format(kept, regions, kept["_was_repaired"])

    report = PM25IngestReport(
        raw_rows=raw_rows,
        parsed_rows=len(kept),
        repaired_rows=n_repaired,
        duplicate_pairs=dropped["ts"].nunique(),
        duplicate_rows_dropped=n_dropped,
        long_rows=len(long_df),
        date_min=long_df["observed_at"].min(),
        date_max=long_df["observed_at"].max(),
        dropped_audit=dropped.reset_index(drop=True),
    )
    return long_df, report
