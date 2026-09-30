"""Experiment orchestrator (spec §11, §11A.1, §11.6, §15).

Orchestrates:
  - ingest (PM2.5 + Weather)
  - feature + target generation (leakage-safe at t0 = 23:00 Asia/Singapore)
  - chronological train/validation/test split (spec §8.1)
  - baseline computation: persistence (B-A), climatological (B-B), trailing-7-day (B-C)
  - ML candidate training: Ridge / ExtraTrees / XGBoost / LightGBM / (optional CatBoost)
  - validation selection per (region, target): MAE primary, RMSE tiebreak, R² secondary
  - test-set evaluation for the per-(region,target) selected model, exactly once
  - reproducibility artefact: split info, per-candidate validation metrics, per-selected-model
    test metrics, library versions, seeds, baseline metrics, predictions, saved models.

Selection rule (spec §11.4): per target, per region, independently — validation only. Test set
is never used for selection (spec §11.4).
"""

from __future__ import annotations

import json
import platform
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import joblib

from . import __init__  # noqa: F401 – ensure package import works
from .baselines import (
    baseline_climatological,
    baseline_persistence,
    baseline_trailing_n,
)
from .config import ExperimentConfig
from .features import build_modelling_dataset
from .ingest_pm25 import ingest_pm25
from .ingest_weather import ingest_weather
from .metrics import all_metrics
from .models import all_candidates, bind_prep, model_metadata
from .splits import split_modelling_df


FEATURE_COLUMNS = [
    "pm25_t0", "pm25_lag_24h", "pm25_lag_48h", "pm25_lag_72h",
    "pm25_roll6h_mean", "pm25_roll6h_max",
    "pm25_roll12h_mean", "pm25_roll12h_max",
    "pm25_roll24h_mean", "pm25_roll24h_max",
    "hour_of_day", "day_of_week", "month", "is_weekend", "monsoon_flag",
    "wf_temp_high", "wf_temp_low", "wf_rh_high", "wf_rh_low",
    "wf_wind_high", "wf_wind_low", "wf_wind_dir",
    "wf_forecast_code", "wf_region_forecast_code",
    "wf_n_rain_codes", "wf_n_haze_codes",
    "wf_window_coverage", "wf_n_issues_used",
    "wf_quality_flag",
]
TARGET_COLUMNS = ["pm25_next_day_mean", "pm25_next_day_max"]


def _capture_versions() -> dict:
    rev = {}
    for pkg in ("pandas", "numpy", "sklearn", "xgboost", "lightgbm", "catboost", "joblib"):
        try:
            mod = __import__(pkg)
            rev[pkg] = getattr(mod, "__version__", "unknown")
        except ImportError:
            rev[pkg] = "NOT_INSTALLED"
    rev["python"] = sys.version.split()[0]
    rev["platform"] = platform.platform()
    return rev


@dataclass
class CandidateResult:
    region: str
    target: str
    model_name: str
    fit_seconds: float
    predict_seconds: float
    metrics: dict  # {"mae":, "rmse":, "r2":, "n":}
    persistence_metrics: dict
    delta_vs_persistence: dict
    is_baseline: bool = False


