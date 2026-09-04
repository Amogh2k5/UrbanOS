"""Centralized configuration for the Phase 1B Weather ML pipeline.

Mirrors the Phase 1 PM2.5 `config.py` conventions (dataclass ExperimentConfig,
REPO_ROOT-derived paths, deterministic seed, chronological split dates inside
the weather coverage window [2016-04, 2024-12]). Reuses Phase 1 split dates for
cross-experiment comparability with the PM2.5 model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

RAW_WEATHER_DIR = REPO_ROOT / "ml" / "datasets" / "raw" / "weather_24h" / "extracted"
RAW_PM25_CSV = REPO_ROOT / "ml" / "datasets" / "raw" / "pollution_pm25" / "Historical1hrPM2.5.csv"

PROCESSED_DIR = REPO_ROOT / "ml" / "datasets" / "processed" / "phase1b_weather"
RUNS_DIR = PROCESSED_DIR / "runs"

REGIONS = ("national",)  # weather ML is trained at the national scope (regional numeric fields don't exist in source)

# Regression + classification targets
REGRESSION_TARGETS = (
    "temperature_high_next_day",
    "temperature_low_next_day",
    "relative_humidity_high_next_day",
    "relative_humidity_low_next_day",
    "wind_speed_high_next_day",
    "wind_speed_low_next_day",
)
CLASSIFICATION_TARGETS = (
    "forecast_code_next_day",
)
ALL_TARGETS = REGRESSION_TARGETS + CLASSIFICATION_TARGETS

# Issuance cutoff (matches PM2.5 spec §1.1): t0 = 23:00 Asia/Singapore.
FORECAST_HOUR = 23

# Chronological split — matches the Phase 1 PM2.5 windows for cross-experiment comparability.
SPLIT_TRAIN_START = "2016-04-01"
SPLIT_TRAIN_END = "2021-12-31 23:00:00"
SPLIT_VAL_START = "2022-01-01"
SPLIT_VAL_END = "2023-06-30 23:00:00"
SPLIT_TEST_START = "2023-07-01"
SPLIT_TEST_END = "2024-12-31 23:00:00"

TRAILING_BASELINE_DAYS = 7
RANDOM_SEED = 20240101

ENABLE_CATBOOST = True

# Top-K forecast codes for the classification target (rare codes bucketed to "OTHER").
TOP_K_FORECAST_CODES = 14


@dataclass
class ExperimentConfig:
    raw_weather_dir: Path = RAW_WEATHER_DIR
    raw_pm25_csv: Path = RAW_PM25_CSV
    train_start: str = SPLIT_TRAIN_START
    train_end: str = SPLIT_TRAIN_END
    val_start: str = SPLIT_VAL_START
    val_end: str = SPLIT_VAL_END
    test_start: str = SPLIT_TEST_START
    test_end: str = SPLIT_TEST_END
    targets: tuple = ALL_TARGETS
    regions: tuple = REGIONS
    forecast_hour: int = FORECAST_HOUR
    trailing_baseline_days: int = TRAILING_BASELINE_DAYS
    random_seed: int = RANDOM_SEED
    enable_catboost: bool = ENABLE_CATBOOST
    top_k_forecast_codes: int = TOP_K_FORECAST_CODES
    runs_dir: Path = RUNS_DIR
    run_id: str = ""
    library_versions: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "raw_weather_dir": str(self.raw_weather_dir),
            "raw_pm25_csv": str(self.raw_pm25_csv),
            "train_start": self.train_start,
            "train_end": self.train_end,
            "val_start": self.val_start,
            "val_end": self.val_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "targets": list(self.targets),
            "regression_targets": list(REGRESSION_TARGETS),
            "classification_targets": list(CLASSIFICATION_TARGETS),
            "regions": list(self.regions),
            "forecast_hour": self.forecast_hour,
            "trailing_baseline_days": self.trailing_baseline_days,
            "random_seed": self.random_seed,
            "enable_catboost": self.enable_catboost,
            "top_k_forecast_codes": self.top_k_forecast_codes,
            "runs_dir": str(self.runs_dir),
            "run_id": self.run_id,
            "library_versions": self.library_versions,
        }


def get_default_config() -> ExperimentConfig:
    return ExperimentConfig()
