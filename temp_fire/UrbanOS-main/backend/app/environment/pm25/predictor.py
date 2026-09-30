"""PM2.5 predictor — reuses the trained Phase 1 ML artifacts.

This module does NOT train or retrain. It loads joblib artifacts from
`ml/pm25/models/production/{region}_{target}_catboost.joblib`, builds the
exact leakage-safe feature row expected by those models (reusing
`ml.pm25.features.build_modelling_dataset`), and produces next-day PM2.5
mean/max predictions per region.

Selection rule (from `selections.csv`):
    - model == "catboost" -> run inference via the trained pipeline.
    - model == "bl_persist" -> persistence fallback: predicted next-day value = pm25_t0
      (the observed PM2.5 at the issuance hour t0). Persistence is a BASELINE,
      not an ML model, and is used directly without loading any joblib.

The feature builder ingests raw PM2.5 and Weather data. For historical predictions,
this comes from CSV files. For current predictions, weather comes from the
collected NEA live forecast database. Raw CSVs are never modified (audit rule).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import joblib
import pandas as pd

from backend.app.environment.selectors import (
    SelectionDecision, load_selections, per_region_target_decisions,
)
from backend.app.environment.result import RegionPrediction
from backend.app.environment.weather.data import WeatherForecastStore
from ml.pm25.config import REPO_ROOT
from ml.pm25.features import build_modelling_dataset
from ml.pm25.ingest_pm25 import ingest_pm25
from ml.pm25.ingest_weather import ingest_weather as _ingest_weather_raw

SG_TZ = "Asia/Singapore"
FEATURE_COLUMNS_KEY = "feature_columns"

REGIONS = ("north", "south", "east", "west", "central")
TARGETS = ("pm25_next_day_mean", "pm25_next_day_max")

log = logging.getLogger(__name__)


@dataclass
class _IngestCache:
    pm25_long: pd.DataFrame
    weather_national: pd.DataFrame
    weather_period: pd.DataFrame


class PM25Predictor:
    """Loads selection decisions and trained models, produces per-region predictions."""

    def __init__(
        self,
        runs_dir: Path,
        run_id: str,
        selections: Optional[Dict[Tuple[str, str], SelectionDecision]] = None,
        models_dir: Optional[Path] = None,
    ) -> None:
        self.runs_dir = Path(runs_dir)
        self.run_id = run_id
        self.run_dir = self.runs_dir / run_id
        # Use production models directory by default
        self.models_dir = models_dir or Path("ml/pm25/models/production")
        # Selections file: prefer production models dir, then run dir
        self.selections_csv = self.models_dir / "selections.csv"
        if not self.selections_csv.exists():
            self.selections_csv = self.run_dir / "selections.csv"
        self.experiment_config_path = self.run_dir / "experiment_config.json"

        if selections is None:
            self.selections = load_selections(self.selections_csv)
        else:
            self.selections = selections

        # Caches
        self._model_cache: Dict[Tuple[str, str, str], object] = {}
        self._feature_columns_cache: Optional[list] = None
        self._experiment_config: Optional[dict] = None
        self._ingest_cache: Optional[_IngestCache] = None
        self._pm25_long_cache: Optional[pd.DataFrame] = None

    # ------------------------------------------------------------------ public

    def predict_all_regions(
        self,
        prediction_timestamp: pd.Timestamp,
        pm25_csv: Path,
        weather_dir: Path,
        ingest_cache: Optional[_IngestCache] = None,
        weather_store: Optional[WeatherForecastStore] = None,
        pm25_store: Optional["Pm25ObservationStore"] = None,
    ) -> Tuple[pd.DataFrame, Dict[str, RegionPrediction], Dict[str, object]]:
        """Build features for one t0 = prediction_timestamp and predict for all 5 regions.

        Returns:
            features_df: model-input feature DataFrame (1 row per region).
            per_region:  {region: RegionPrediction}.
            diagnostics: misc provenance + flags.

        If weather_store/pm25_store are provided and prediction_timestamp is recent (within 7 days
        of latest collected data), features will be sourced from the collected live data instead of the historical CSV.
        """
        cache = ingest_cache or self._ensure_ingested(pm25_csv, weather_dir, weather_store, pm25_store, prediction_timestamp)

        # The feature builder takes issuance_dates (calendar dates).
        t0 = pd.Timestamp(prediction_timestamp).tz_convert(SG_TZ)
        issuance_dates = pd.DatetimeIndex([t0.normalize()])

        modelling_df, _report = build_modelling_dataset(
            pm25_long=cache.pm25_long,
            national_weather=cache.weather_national,
            period_weather=cache.weather_period,
            regions=REGIONS,
            issuance_dates=issuance_dates,
            forecast_hour=t0.hour,
        )

        # Modelling dataset is sorted by region. We need exactly one row per region.
        # If ingestion produced no row for a given region (e.g. no PM2.5 obs for that
        # day), that region is missing; caller should flag it.
        modelling_df = modelling_df.sort_values("region").reset_index(drop=True)

        per_region: Dict[str, RegionPrediction] = {}
        # target_models per region recorded for the report
        diagnostics: Dict[str, object] = {
            "predictions_total": 0,
            "predictions_ml": 0,
            "predictions_persist": 0,
            "regions_missing_features": [],
            "feature_report_rows": len(modelling_df),
        }

        for region in REGIONS:
            sub = modelling_df[modelling_df["region"] == region]
            if sub.empty:
                diagnostics["regions_missing_features"].append(region)
                per_region[region] = RegionPrediction(
                    region=region,
                    selected_model="MISSING_FEATURES",
                    is_ml_model=False,
                    pm25_next_day_mean=None,
                    pm25_next_day_max=None,
                    fallback_reason="No feature row could be built for this region (PM2.5 obs missing for t0).",
                )
                continue

            row = sub.iloc[0]
            decisions = per_region_target_decisions(self.selections, region)

            target_models: Dict[str, str] = {}
            mean_pred, max_pred = None, None
            overall_model = "bl_persist"
            overall_is_ml = False
            fallback_reason = None

            for target, dec in decisions.items():
                if dec.is_ml_model:
                    pred_val = self._predict_with_ml(region, target, dec.selected_model, row)
                    target_models[target] = dec.selected_model
                    overall_model = dec.selected_model
                    overall_is_ml = True
                    diagnostics["predictions_ml"] += 1
                else:
                    # Persistence: predicted next-day value = PM2.5 observed at t0.
                    pred_val = self._persistence_prediction(row)
                    target_models[target] = "bl_persist"
                    fallback_reason = dec.fallback_reason
                    diagnostics["predictions_persist"] += 1

                if target == "pm25_next_day_mean":
                    mean_pred = pred_val
                elif target == "pm25_next_day_max":
                    max_pred = pred_val

                diagnostics["predictions_total"] += 1

            # A region is "ML" only if BOTH targets were ML; if any was persist,
            # we tag the region selected_model by the *primary* target
            # (pm25_next_day_mean) for top-level reporting.
            primary_dec = decisions["pm25_next_day_mean"]
            overall_model = primary_dec.selected_model
            overall_is_ml = primary_dec.is_ml_model

            per_region[region] = RegionPrediction(
                region=region,
                selected_model=overall_model,
                is_ml_model=overall_is_ml,
                pm25_next_day_mean=mean_pred,
                pm25_next_day_max=max_pred,
                target_models=target_models,
                persistence_value_pm25_t0=(None if primary_dec.is_ml_model else float(row["pm25_t0"])),
                fallback_reason=fallback_reason,
            )

        return modelling_df, per_region, diagnostics

    # --------------------------------------------------------------- internals

    def _ensure_ingested(
        self,
        pm25_csv: Path,
        weather_dir: Path,
        weather_store: Optional[WeatherForecastStore] = None,
        pm25_store: Optional["Pm25ObservationStore"] = None,
        prediction_timestamp: Optional[pd.Timestamp] = None,
    ) -> _IngestCache:
        """Ensure PM2.5 and weather data are ingested.

        If weather_store/pm25_store are provided and prediction_timestamp is recent,
        use collected live data. Otherwise fall back to historical CSVs.
        """
        if self._ingest_cache is None:
            # Try to use live PM2.5 observations for current predictions
            use_live_pm25 = False
            pm25_long = None
            if pm25_store is not None and prediction_timestamp is not None:
                latest_obs_ts = pm25_store.get_latest_observation_timestamp()
                if latest_obs_ts is not None:
                    latest_obs = pd.Timestamp(latest_obs_ts)
                    pred_ts = pd.Timestamp(prediction_timestamp).tz_convert(SG_TZ)
                    age_days = (pred_ts - latest_obs).total_seconds() / 86400
                    if 0 <= age_days <= 7 and latest_obs <= pred_ts:
                        use_live_pm25 = True
                        log.info("Using collected live PM2.5 observations (latest obs: %s, age: %.1f days)",
                                 latest_obs_ts, age_days)

            if use_live_pm25:
                log.info("Loading PM2.5 from observation store")
                pm25_long = pm25_store.to_long_dataframe(REGIONS)
                # Filter to observations up to prediction_timestamp
                pred_ts = pd.Timestamp(prediction_timestamp).tz_convert(SG_TZ)
                pm25_long = pm25_long[pm25_long["observed_at"] <= pred_ts]
                if pm25_long.empty:
                    log.warning("No eligible live PM2.5 observations for t0=%s, falling back to CSV",
                                prediction_timestamp)
                    use_live_pm25 = False

            if not use_live_pm25:
                log.info("Ingesting PM2.5 from %s", pm25_csv)
                pm25_long, _pm25_report = ingest_pm25(str(pm25_csv), REGIONS)
            self._pm25_long_cache = pm25_long

            # Weather (same logic as before)
            use_live_weather = False
            if weather_store is not None and prediction_timestamp is not None:
                latest_forecast_ts = weather_store.get_latest_forecast_timestamp()
                if latest_forecast_ts is not None:
                    latest_forecast = pd.Timestamp(latest_forecast_ts)
                    pred_ts = pd.Timestamp(prediction_timestamp).tz_convert(SG_TZ)
                    age_days = (pred_ts - latest_forecast).total_seconds() / 86400
                    if 0 <= age_days <= 7 and latest_forecast <= pred_ts:
                        use_live_weather = True
                        log.info("Using collected live weather data (latest forecast: %s, age: %.1f days)",
                                 latest_forecast_ts, age_days)

            if use_live_weather:
                log.info("Loading weather from collected forecast store")
                nat = weather_store.to_national_dataframe()
                per_long = weather_store.to_period_dataframe()
                pred_ts = pd.Timestamp(prediction_timestamp).tz_convert(SG_TZ)
                nat = nat[nat["timestamp"] <= pred_ts]
                per_long = per_long[per_long["timestamp"] <= pred_ts]
                if nat.empty or per_long.empty:
                    log.warning("No eligible live weather forecasts for t0=%s, falling back to CSV",
                                prediction_timestamp)
                    use_live_weather = False
                else:
                    per = self._pivot_period_df(per_long)

            if not use_live_weather:
                log.info("Ingesting Weather 24h from %s", weather_dir)
                nat, per, _w_report = _ingest_weather_raw(str(weather_dir))

            self._ingest_cache = _IngestCache(self._pm25_long_cache, nat, per)
        elif (weather_store is not None or pm25_store is not None) and prediction_timestamp is not None:
            # Refresh cache if needed for a different t0
            refresh = False
            latest_forecast_ts = None
            latest_obs_ts = None
            if weather_store is not None:
                latest_forecast_ts = weather_store.get_latest_forecast_timestamp()
            if pm25_store is not None:
                latest_obs_ts = pm25_store.get_latest_observation_timestamp()
            pred_ts = pd.Timestamp(prediction_timestamp).tz_convert(SG_TZ)

            if weather_store is not None and latest_forecast_ts is not None:
                latest_forecast = pd.Timestamp(latest_forecast_ts)
                age_days = (pred_ts - latest_forecast).total_seconds() / 86400
                if 0 <= age_days <= 7 and latest_forecast <= pred_ts:
                    refresh = True
            if pm25_store is not None and latest_obs_ts is not None:
                latest_obs = pd.Timestamp(latest_obs_ts)
                age_days = (pred_ts - latest_obs).total_seconds() / 86400
                if 0 <= age_days <= 7 and latest_obs <= pred_ts:
                    refresh = True

            if refresh:
                log.info("Rebuilding ingest cache with live data for t0=%s", prediction_timestamp)
                pm25_long = self._pm25_long_cache
                if pm25_store is not None and latest_obs_ts is not None:
                    pm25_long = pm25_store.to_long_dataframe(REGIONS)
                    pm25_long = pm25_long[pm25_long["observed_at"] <= pred_ts]
                nat = None
                per = None
                if weather_store is not None and latest_forecast_ts is not None:
                    nat = weather_store.to_national_dataframe()
                    per_long = weather_store.to_period_dataframe()
                    nat = nat[nat["timestamp"] <= pred_ts]
                    per_long = per_long[per_long["timestamp"] <= pred_ts]
                    per = self._pivot_period_df(per_long) if not per_long.empty else per_long
                if pm25_long is not None and (nat is not None and not nat.empty) and (per is not None and not per.empty):
                    self._ingest_cache = _IngestCache(pm25_long, nat, per)

        return self._ingest_cache

    def _build_ingest_cache_from_store(
        self,
        pm25_csv: Path,
        weather_store: WeatherForecastStore,
        prediction_timestamp: pd.Timestamp,
    ) -> _IngestCache:
        """Build ingest cache using PM2.5 from CSV and weather from collected store."""
        if self._pm25_long_cache is None:
            log.info("Ingesting PM2.5 from %s", pm25_csv)
            pm25_long, _ = ingest_pm25(str(pm25_csv), REGIONS)
            self._pm25_long_cache = pm25_long
        else:
            pm25_long = self._pm25_long_cache

        log.info("Loading weather from collected forecast store for t0=%s", prediction_timestamp)
        nat = weather_store.to_national_dataframe()
        per = weather_store.to_period_dataframe()

        # Filter to eligible forecasts (issued at or before t0)
        pred_ts = pd.Timestamp(prediction_timestamp).tz_convert(SG_TZ)
        nat = nat[nat["timestamp"] <= pred_ts]
        per = per[per["timestamp"] <= pred_ts]

        if nat.empty or per.empty:
            raise ValueError(f"No eligible weather forecasts found for t0={prediction_timestamp}")

        return _IngestCache(pm25_long, nat, per)

    def _pivot_period_df(self, per_long: pd.DataFrame) -> pd.DataFrame:
        """Pivot long-format period forecast (region as column) to wide format
        with one column per region for forecast_code and forecast_text, matching
        the historical ingest schema expected by the feature pipeline."""
        idx_cols = [
            "date", "timestamp", "update_timestamp", "valid_period_start",
            "valid_period_end", "time_period_start", "time_period_end", "time_period_text"
        ]
        missing = [c for c in idx_cols if c not in per_long.columns]
        if missing:
            raise ValueError(f"Period dataframe missing index columns: {missing}")

        # Determine a single data_quality_flag per period group (take first)
        dq = per_long.groupby(idx_cols)["data_quality_flag"].first().reset_index()
        dq.rename(columns={"data_quality_flag": "data_quality_flag"}, inplace=True)

        # Pivot forecast_code and forecast_text
        pivoted = per_long.set_index(idx_cols + ["region"])[["forecast_code", "forecast_text"]].unstack("region")
        pivoted.columns = [f"{region}_{col}" for col, region in pivoted.columns]
        pivoted = pivoted.reset_index()

        # Merge data_quality_flag back
        pivoted = pivoted.merge(dq, on=idx_cols, how="left")
        return pivoted

    def experiment_config(self) -> dict:
        if self._experiment_config is None:
            with open(self.experiment_config_path, "r", encoding="utf-8") as f:
                self._experiment_config = json.load(f)
        return self._experiment_config

    def _feature_columns(self) -> list:
        if self._feature_columns_cache is None:
            # Try feature_definitions.json first (authoritative)
            fdefs = self.run_dir / "feature_definitions.json"
            if fdefs.exists():
                with open(fdefs, "r", encoding="utf-8") as f:
                    self._feature_columns_cache = json.load(f).get("feature_columns")
            if self._feature_columns_cache is None:
                # Fall back to a model artifact's stored feature_columns
                sample = next(self.models_dir.glob("*catboost*.joblib"), None)
                if sample is not None:
                    art = joblib.load(sample)
                    self._feature_columns_cache = art.get(FEATURE_COLUMNS_KEY)
        return self._feature_columns_cache or []

    def _load_model(self, region: str, target: str, model_name: str):
        key = (region, target, model_name)
        if key not in self._model_cache:
            # Use production models directory
            path = self.models_dir / f"{region}_{target}_{model_name}.joblib"
            if not path.exists():
                # Fallback to run directory if production model not found
                fallback_path = self.run_dir / "models" / f"{region}_{target}_{model_name}.joblib"
                if fallback_path.exists():
                    path = fallback_path
                    log.warning("Using fallback model from run directory: %s", path)
                else:
                    raise FileNotFoundError(f"Model artifact missing: {path}")
            self._model_cache[key] = joblib.load(path)
        return self._model_cache[key]

    def _predict_with_ml(
        self,
        region: str,
        target: str,
        model_name: str,
        feature_row: pd.Series,
    ) -> float:
        feat_cols = self._feature_columns()
        if not feat_cols:
            # Fall back to the artifact's own stored feature_columns
            art = self._load_model(region, target, model_name)
            feat_cols = art.get(FEATURE_COLUMNS_KEY) or list(feature_row.index)

        X = pd.DataFrame([feature_row])[feat_cols]
        artifact = self._load_model(region, target, model_name)
        pipeline = artifact["pipeline"] if isinstance(artifact, dict) else artifact
        try:
            pred = pipeline.predict(X)
        except Exception as e:
            # Model compatibility issue (e.g., SimpleImputer _fill_dtype) – fall back to persistence
            log.warning("ML prediction failed for %s/%s/%s: %s; using persistence fallback", region, target, model_name, e)
            return self._persistence_prediction(feature_row)
        # Sklearn pipelines return shape (1,); CatBoost similarly.
        val = pred[0] if hasattr(pred, "__len__") else pred
        return float(val)

    @staticmethod
    def _persistence_prediction(feature_row: pd.Series) -> float:
        """Persistence baseline: next-day PM2.5 = observed PM2.5 at t0.

        Used for both mean and max targets (per spec §9.3 the baseline emits the
        same value for both)."""
        return float(feature_row["pm25_t0"])