@dataclass
class SelectionRecord:
    region: str
    target: str
    selected_model: str
    selection_rationale: str
    val_metrics: dict
    persistence_val_metrics: dict
    test_metrics: dict
    persistence_test_metrics: dict


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_experiment(cfg: ExperimentConfig) -> dict:
    """Execute the full Phase 1 experiment.

    Returns a summary dict suitable for printing. All artefacts are written to
    cfg.runs_dir / cfg.run_id.
    """
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
    log = logging.getLogger("phase1_pm25")

    # Capture versions up-front for the artefact
    cfg.library_versions = _capture_versions()

    run_dir = _ensure_dir(cfg.runs_dir / cfg.run_id)
    log.info("run_id=%s  run_dir=%s", cfg.run_id, run_dir)

    # ---------- 1. ingest ----------
    log.info("ingesting PM2.5 from %s", cfg.raw_pm25_csv)
    t0 = time.time()
    pm25_long, pm25_report = ingest_pm25(cfg.raw_pm25_csv, cfg.regions)
    log.info("  PM2.5 ingested: %d long rows in %.1fs", pm25_report.long_rows, time.time() - t0)

    log.info("ingesting Weather 24h from %s", cfg.raw_weather_dir)
    t0 = time.time()
    nat, per, weather_report = ingest_weather(str(cfg.raw_weather_dir))
    log.info("  Weather ingested: %d national + %d period rows in %.1fs",
             weather_report.national_rows, weather_report.period_rows, time.time() - t0)

    # ---------- 2. issuance dates within train+val+test span (2016-04-01 → 2024-12-31) ----------
    full_span_start = pd.Timestamp(cfg.train_start).tz_localize("Asia/Singapore")
    full_span_end = pd.Timestamp(cfg.test_end).tz_localize("Asia/Singapore")
    # Daily issuance dates from full_span_start to full_span_end inclusive
    issuance_dates = pd.date_range(full_span_start, full_span_end, freq="D", tz="Asia/Singapore")

    log.info("building modelling dataset for %d issuance dates × %d regions",
             len(issuance_dates), len(cfg.regions))
    t0 = time.time()
    df, feat_report = build_modelling_dataset(
        pm25_long, nat, per, cfg.regions, issuance_dates, forecast_hour=cfg.forecast_hour
    )
    log.info("  dataset built: %d rows × %d cols in %.1fs", len(df), df.shape[1], time.time() - t0)

    # Save the modelling dataset (Parquet if available, CSV otherwise — for the artefact)
    modelling_path = run_dir / "modelling_dataset.parquet"
    try:
        df.to_parquet(modelling_path, index=False)
    except Exception:
        modelling_path = run_dir / "modelling_dataset.csv"
        df.to_csv(modelling_path, index=False)
    log.info("  saved modelling dataset -> %s", modelling_path)

    # Save ingestion reports
    artefact_reports = {
        "pm25_ingest": {k: (v.isoformat() if hasattr(v, "isoformat") else
                             (v.to_dict('records') if hasattr(v, 'to_dict') else v))
                        for k, v in asdict(pm25_report).items()},
        "weather_ingest": {k: (v.isoformat() if hasattr(v, "isoformat") else v)
                           for k, v in asdict(weather_report).items()},
        "feature_report": {k: (v if not isinstance(v, dict) else v)
                           for k, v in asdict(feat_report).items()},
    }
    (run_dir / "ingest_feature_reports.json").write_text(
        json.dumps(artefact_reports, indent=2, default=str), encoding="utf-8"
    )

    # ---------- 3. chronological split ----------
    train_df, val_df, test_df, split_info = split_modelling_df(
        df,
        train_start=cfg.train_start, train_end=cfg.train_end,
        val_start=cfg.val_start, val_end=cfg.val_end,
        test_start=cfg.test_start, test_end=cfg.test_end,
    )
    # Filter rows that have a complete target window (we don't use rows with NaN targets for training
    # but they may still serve as feature sources; the modelling dataset already drops them as
    # per spec — safe rows have n_target_hours_present > 0).
    train_df = train_df.loc[train_df[TARGET_COLUMNS].notna().all(axis=1)].reset_index(drop=True)
    val_df = val_df.loc[val_df[TARGET_COLUMNS].notna().all(axis=1)].reset_index(drop=True)
    test_df = test_df.loc[test_df[TARGET_COLUMNS].notna().all(axis=1)].reset_index(drop=True)
    log.info("splits: train=%d  val=%d  test=%d  dates: train[%s .. %s] val[%s .. %s] test[%s .. %s]",
             split_info.train_rows, split_info.val_rows, split_info.test_rows,
             cfg.train_start, cfg.train_end, cfg.val_start, cfg.val_end, cfg.test_start, cfg.test_end)

    (run_dir / "split_info.json").write_text(json.dumps(split_info.as_dict(), indent=2), encoding="utf-8")

    # Combine train+val for the trailing-7-day baseline (val rows need historical issuances
    # that live in train).
    train_val_df = pd.concat([train_df, val_df], ignore_index=True)
    full_after_split_df = df.copy()  # used for trailing-baseline (only AT-OR-BEFORE t0 is read)

    # ---------- 4. baselines + ML candidates, per region & target ----------
    random_seed = cfg.random_seed
    # Build candidate factory (per region: new instance — keeps fitted state isolated)
    cand_specs = all_candidates(random_seed, enable_catboost=cfg.enable_catboost, extra_trees=True)

    all_val_metrics: List[CandidateResult] = []
    all_val_predictions: List[pd.DataFrame] = []
    all_selections: List[SelectionRecord] = []
    all_test_predictions: List[pd.DataFrame] = []

    # For each region/target pair: train all candidates on train, eval on val, select best,
    # then evaluate selected on test exactly once.
    for region in cfg.regions:
        log.info("== region: %s ==", region)
        train_r = train_df.loc[train_df["region"] == region]
        val_r = val_df.loc[val_df["region"] == region]
        test_r = test_df.loc[test_df["region"] == region]
        if train_r.empty or val_r.empty or test_r.empty:
            log.warning("  skipping region %s — empty split (train=%d val=%d test=%d)",
                        region, len(train_r), len(val_r), len(test_r))
            continue

        X_train_full = train_r[FEATURE_COLUMNS].copy()
        X_val_full = val_r[FEATURE_COLUMNS].copy()
        X_test_full = test_r[FEATURE_COLUMNS].copy()

        # ----- baselines: B-A persistence, B-B climatological, B-C trailing-7-day -----
        bl_stats: Dict[Tuple[str, str], Dict[str, dict]] = {}
        bl_preds: Dict[Tuple[str, str], pd.Series] = {}

        # Persistence — predict using last 24h pm25 ending at each t0.
        # IMPORTANT: do NOT use `.values` here — that strips tz info, so .tz_convert fails.
        # The "t0" column is already tz-aware Asia/Singapore; build the DatetimeIndex
        # directly from the Series (preserves tz).
        t0s_train = pd.DatetimeIndex(train_r["t0"])
        t0s_val = pd.DatetimeIndex(val_r["t0"])
        t0s_test = pd.DatetimeIndex(test_r["t0"])
        bl_persist_val = baseline_persistence(pm25_long, region, t0s_val)
        bl_persist_test = baseline_persistence(pm25_long, region, t0s_test)

        bl_clim_val = baseline_climatological(train_r, region, val_r)
        bl_clim_test = baseline_climatological(train_r, region, test_r)

        bl_trail_val = baseline_trailing_n(train_val_df, region, val_r, n_days=cfg.trailing_baseline_days)
        bl_trail_test = baseline_trailing_n(train_val_df, region, test_r, n_days=cfg.trailing_baseline_days)

        # Map baselines onto val/test rows (align by t0)
        def _attach_baseline(pred_df: pd.DataFrame, baseline: pd.DataFrame, prefix: str) -> pd.DataFrame:
            # baseline is indexed by t0 with cols [pm25_next_day_mean, pm25_next_day_max]
            b = baseline.copy()
            b.columns = [f"{prefix}__{c}" for c in b.columns]
            pred_df = pred_df.merge(b, left_on="t0", right_index=True, how="left")
            return pred_df

        # ----- ML candidates -----
        for target in cfg.targets:
            log.info("  region=%s target=%s", region, target)
            y_train = train_r[target].astype(float).values
            y_val = val_r[target].astype(float).values
            y_test = test_r[target].astype(float).values

            # We track predictions per (region, target) in a single DataFrame that will also
            # include baseline predictions side-by-side.
            val_pred_df = val_r[["t0", "region", "issuance_date"]].copy()
            val_pred_df["target"] = target
            val_pred_df["y_true"] = y_val

            test_pred_df = test_r[["t0", "region", "issuance_date"]].copy()
            test_pred_df["target"] = target
            test_pred_df["y_true"] = y_test

            for bl_name, bl_val, bl_test in [
                ("bl_persist", bl_persist_val, bl_persist_test),
                ("bl_clim", bl_clim_val, bl_clim_test),
                ("bl_trail7", bl_trail_val, bl_trail_test),
            ]:
                bl_v_vals = bl_val.reindex(pd.Index(val_r["t0"]))[target].values
                bl_t_vals = bl_test.reindex(pd.Index(test_r["t0"]))[target].values
                val_pred_df[f"pred__{bl_name}"] = bl_v_vals
                test_pred_df[f"pred__{bl_name}"] = bl_t_vals
                # Persist val/test metrics for the baseline register
                v_met = all_metrics(y_val, bl_v_vals)
                cr = CandidateResult(
                    region=region, target=target, model_name=bl_name,
                    fit_seconds=0.0, predict_seconds=0.0,
                    metrics=v_met,
                    persistence_metrics=v_met,
                    delta_vs_persistence={k: 0.0 for k in ("mae", "rmse", "r2")},
                    is_baseline=True,
                )
                all_val_metrics.append(cr)

            # Train & evaluate each ML candidate on validation
            for model_name, base_pipeline in cand_specs.items():
                t0_t = time.time()
                pipeline = bind_prep(base_pipeline, X_train_full)  # fit prep on train only (leakage-safe)
                pipeline.fit(X_train_full, y_train)
                fit_seconds = time.time() - t0_t

                t0_t = time.time()
                y_val_pred = pipeline.predict(X_val_full)
                predict_seconds = time.time() - t0_t

                val_pred_df[f"pred__{model_name}"] = y_val_pred
                metrics = all_metrics(y_val, y_val_pred)

                # Persistence is the floor — every ML candidate must beat it on MAE
                persist_y_pred = val_pred_df["pred__bl_persist"].values
                persist_metrics = all_metrics(y_val, persist_y_pred)
                delta = {k: metrics[k] - persist_metrics[k] for k in ("mae", "rmse", "r2")}

                cr = CandidateResult(
                    region=region, target=target, model_name=model_name,
                    fit_seconds=fit_seconds, predict_seconds=predict_seconds,
                    metrics=metrics,
                    persistence_metrics=persist_metrics,
                    delta_vs_persistence=delta,
                    is_baseline=False,
                )
                all_val_metrics.append(cr)

                # Save the fitted model artefact (per-region/per-target/per-model) for reproducibility
                model_path = run_dir / f"models/{region}_{target}_{model_name}.joblib"
                _ensure_dir(model_path.parent)
                joblib.dump({"pipeline": pipeline, "feature_columns": FEATURE_COLUMNS,
                             "region": region, "target": target, "model_name": model_name,
                             "config": cfg.as_dict()}, model_path)

            # ----- selection: per region, per target, choose by val MAE (primary), RMSE tiebreak, R² secondary -----
            cand_results = [c for c in all_val_metrics if c.region == region and c.target == target and not c.is_baseline]
            # Eligible: must beat persistence on every primary metric (MAE and RMSE)
            persist_val = next(c for c in all_val_metrics if c.region == region and c.target == target
                                and c.is_baseline and c.model_name == "bl_persist")
            eligible = [c for c in cand_results
                        if c.metrics["mae"] < persist_val.metrics["mae"]
                        and c.metrics["rmse"] < persist_val.metrics["rmse"]]
            if eligible:
                # Sort by MAE asc, then RMSE asc, then R² desc
                eligible.sort(key=lambda c: (c.metrics["mae"], c.metrics["rmse"], -c.metrics["r2"]))
                selected = eligible[0]
                rationale = (
                    f"selected={selected.model_name}; eligible (beats persistence on val MAE+RMSE); "
                    f"val MAE={selected.metrics['mae']:.4f} < persist {persist_val.metrics['mae']:.4f}; "
                    f"val RMSE={selected.metrics['rmse']:.4f} < persist {persist_val.metrics['rmse']:.4f}; "
                    f"selection rank by (MAE asc, RMSE asc, R² desc)."
                )
            else:
                # No ML beat persistence -> select persistence itself as the de-facto model
                # (per spec §9.4: persistent is the floor)
                selected = persist_val
                rationale = (
                    f"selected=bl_persist; no ML candidate beat persistence on val MAE+RMSE; "
                    f"falling back to persistence per spec §9.4."
                )

            # Load the selected model's pipeline and predict on the test set once
            if selected.model_name == "bl_persist":
                y_test_pred = test_pred_df[f"pred__bl_persist"].values
            else:
                spath = run_dir / f"models/{region}_{target}_{selected.model_name}.joblib"
                loaded = joblib.load(spath)
                y_test_pred = loaded["pipeline"].predict(X_test_full)

            test_pred_df[f"pred__selected"] = y_test_pred
            test_metrics = all_metrics(y_test, y_test_pred)
            persist_test_pred = test_pred_df["pred__bl_persist"].values
            persist_test_metrics = all_metrics(y_test, persist_test_pred)

            rec = SelectionRecord(
                region=region, target=target,
                selected_model=selected.model_name,
                selection_rationale=rationale,
                val_metrics=selected.metrics,
                persistence_val_metrics=persist_val.metrics,
                test_metrics=test_metrics,
                persistence_test_metrics=persist_test_metrics,
            )
            all_selections.append(rec)

            all_val_predictions.append(val_pred_df)
            all_test_predictions.append(test_pred_df)

    # ---------- 5. write artefacts ----------
    val_metrics_df = pd.DataFrame([asdict(c) for c in all_val_metrics])
    val_metrics_df.to_csv(run_dir / "validation_metrics.csv", index=False)

    selections_df = pd.DataFrame([asdict(s) for s in all_selections])
    selections_df.to_csv(run_dir / "selections.csv", index=False)

    val_preds_df = pd.concat(all_val_predictions, ignore_index=True)
    val_preds_path = run_dir / "validation_predictions.csv"
    val_preds_df.to_csv(val_preds_path, index=False)

    test_preds_df = pd.concat(all_test_predictions, ignore_index=True)
    test_preds_df.to_csv(run_dir / "test_predictions.csv", index=False)

    # Feature definitions
    feature_defs = {
        "feature_columns": FEATURE_COLUMNS,
        "target_columns": TARGET_COLUMNS,
        "definitions": _feature_definitions(),
    }
    (run_dir / "feature_definitions.json").write_text(json.dumps(feature_defs, indent=2), encoding="utf-8")

    # Model configs (capture each candidate's hyperparams; same for every region but persisted for reproducibility)
    model_cfgs = {
        mname: {
            "class": type(bind_prep(base_pipe, train_df[FEATURE_COLUMNS]).steps[-1][1]).__name__,
        }
        for mname, base_pipe in cand_specs.items()
    }
    (run_dir / "model_configs.json").write_text(json.dumps(model_cfgs, indent=2), encoding="utf-8")

    # Experiment config (with library versions)
    (run_dir / "experiment_config.json").write_text(json.dumps(cfg.as_dict(), indent=2), encoding="utf-8")

    # Save PM2.5 dropped-audit trail
    try:
        pm25_report.dropped_audit.to_csv(run_dir / "pm25_ingest_dropped_audit.csv", index=False)
    except Exception:
        pass

    # Summary
    summary = {
        "run_id": cfg.run_id,
        "run_dir": str(run_dir),
        "modelling_dataset_rows": len(df),
        "modelling_dataset_cols": df.shape[1],
        "split_train_rows": split_info.train_rows,
        "split_val_rows": split_info.val_rows,
        "split_test_rows": split_info.test_rows,
        "n_seeds_per_model_region_target": 1,  # single seed (deterministic per spec)
        "random_seed": cfg.random_seed,
        "candidates": list(cand_specs.keys()),
        "baselines": ["bl_persist", "bl_clim", "bl_trail7"],
        "selections": [
            {
                "region": s.region, "target": s.target, "selected_model": s.selected_model,
                "val_mae": s.val_metrics["mae"], "val_rmse": s.val_metrics["rmse"], "val_r2": s.val_metrics["r2"],
                "persist_val_mae": s.persistence_val_metrics["mae"],
                "persist_val_rmse": s.persistence_val_metrics["rmse"],
                "test_mae": s.test_metrics["mae"], "test_rmse": s.test_metrics["rmse"],
                "test_r2": s.test_metrics["r2"],
                "persist_test_mae": s.persistence_test_metrics["mae"],
                "persist_test_rmse": s.persistence_test_metrics["rmse"],
            }
            for s in all_selections
        ],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _feature_definitions() -> dict:
    """Plain-text descriptions of every feature column."""
    return {
        "pm25_t0": "PM2.5 value at t0 (the hour of forecast issuance = D 23:00).",
        "pm25_lag_24h": "PM2.5 24 hours before t0 (same hour, prior day).",
        "pm25_lag_48h": "PM2.5 48 hours before t0.",
        "pm25_lag_72h": "PM2.5 72 hours before t0.",
        "pm25_roll6h_mean": "Rolling 6-hour mean of PM2.5 ending at t0 (inclusive).",
        "pm25_roll6h_max": "Rolling 6-hour max of PM2.5 ending at t0 (inclusive).",
        "pm25_roll12h_mean": "Rolling 12-hour mean ending at t0.",
        "pm25_roll12h_max": "Rolling 12-hour max ending at t0.",
        "pm25_roll24h_mean": "Rolling 24-hour mean ending at t0.",
        "pm25_roll24h_max": "Rolling 24-hour max ending at t0.",
        "hour_of_day": "Calendar hour of t0 (always 23 in the Phase 1 setup but kept for generality).",
        "day_of_week": "0=Monday .. 6=Sunday, from t0.",
        "month": "Calendar month of t0.",
        "is_weekend": "1 if day_of_week in {5,6} else 0.",
        "monsoon_flag": "NE/SW/transitional (simple NEA convention; spec VERIFY for exact windows).",
        "wf_temp_high": "Latest national forecast's temperature_high, issue timestamp <= t0.",
        "wf_temp_low": "Latest national forecast's temperature_low.",
        "wf_rh_high": "Latest national forecast's relative_humidity_high.",
        "wf_rh_low": "Latest national forecast's relative_humidity_low.",
        "wf_wind_high": "Latest national forecast's wind_speed_high.",
        "wf_wind_low": "Latest national forecast's wind_speed_low.",
        "wf_wind_dir": "Latest national forecast's wind_speed_direction.",
        "wf_forecast_code": "Latest national forecast_code.",
        "wf_region_forecast_code": "Forecast code of the winning issue covering the first covered target hour, for the region.",
        "wf_n_rain_codes": "Count of covered target hours whose winning issue's region forecast_code is a rain code.",
        "wf_n_haze_codes": "Count of covered target hours whose winning issue's region forecast_code is a haze code.",
        "wf_window_coverage": "Fraction of [t0+1h, t0+24h] hours covered by an eligible forecast period.",
        "wf_n_issues_used": "Number of distinct forecast issues that contributed to the target window.",
        "wf_quality_flag": "ok | year_offset_repaired | no_weather (carried from period table per audit §15.4).",
    }
