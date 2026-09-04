"""EnvironmentModule — the Environment domain agent for UrbanOS.

Inputs:
  - Completed Phase 1 PM2.5 ML artifacts (selections.csv + trained joblib models)
  - NEA 24h Weather Forecast datasets (raw CSVs, never modified)

Output:
  - `EnvironmentReport` — a structured *environment domain envelope* ready for the
    future Coordinator (architecture proposal §2). Contains:
      - prediction timestamp (t0 = D 23:00 Asia/Singapore, the issuance cutoff)
      - forecast date / target window
      - per-region (5) PM2.5 next-day mean & max predictions
      - model used per region + per target (catboost or bl_persist)
      - weather forecast summary (latest NEA issue with timestamp <= t0)
      - data_quality_flags (year-offset bug, region missing features, etc.)
      - provenance (artifact paths, ingest report counts)

Not built here (per AGENTS.md / task instructions):
  - Coordinator, Risk Engine, Traffic/Flood modules, dashboard, maps, scheduling,
    agent-to-agent comms, weather ML, new training.

PM2.5 prediction logic is fully separated from presentation: the `PM25Predictor`
returns a `RegionPrediction` dataclass and the model-input `features_df`;
`EnvironmentReport.to_dict()/to_json()` does the serialization.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional

import pandas as pd

from backend.app.environment.pm25.predictor import PM25Predictor, _IngestCache
from backend.app.environment.result import (
    EnvironmentReport, RegionPrediction, utcnow_sg,
)
from backend.app.environment.selectors import load_selections, SelectionDecision
from backend.app.environment.weather.loader import (
    load_weather, latest_forecast_summary, WeatherDiagnostics,
)
from ml.pm25.config import (
    REPO_ROOT, RAW_PM25_CSV, RAW_WEATHER_DIR, RUNS_DIR,
)

log = logging.getLogger(__name__)

SG_TZ = "Asia/Singapore"
DEFAULT_RUN_ID = "phase1_v1"
REGIONS = ("north", "south", "east", "west", "central")


class EnvironmentModule:
    """Environment domain agent — orchestrates PM2.5 ML + Weather into one report."""

    def __init__(
        self,
        runs_dir: Path = RUNS_DIR,
        run_id: str = DEFAULT_RUN_ID,
        pm25_csv: Path = RAW_PM25_CSV,
        weather_dir: Path = RAW_WEATHER_DIR,
    ) -> None:
        self.runs_dir = Path(runs_dir)
        self.run_id = run_id
        self.pm25_csv = Path(pm25_csv)
        self.weather_dir = Path(weather_dir)

        self.predictor = PM25Predictor(runs_dir=self.runs_dir, run_id=self.run_id)

        # Reuse a single ingestion of PM2.5 and Weather across predictor + weather summary
        # to keep latency bounded (large CSVs).
        self._shared_ingest_cache: Optional[_IngestCache] = None

    # ------------------------------------------------------------------ public

    def run(
        self,
        prediction_timestamp: Optional[pd.Timestamp] = None,
        force_t0: Optional[pd.Timestamp] = None,
    ) -> EnvironmentReport:
        """Build the Environment situation report.

        Args:
            prediction_timestamp: t0 = the issuance cutoff (D 23:00 Asia/Singapore).
                If None, defaults to the latest observation hour in the PM2.5 data
                that is < 24h before its max, so the target window is non-trivial.
                For deterministic demo / Coordinator replay, pass an explicit t0.
            force_t0: alias for prediction_timestamp (kept for clarity).

        Returns: EnvironmentReport (also a dict-shaped envelope via .to_dict()).
        """
        t0_arg = force_t0 if force_t0 is not None else prediction_timestamp

        # --- Ingest once, share. ---
        cache = self._ensure_ingested()
        self._shared_ingest_cache = cache

        # --- Determine t0 if not provided. ---
        if t0_arg is None:
            t0 = self._default_t0_from_pm25(cache.pm25_long, cache.weather_national)
        else:
            t0 = pd.Timestamp(t0_arg)
            if t0.tzinfo is None:
                t0 = t0.tz_localize(SG_TZ)
            else:
                t0 = t0.tz_convert(SG_TZ)

        # --- Weather summary. ---
        weather_summary, latest_issue_ts = latest_forecast_summary(
            cache.weather_national, t0, period=cache.weather_period,
        )

        # --- PM2.5 predictions for all 5 regions. ---
        features_df, per_region, diag = self.predictor.predict_all_regions(
            prediction_timestamp=t0,
            pm25_csv=self.pm25_csv,
            weather_dir=self.weather_dir,
            ingest_cache=cache,
        )

        # --- Assemble report. ---
        forecast_date = t0.normalize()
        target_window_start = t0 + pd.Timedelta(hours=1)
        target_window_end = t0 + pd.Timedelta(hours=24)

        data_quality_flags = []
        if diag.get("regions_missing_features"):
            for r in diag["regions_missing_features"]:
                data_quality_flags.append(f"region_{r}_missing_pm25_features")
        if weather_summary is None:
            data_quality_flags.append("no_nea_weather_forecast_at_t0")
        elif latest_issue_ts is not None:
            age_h = (t0 - latest_issue_ts).total_seconds() / 3600.0
            # Architecture §18: no silent fallbacks. Flag a stale weather issue
            # (>36h old) so the Coordinator / dashboard can show degradation.
            if age_h > 36:
                data_quality_flags.append(
                    f"weather_forecast_stale:{age_h:.1f}h_old_at_t0"
                )
        # Carry weather period year-offset flag if applicable to the latest issue.
        weather_dq_flag = self._check_weather_period_quality(cache.weather_period, latest_issue_ts)
        if weather_dq_flag:
            data_quality_flags.append(weather_dq_flag)

        # PM2.5 data_quality_flag (repaired / duplicate) tally if any present.
        pm25_dropped = int((cache.pm25_long["data_quality_flag"] != "ok").sum())
        if pm25_dropped > 0:
            data_quality_flags.append(f"pm25_ingest_special_rows:{pm25_dropped}")

        evidence = self._build_evidence(weather_summary, per_region)

        report = EnvironmentReport(
            domain="environment",
            schema_version="1.0",
            generated_at=utcnow_sg(),
            prediction_timestamp=t0.to_pydatetime(),
            forecast_date=forecast_date.to_pydatetime(),
            target_window_start=target_window_start.to_pydatetime(),
            target_window_end=target_window_end.to_pydatetime(),
            regions=[per_region[r] for r in REGIONS if r in per_region],
            weather_forecast=weather_summary,
            data_quality_flags=data_quality_flags,
            evidence=evidence,
            provenance=self._build_provenance(t0, diag, per_region),
        )
        return report

    # ---------------------------------------------------------------- internals

    def _ensure_ingested(self) -> _IngestCache:
        if self._shared_ingest_cache is not None:
            return self._shared_ingest_cache
        log.info("Ingesting PM2.5 + Weather for EnvironmentModule")
        # Use predictor's helper to avoid duplication; sets self._ingest_cache internal.
        cache = self.predictor._ensure_ingested(self.pm25_csv, self.weather_dir)
        self._shared_ingest_cache = cache
        return cache

    def _default_t0_from_pm25(
        self,
        pm25_long: pd.DataFrame,
        weather_national: Optional[pd.DataFrame] = None,
    ) -> pd.Timestamp:
        """Pick t0 = the latest available PM2.5 observation hour with a non-empty next-day window,
        capped by the latest available NEA weather forecast issue so the weather_summary is fresh.

        For production replay we cap at the latest observed hour. We use 23:00 of the most
        recent observed date when possible; otherwise fall back to the latest hour. If weather
        data is provided, we further cap t0 by the latest weather issue's date (so the auto
        t0 doesn't point at a future the weather dataset hasn't covered yet).
        """
        obs = pm25_long["observed_at"]
        if obs.dt.tz is None:
            obs = obs.dt.tz_localize(SG_TZ)
        else:
            obs = obs.dt.tz_convert(SG_TZ)
        max_obs = obs.max()
        # Try the calendar day of max_obs at 23:00.
        t0_candidate = max_obs.normalize() + pd.Timedelta(hours=23)
        # If max_obs is exactly 23:00 of its day, use it. Otherwise prefer the day before,
        # because the next-day target window must be observable for evaluation reproducibility.
        if t0_candidate > max_obs:
            t0_candidate = max_obs.normalize() - pd.Timedelta(days=1) + pd.Timedelta(hours=23)
            if t0_candidate > max_obs:
                t0_candidate = max_obs.floor("h")

        # Cap by latest weather issue if provided, to keep the weather_summary fresh.
        if weather_national is not None and not weather_national.empty:
            wts = weather_national["timestamp"]
            if wts.dt.tz is None:
                wts = wts.dt.tz_localize(SG_TZ)
            else:
                wts = wts.dt.tz_convert(SG_TZ)
            max_weather = wts.max()
            # Pick the day of max_weather at 23:00. The weather issue could be any time
            # that day; we want the last 23:00 that is <= max_obs so PM2.5 is also observable.
            cap = max_weather.normalize() + pd.Timedelta(hours=23)
            if cap < t0_candidate:
                # Cap t0 to this. But we must also ensure cap <= max_obs (PM2.5 is observable
                # at cap). If cap > max_obs, fall back to max_obs.floor('h').
                t0_candidate = cap if cap <= max_obs else max_obs.floor("h")

        return t0_candidate

    def _check_weather_period_quality(
        self,
        period: pd.DataFrame,
        latest_issue_ts: Optional[pd.Timestamp],
    ) -> Optional[str]:
        """Surface weather-period data-quality issues for the latest issue used.

        Phase-1 ingester (`ml.phase1_pm25.ingest_weather._fix_year_offset`) only flags
        rows where `valid_period_start.year != date.year`. It misses the same-calendar-year
        form of the year-offset bug (e.g. `date=2024-12-31` issue timestamp=`2024-12-31 23:00`,
        but `valid_period_start=2024-01-01` — same year, but precedes the issuance date,
        which is semantically impossible for a forecast). The fixer cannot be modified
        (Phase 1 pipeline frozen). Here we surface the defect as a flag instead, per
        architecture §18 (no silent fallbacks).
        """
        if latest_issue_ts is None or period.empty:
            return None
        same_issue = period[period["timestamp"] == latest_issue_ts]
        if same_issue.empty:
            return None
        flags = set(same_issue["data_quality_flag"].dropna().unique())
        if "year_offset_repaired" in flags:
            return "weather_period_year_offset_repaired"

        # Additional check: any valid_period_start before the issue date.
        # (Forecast can't be valid before its issuance date.)
        vps = same_issue["valid_period_start"].dropna()
        if not vps.empty:
            vps_min = pd.Timestamp(vps.min())
            if vps_min.tzinfo is None:
                vps_min = vps_min.tz_localize(SG_TZ)
            else:
                vps_min = vps_min.tz_convert(SG_TZ)
            date_min = same_issue["date"].min()
            if pd.notna(date_min):
                date_min = pd.Timestamp(date_min)
                if date_min.tzinfo is None:
                    date_min = date_min.tz_localize(SG_TZ)
                else:
                    date_min = date_min.tz_convert(SG_TZ)
                if vps_min < date_min:
                    return "weather_valid_period_precedes_issue_date"

        return None

    def _build_evidence(
        self,
        weather_summary,
        per_region: Dict[str, RegionPrediction],
    ) -> list:
        ev = [
            {
                "source": "NEA Historical1hrPM2.5.csv",
                "ref": str(self.pm25_csv),
                "kind": "pm25_observations",
            },
            {
                "source": "NEA Historical24hourWeatherForecast",
                "ref": str(self.weather_dir),
                "kind": "weather_forecasts",
            },
            {
                "source": "Phase 1 PM2.5 ML artifacts",
                "ref": str(self.predictor.run_dir),
                "kind": "ml_models_and_selections",
            },
        ]
        if weather_summary is not None and weather_summary.forecast_issue_timestamp is not None:
            ev.append({
                "source": "NEA 24h forecast at t0",
                "ref": weather_summary.forecast_issue_timestamp.isoformat(),
                "kind": "latest_weather_issue_used",
            })
        return ev

    def _build_provenance(
        self,
        t0: pd.Timestamp,
        diag: Dict[str, object],
        per_region: Dict[str, RegionPrediction],
    ) -> Dict[str, object]:
        cfg = self.predictor.experiment_config()
        # Load candidate model set (model_configs.json) — experiment_config.json
        # does not carry "candidates"/"baselines"; they are defined in ml.phase1_pm25.models.
        candidates_baselines = self._load_model_configs()
        # Tally selections
        ml_regions = [r for r, p in per_region.items() if p.is_ml_model]
        persist_regions = [r for r, p in per_region.items() if not p.is_ml_model and p.selected_model == "bl_persist"]
        return {
            "run_id": self.run_id,
            "run_dir": str(self.predictor.run_dir),
            "selections_csv": str(self.predictor.selections_csv),
            "experiment_config": {
                "forecast_hour": cfg.get("forecast_hour"),
                "train_start": cfg.get("train_start"),
                "train_end": cfg.get("train_end"),
                "val_start": cfg.get("val_start"),
                "val_end": cfg.get("val_end"),
                "test_start": cfg.get("test_start"),
                "test_end": cfg.get("test_end"),
                "candidates": candidates_baselines.get("candidates"),
                "baselines": candidates_baselines.get("baselines"),
                "library_versions": cfg.get("library_versions"),
            },
            "t0": t0.isoformat(),
            "regions_total": len(per_region),
            "regions_ml": ml_regions,
            "regions_persist": persist_regions,
            "regions_missing_features": diag.get("regions_missing_features", []),
            "decisions": {
                f"{r}_{t}": self.predictor.selections[(r, t)].selected_model
                for r in REGIONS for t in ("pm25_next_day_mean", "pm25_next_day_max")
            },
        }

    def _load_model_configs(self) -> Dict[str, object]:
        # candidates = keys of ml.phase1_pm25.models.all_candidates (per spec §11).
        # Hardcoded here only for provenance reporting (the experiment ran with this set).
        return {
            "candidates": ["ridge", "extra_trees", "xgb", "lgbm", "catboost"],
            "baselines": ["bl_persist", "bl_clim", "bl_trail7"],
        }


# ------------------------------------------------------------------ helpers

def default_paths() -> Dict[str, Path]:
    """Return the canonical UrbanOS paths the module uses by default."""
    return {
        "runs_dir": RUNS_DIR,
        "pm25_csv": RAW_PM25_CSV,
        "weather_dir": RAW_WEATHER_DIR,
    }
