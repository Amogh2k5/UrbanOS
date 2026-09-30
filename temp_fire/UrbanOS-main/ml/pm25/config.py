"""Centralized configuration for the Phase 1 PM2.5 ML pipeline.

All paths, seeds, split dates, regions, and target definitions live here.
No machine-specific hardcoded paths; paths derive from REPO_ROOT.

Spec reference: docs/ml/PHASE1_PM25_ML_SPEC.md (authoritative).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


# --- Paths ---------------------------------------------------------------
# ml/phase1_pm25/config.py -> repo root is two levels up (ml/phase1_pm25 -> ml/ -> root).
REPO_ROOT = Path(__file__).resolve().parents[2]

RAW_PM25_CSV = REPO_ROOT / "ml" / "datasets" / "raw" / "pollution_pm25" / "Historical1hrPM2.5.csv"
RAW_WEATHER_DIR = REPO_ROOT / "ml" / "datasets" / "raw" / "weather_24h" / "extracted"

# Processed artefacts (intermediate tables + final experiment run dirs)
PROCESSED_DIR = REPO_ROOT / "ml" / "datasets" / "processed" / "phase1_pm25"
RUNS_DIR = PROCESSED_DIR / "runs"

# --- Constants from the spec --------------------------------------------
REGIONS = ("north", "south", "east", "west", "central")

# Targets in scope for the initial Phase 1 implementation (spec §1.3, §11A.1).
TARGETS = ("pm25_next_day_mean", "pm25_next_day_max")

# "Primary/secondary" labeling from the spec is informational; both are first-class here.
REGRESSION_TARGETS = TARGETS  # only regression targets are in scope

# Issuance cutoff (spec §1.1, §4): t0 = 23:00 Asia/Singapore.
FORECAST_HOUR = 23  # local Singapore hour

# Chronological split (spec §8.1) — all sub-splits inside weather coverage [2016-04, 2024-12].
SPLIT_TRAIN_START = "2016-04-01"
SPLIT_TRAIN_END = "2021-12-31 23:00:00"
SPLIT_VAL_START = "2022-01-01"
SPLIT_VAL_END = "2023-06-30 23:00:00"
SPLIT_TEST_START = "2023-07-01"
SPLIT_TEST_END = "2024-12-31 23:00:00"

# Rolling/lag configuration (spec §3.2 Group A)
PM25_LAG_HOURS = (24, 48, 72)  # t-24h, t-48h, t-72h same-hour prior-day values
PM25_ROLL_WINDOWS_HOURS = (6, 12, 24)  # rolling mean & max ending at t0

# Trailing-7-day baseline window (spec §9.3) — 7 forecast issuances (i.e. 7 days)
TRAILING_BASELINE_DAYS = 7

# Determinism (spec §10.5, §11.6)
RANDOM_SEED = 20240101

# Model search (spec §11) — values are minimal sensible defaults; not exhaustive search spaces.
# Selection is decided by validation MAE primary, RMSE tiebreak, R² secondary (spec §11.4).

# CatBoost toggle (spec §11.3): conditionally included. Default True because:
#  - the Phase-1 feature set contains many categorical weather forecast codes (e.g. wf_forecast_code,
#    {region}_forecast_code, wf_wind_dir, monsoon_flag) that CatBoost handles natively without
#    needing a separate OneHotEncoder in the linear/ridge pipeline; this gives a materially simpler
#    pipeline than one-hot for the tree family and avoids dimensionality blow-up for the linear model
#    (documented reason: feature-type-driven, not added for breadth).
# Setting to False skips CatBoost entirely.
ENABLE_CATBOOST = True


@dataclass
class ExperimentConfig:
    """Single object that fully describes one experiment run."""

    # Data
    raw_pm25_csv: Path = RAW_PM25_CSV
    raw_weather_dir: Path = RAW_WEATHER_DIR

    # Splits (as strings; parsed by splits.py into Timestamps)
    train_start: str = SPLIT_TRAIN_START
    train_end: str = SPLIT_TRAIN_END
    val_start: str = SPLIT_VAL_START
    val_end: str = SPLIT_VAL_END
    test_start: str = SPLIT_TEST_START
    test_end: str = SPLIT_TEST_END

    # Targets / regions
    targets: tuple = TARGETS
    regions: tuple = REGIONS

    # Feature params
    pm25_lag_hours: tuple = PM25_LAG_HOURS
    pm25_roll_windows_hours: tuple = PM25_ROLL_WINDOWS_HOURS
    forecast_hour: int = FORECAST_HOUR

    # Baselines
    trailing_baseline_days: int = TRAILING_BASELINE_DAYS

    # Determinism
    random_seed: int = RANDOM_SEED

    # Models
    enable_catboost: bool = ENABLE_CATBOOST

    # Output
    runs_dir: Path = RUNS_DIR
    run_id: str = ""  # set by experiment.py at runtime

    # Captured reproducibility metadata (filled by experiment.py)
    library_versions: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "raw_pm25_csv": str(self.raw_pm25_csv),
            "raw_weather_dir": str(self.raw_weather_dir),
            "train_start": self.train_start,
            "train_end": self.train_end,
            "val_start": self.val_start,
            "val_end": self.val_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "targets": list(self.targets),
            "regions": list(self.regions),
            "pm25_lag_hours": list(self.pm25_lag_hours),
            "pm25_roll_windows_hours": list(self.pm25_roll_windows_hours),
            "forecast_hour": self.forecast_hour,
            "trailing_baseline_days": self.trailing_baseline_days,
            "random_seed": self.random_seed,
            "enable_catboost": self.enable_catboost,
            "runs_dir": str(self.runs_dir),
            "run_id": self.run_id,
            "library_versions": self.library_versions,
        }


def get_default_config() -> ExperimentConfig:
    return ExperimentConfig()
