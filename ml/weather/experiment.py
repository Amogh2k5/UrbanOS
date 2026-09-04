"""Weather ML experiment v3 - absolute targets with lagged-only features.

Task: Predict absolute next-day NEA forecast using ONLY historical lags (lag1, lag2, lag7).
Persistence baseline: wf_now (today's NEA forecast at t0) - which ML does NOT see.

This is a fairer comparison: ML learns from historical patterns, persistence gets today's forecast.
"""

from __future__ import annotations

import json
import logging
import platform
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score

from .features_v2 import _national_lag_features, _pm25_features_for_weather
from .splits import split_modelling_df
from ml.pm25.metrics import all_metrics as regression_metrics
from ml.pm25.ingest_pm25 import ingest_pm25
from ml.pm25.ingest_weather import ingest_weather
from ml.pm25.models import all_candidates, bind_prep


log = logging.getLogger("phase1b_weather_v3")


@dataclass
class ExperimentConfig:
    raw_weather_dir: Path = Path(__file__).resolve().parents[2] / "ml" / "datasets" / "raw" / "weather_24h" / "extracted"
    raw_pm25_csv: Path = Path(__file__).resolve().parents[2] / "ml" / "datasets" / "raw" / "pollution_pm25" / "Historical1hrPM2.5.csv"
    train_start: str = "2016-04-01"
    train_end: str = "2021-12-31 23:00:00"
    val_start: str = "2022-01-01"
    val_end: str = "2023-06-30 23:00:00"
    test_start: str = "2023-07-01"
    test_end: str = "2024-12-31 23:00:00"
    forecast_hour: int = 23
    random_seed: int = 20240101
    enable_catboost: bool = True
    runs_dir: Path = Path(__file__).resolve().parents[2] / "ml" / "datasets" / "processed" / "phase1b_weather" / "runs"
    run_id: str = "phase3_v1"


REGRESSION_TARGETS = (
    "temperature_high_next_day",
    "temperature_low_next_day",
    "relative_humidity_high_next_day",
    "relative_humidity_low_next_day",
    "wind_speed_high_next_day",
    "wind_speed_low_next_day",
)
CLASSIFICATION_TARGET = "forecast_code_next_day"
ALL_TARGETS = REGRESSION_TARGETS + (CLASSIFICATION_TARGET,)


TARGET_TO_SOURCE = {
    "temperature_high_next_day": "temperature_high",
    "temperature_low_next_day": "temperature_low",
    "relative_humidity_high_next_day": "relative_humidity_high",
    "relative_humidity_low_next_day": "relative_humidity_low",
    "wind_speed_high_next_day": "wind_speed_high",
    "wind_speed_low_next_day": "wind_speed_low",
    "forecast_code_next_day": "forecast_code",
}


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


def _classify_metrics(y_true, y_pred) -> dict:
    mask = ~(pd.isna(y_true) | pd.isna(y_pred))
    yt = np.array(y_true)[mask]
    yp = np.array(y_pred)[mask]
    if len(yt) == 0:
        return {"accuracy": np.nan, "macro_f1": np.nan, "n": 0}
    return {
        "accuracy": float(accuracy_score(yt, yp)),
        "macro_f1": float(f1_score(yt, yp, average="macro", zero_division=0)),
        "n": int(len(yt)),
    }


def _is_regression(target: str) -> bool:
    return not target.startswith("forecast_code")


def _metric_eligible(ml_metrics: dict, bl_metrics: dict, regression: bool) -> bool:
    if regression:
        mae_ml, rmse_ml = ml_metrics["mae"], ml_metrics["rmse"]
        mae_b, rmse_b = bl_metrics["mae"], bl_metrics["rmse"]
        if pd.isna(mae_ml) or pd.isna(rmse_ml):
            return False
        return (mae_ml < mae_b) and (rmse_ml < rmse_b)
    else:
        f1_ml, acc_ml = ml_metrics["macro_f1"], ml_metrics["accuracy"]
        f1_b, acc_b = bl_metrics["macro_f1"], bl_metrics["accuracy"]
        if pd.isna(f1_ml) or pd.isna(acc_ml):
            return False
        return (f1_ml > f1_b) and (acc_ml > acc_b)


def _primary_metric(metrics: dict, regression: bool) -> float:
    if regression:
        return metrics["mae"]
    return -metrics["macro_f1"]


def _load_inputs(cfg: ExperimentConfig) -> Tuple[pd.DataFrame, pd.DataFrame]:
    log.info("Ingesting PM2.5 ...")
    pm25_long, _ = ingest_pm25(str(cfg.raw_pm25_csv), ("north", "south", "east", "west", "central"))
    log.info("Ingesting Weather 24h ...")
    national, _period, _ = ingest_weather(str(cfg.raw_weather_dir))
    return pm25_long, national


def _build_modelling_dataset(pm25_long: pd.DataFrame, national: pd.DataFrame, cfg: ExperimentConfig):
    """Build modelling dataset with ABSOLUTE targets and LAGGED-ONLY features."""
    start = pd.Timestamp("2016-04-01").tz_localize("Asia/Singapore")
    end = pd.Timestamp("2024-12-31").tz_localize("Asia/Singapore")
    issuance_dates = pd.date_range(start.normalize(), end.normalize(), freq="D")

    t0s = pd.DatetimeIndex([
        (pd.Timestamp(d).tz_convert("Asia/Singapore") if pd.Timestamp(d).tzinfo is not None
         else pd.Timestamp(d).tz_localize("Asia/Singapore")).replace(hour=23, minute=0, second=0)
        for d in issuance_dates
    ])

    # 1. Lagged forecast features ONLY (no wf_now!)
    lag_feats = _national_lag_features(national, t0s, lags_days=(1, 2, 3, 7))

    # 2. PM2.5 national features
    pm25_feats = _pm25_features_for_weather(pm25_long, t0s)

    # 3. Absolute targets (next-day NEA forecast)
    targets = _build_absolute_targets(national, t0s)

    # Join
    df = lag_feats.join(pm25_feats, how="left").join(targets, how="left")

    # Calendar features
    df["hour_of_day"] = df.index.hour
    df["day_of_week"] = df.index.dayofweek
    df["month"] = df.index.month
    df["is_weekend"] = (df["day_of_week"] >= 5).astype("int8")
    df["monsoon_flag"] = pd.Series(df.index).map(monsoon_flag).values
    df["issuance_date"] = df.index.tz_convert("Asia/Singapore").normalize()

    df = df.reset_index(drop=True)
    df["t0"] = df["issuance_date"] + pd.Timedelta(hours=cfg.forecast_hour)

    # Feature columns (lagged forecasts only, no wf_now!)
    feature_cols = [
        # PM2.5 national
        "pm25_nat_t0", "pm25_nat_lag_24h", "pm25_nat_lag_72h",
        "pm25_nat_roll24h_mean", "pm25_nat_roll24h_max",
        # Calendar
        "hour_of_day", "day_of_week", "month", "is_weekend", "monsoon_flag",
        # Lagged forecasts ONLY (no wf_now!)
        "wf_lag1_temp_high", "wf_lag1_temp_low",
        "wf_lag1_rh_high", "wf_lag1_rh_low",
        "wf_lag1_wind_high", "wf_lag1_wind_low",
        "wf_lag1_wind_dir", "wf_lag1_forecast_code",
        "wf_lag2_temp_high", "wf_lag2_temp_low",
        "wf_lag2_rh_high", "wf_lag2_rh_low",
        "wf_lag2_wind_high", "wf_lag2_wind_low",
        "wf_lag2_wind_dir", "wf_lag2_forecast_code",
        "wf_lag3_temp_high", "wf_lag3_temp_low",
        "wf_lag3_rh_high", "wf_lag3_rh_low",
        "wf_lag3_wind_high", "wf_lag3_wind_low",
        "wf_lag3_wind_dir", "wf_lag3_forecast_code",
        "wf_lag7_temp_high", "wf_lag7_temp_low",
        "wf_lag7_rh_high", "wf_lag7_rh_low",
        "wf_lag7_wind_high", "wf_lag7_wind_low",
        "wf_lag7_wind_dir", "wf_lag7_forecast_code",
    ]
    target_cols = [
        "temperature_high_next_day",
        "temperature_low_next_day",
        "relative_humidity_high_next_day",
        "relative_humidity_low_next_day",
        "wind_speed_high_next_day",
        "wind_speed_low_next_day",
        "forecast_code_next_day",
        "target_issue_ts",
    ]

    ordered = ["issuance_date", "t0"] + target_cols + feature_cols
    df = df[ordered]

    from .features_v2 import FeatureReport
    rows_with_target = int(df["forecast_code_next_day"].notna().sum())
    rows_missing_target = int(df["forecast_code_next_day"].isna().sum())

    report = FeatureReport(
        rows=len(df),
        feature_columns=feature_cols,
        target_columns=target_cols,
        feature_null_counts={c: int(df[c].isna().sum()) for c in feature_cols},
        rows_with_target=rows_with_target,
        rows_missing_target=rows_missing_target,
    )
    return df, feature_cols, target_cols


def _build_absolute_targets(national: pd.DataFrame, t0s: pd.DatetimeIndex) -> pd.DataFrame:
    """Build absolute next-day targets (the NEA forecast issued tomorrow)."""
    nat = national.sort_values("timestamp").reset_index(drop=True)
    if nat["timestamp"].dt.tz is None:
        nat["timestamp"] = nat["timestamp"].dt.tz_localize("Asia/Singapore")
    else:
        nat["timestamp"] = nat["timestamp"].dt.tz_convert("Asia/Singapore")

    out_rows = []
    for t0 in t0s:
        next_day_start = (t0 + pd.Timedelta(days=1)).normalize()
        next_day_end = next_day_start + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        elig = nat[(nat["timestamp"] >= next_day_start) & (nat["timestamp"] <= next_day_end)]
        if elig.empty:
            out_rows.append(_null_abs_target_row(t0))
            continue
        latest = elig.sort_values("timestamp").iloc[-1]
        out_rows.append({
            "t0": t0,
            "temperature_high_next_day": _num(latest, "temperature_high"),
            "temperature_low_next_day": _num(latest, "temperature_low"),
            "relative_humidity_high_next_day": _num(latest, "relative_humidity_high"),
            "relative_humidity_low_next_day": _num(latest, "relative_humidity_low"),
            "wind_speed_high_next_day": _num(latest, "wind_speed_high"),
            "wind_speed_low_next_day": _num(latest, "wind_speed_low"),
            "forecast_code_next_day": _str(latest, "forecast_code"),
            "target_issue_ts": pd.Timestamp(latest["timestamp"]).isoformat(),
        })
    return pd.DataFrame(out_rows).set_index("t0")


def _null_abs_target_row(t0: pd.Timestamp) -> dict:
    return {
        "t0": t0,
        "temperature_high_next_day": np.nan,
        "temperature_low_next_day": np.nan,
        "relative_humidity_high_next_day": np.nan,
        "relative_humidity_low_next_day": np.nan,
        "wind_speed_high_next_day": np.nan,
        "wind_speed_low_next_day": np.nan,
        "forecast_code_next_day": None,
        "target_issue_ts": None,
    }


def _num(row: pd.Series, col: str):
    val = row.get(col)
    if pd.isna(val):
        return np.nan
    return float(val)


def _str(row: pd.Series, col: str):
    val = row.get(col)
    if pd.isna(val):
        return None
    return str(val)


def monsoon_flag(date: pd.Timestamp) -> str:
    m = date.month
    if m in (12, 1, 2, 3):
        return "NE"
    if m in (6, 7, 8, 9):
        return "SW"
    return "transitional"


from dataclasses import dataclass
from typing import List

@dataclass
class FeatureReport:
    rows: int
    feature_columns: List[str]
    target_columns: List[str]
    feature_null_counts: dict
    rows_with_target: int
    rows_missing_target: int


def _make_model(target_regression: bool, seed: int):
    cands = all_candidates(seed=seed, enable_catboost=True)
    return cands


def _swap_to_classifier(pipeline, model_name: str, seed: int):
    from sklearn.ensemble import ExtraTreesClassifier
    from sklearn.linear_model import RidgeClassifier
    prep = pipeline.steps[0][1]
    final_name = pipeline.steps[-1][0]
    if model_name == "ridge":
        final = RidgeClassifier(random_state=seed)
    elif model_name == "extra_trees":
        final = ExtraTreesClassifier(n_estimators=200, n_jobs=-1, random_state=seed, bootstrap=False)
    elif model_name == "xgb":
        from xgboost import XGBClassifier
        final = XGBClassifier(n_estimators=300, max_depth=6, learning_rate=0.05,
                              subsample=0.9, colsample_bytree=0.9, tree_method="hist",
                              random_state=seed, n_jobs=-1, use_label_encoder=False,
                              eval_metric="mlogloss")
    elif model_name == "lgbm":
        from lightgbm import LGBMClassifier
        final = LGBMClassifier(n_estimators=300, num_leaves=31, learning_rate=0.05,
                               feature_fraction=0.9, bagging_fraction=0.9, bagging_freq=1,
                               random_state=seed, n_jobs=-1, verbose=-1)
    elif model_name == "catboost":
        from catboost import CatBoostClassifier
        final = CatBoostClassifier(iterations=300, depth=6, learning_rate=0.05,
                                    random_seed=seed, verbose=False)
    else:
        final = pipeline.steps[-1][1]
    from sklearn.pipeline import Pipeline
    return Pipeline([("prep", prep), (final_name, final)])


def _fit_predict_one(model_name, pipeline, target, train_df, val_df, test_df, feature_cols):
    Xtr = train_df[feature_cols]
    ytr = train_df[target]
    Xval = val_df[feature_cols]
    Xtest = test_df[feature_cols]

    keep = ytr.notna()
    Xtr_use, ytr_use = Xtr[keep], ytr[keep]

    regression = _is_regression(target)
    if not regression:
        classes = sorted(ytr_use.dropna().unique().tolist())
        label_map = {c: i for i, c in enumerate(classes)}
        ytr_encoded = ytr_use.map(label_map)
        pipeline = bind_prep(pipeline, Xtr_use)
        pipeline = _swap_to_classifier(pipeline, model_name, seed=pipeline.steps[-1][1].random_state
                                        if hasattr(pipeline.steps[-1][1], "random_state") else 0)
        t0 = time.time()
        pipeline.fit(Xtr_use, ytr_encoded)
        fit_s = time.time() - t0
        t0 = time.time()
        yval_pred_enc = pipeline.predict(Xval)
        ytest_pred_enc = pipeline.predict(Xtest)
        predict_s = time.time() - t0
        inv_map = {i: c for c, i in label_map.items()}
        yval_pred = np.array([inv_map.get(int(p), None) for p in yval_pred_enc])
        ytest_pred = np.array([inv_map.get(int(p), None) for p in ytest_pred_enc])
        return fit_s, predict_s, yval_pred, ytest_pred, None, pipeline
    else:
        pipeline = bind_prep(pipeline, Xtr_use)
        t0 = time.time()
        pipeline.fit(Xtr_use, ytr_use.astype(float))
        fit_s = time.time() - t0
        t0 = time.time()
        yval_pred = pipeline.predict(Xval)
        ytest_pred = pipeline.predict(Xtest)
        predict_s = time.time() - t0
        return fit_s, predict_s, yval_pred, ytest_pred, None, pipeline


def run_experiment_v3(cfg: ExperimentConfig) -> dict:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
    cfg.library_versions = _capture_versions()
    run_dir = cfg.runs_dir / cfg.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    models_dir = run_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    pm25_long, national = _load_inputs(cfg)

    df, feature_cols, target_cols = _build_modelling_dataset(pm25_long, national, cfg)
    df.to_csv(run_dir / "modelling_dataset.csv", index=False)
    log.info("Modelling dataset: rows=%d, cols=%d", len(df), df.shape[1])

    train_df, val_df, test_df = split_modelling_df(
        df, cfg.train_start, cfg.train_end, cfg.val_start, cfg.val_end,
        cfg.test_start, cfg.test_end, require_targets=True,
    )
    log.info("Train=%d, Val=%d, Test=%d", len(train_df), len(val_df), len(test_df))

    validation_prediction_frames = {}
    test_prediction_frames = {}
    selections_rows = []
    all_target_results = []

    for target in ALL_TARGETS:
        regression = _is_regression(target)
        log.info("=== Target: %s (regression=%s) ===", target, regression)

        if not regression:
            train_t = train_df.dropna(subset=[target]).copy()
            val_t = val_df.dropna(subset=[target]).copy()
            test_t = test_df.dropna(subset=[target]).copy()
        else:
            train_t = train_df.dropna(subset=[target]).copy()
            val_t = val_df.dropna(subset=[target]).copy()
            test_t = test_df.dropna(subset=[target]).copy()

        if train_t.empty or val_t.empty:
            log.warning("Skipping target %s (empty train or val)", target)
            selections_rows.append({
                "target": target,
                "selected_model": "bl_persist",
                "selection_rationale": "insufficient training or validation data",
                "val_metrics": "{}", "persistence_val_metrics": "{}",
                "test_metrics": "{}", "persistence_test_metrics": "{}",
            })
            continue

        # --- Baselines ---
        # Persistence = wf_now (today's NEA forecast) - ML does NOT see this!
        # We need to get wf_now for val and test sets
        src_col = TARGET_TO_SOURCE[target]
        
        # Get wf_now for val and test by looking up the latest issue at each t0
        # Since the modelling dataset doesn't have wf_now, we compute it here
        bl_persist_val = _get_persistence_baseline(national, val_df, target, src_col)
        bl_persist_test = _get_persistence_baseline(national, test_df, target, src_col)

        if regression:
            bl_persist_val_metrics = regression_metrics(val_t[target].values, bl_persist_val)
            bl_persist_test_metrics = regression_metrics(test_t[target].values, bl_persist_test)
        else:
            bl_persist_val_metrics = _classify_metrics(val_t[target].values, bl_persist_val)
            bl_persist_test_metrics = _classify_metrics(test_t[target].values, bl_persist_test)

        # --- ML candidates ---
        cand_pipelines = _make_model(regression, cfg.random_seed)
        ml_results = {}
        ml_val_preds = {}
        ml_test_preds = {}
        ml_fitted_pipelines = {}

        for mname, pipeline in cand_pipelines.items():
            try:
                fit_s, pred_s, yv, yt, _, fitted = _fit_predict_one(
                    mname, pipeline, target, train_t, val_t, test_t, feature_cols,
                )
            except Exception as e:
                log.warning("Candidate %s failed on target %s: %s", mname, target, e)
                continue
            ml_val_preds[mname] = yv
            ml_test_preds[mname] = yt
            ml_fitted_pipelines[mname] = fitted
            if regression:
                mtr = regression_metrics(val_t[target].values, yv)
            else:
                mtr = _classify_metrics(val_t[target].values, yv)
            ml_results[mname] = {
                "fit_seconds": fit_s,
                "predict_seconds": pred_s,
                "val_metrics": mtr,
                "persistence_val_metrics": bl_persist_val_metrics,
                "delta_vs_persistence": {k: (mtr[k] - bl_persist_val_metrics[k]) for k in bl_persist_val_metrics},
                "is_baseline": False,
            }

        # --- Selection ---
        eligible_ml = [
            (mname, mr) for mname, mr in ml_results.items()
            if _metric_eligible(mr["val_metrics"], bl_persist_val_metrics, regression)
        ]
        if eligible_ml:
            eligible_ml.sort(key=lambda kv: _primary_metric(kv[1]["val_metrics"], regression))
            selected_model = eligible_ml[0][0]
            rationale = (
                f"selected={selected_model}; eligible (beats persistence on val "
                f"{'MAE+RMSE' if regression else 'macro_F1+accuracy'}); "
                f"val metrics={ml_results[selected_model]['val_metrics']}"
            )
        else:
            selected_model = "bl_persist"
            rationale = (
                f"selected=bl_persist; no ML candidate beat persistence on val "
                f"{'MAE+RMSE' if regression else 'macro_F1+accuracy'}; falling back to persistence."
            )

        if selected_model == "bl_persist":
            sel_val_pred = bl_persist_val
            sel_test_pred = bl_persist_test
            val_metrics = bl_persist_val_metrics
        else:
            sel_val_pred = ml_val_preds[selected_model]
            sel_test_pred = ml_test_preds[selected_model]
            val_metrics = ml_results[selected_model]["val_metrics"]

        if regression:
            sel_test_metrics = regression_metrics(test_t[target].values, sel_test_pred)
        else:
            sel_test_metrics = _classify_metrics(test_t[target].values, sel_test_pred)

        selections_rows.append({
            "target": target,
            "selected_model": selected_model,
            "selection_rationale": rationale,
            "val_metrics": json.dumps(val_metrics),
            "persistence_val_metrics": json.dumps(bl_persist_val_metrics),
            "test_metrics": json.dumps(sel_test_metrics),
            "persistence_test_metrics": json.dumps(bl_persist_test_metrics),
        })

        if selected_model != "bl_persist":
            artifact = {
                "pipeline": ml_fitted_pipelines[selected_model],
                "feature_columns": feature_cols,
                "target": target,
                "model_name": selected_model,
            }
            joblib.dump(artifact, models_dir / f"{target}_{selected_model}.joblib")

        val_pred_df = val_t[["t0", "issuance_date", target]].copy()
        val_pred_df["prediction"] = sel_val_pred
        val_pred_df["selected_model"] = selected_model
        val_pred_df["persistence_prediction"] = bl_persist_val
        validation_prediction_frames[target] = val_pred_df

        test_pred_df = test_t[["t0", "issuance_date", target]].copy()
        test_pred_df["prediction"] = sel_test_pred
        test_pred_df["selected_model"] = selected_model
        test_pred_df["persistence_prediction"] = bl_persist_test
        test_prediction_frames[target] = test_pred_df

        for mname, mr in ml_results.items():
            all_target_results.append({
                "target": target, "model_name": mname,
                "fit_seconds": mr["fit_seconds"], "predict_seconds": mr["predict_seconds"],
                "metrics": json.dumps(mr["val_metrics"]),
                "persistence_metrics": json.dumps(mr["persistence_val_metrics"]),
                "delta_vs_persistence": json.dumps(mr["delta_vs_persistence"]),
                "is_baseline": False,
            })
        all_target_results.append({
            "target": target, "model_name": "bl_persist",
            "fit_seconds": 0.0, "predict_seconds": 0.0,
            "metrics": json.dumps(bl_persist_val_metrics),
            "persistence_metrics": json.dumps(bl_persist_val_metrics),
            "delta_vs_persistence": json.dumps({k: 0.0 for k in bl_persist_val_metrics}),
            "is_baseline": True,
        })

    # --- Write artifacts ---
    val_metrics_rows = []
    for r in all_target_results:
        val_metrics_rows.append({
            "target": r["target"],
            "model_name": r["model_name"],
            "fit_seconds": r["fit_seconds"],
            "predict_seconds": r["predict_seconds"],
            "metrics": r["metrics"],
            "persistence_metrics": r["persistence_metrics"],
            "delta_vs_persistence": r["delta_vs_persistence"],
            "is_baseline": r["is_baseline"],
        })
    pd.DataFrame(val_metrics_rows).to_csv(run_dir / "validation_metrics.csv", index=False)
    pd.DataFrame(selections_rows).to_csv(run_dir / "selections.csv", index=False)

    all_val_preds = []
    for tgt, fr in validation_prediction_frames.items():
        fr2 = fr.copy()
        fr2["target"] = tgt
        all_val_preds.append(fr2)
    if all_val_preds:
        pd.concat(all_val_preds, ignore_index=True).to_csv(run_dir / "validation_predictions.csv", index=False)
    all_test_preds = []
    for tgt, fr in test_prediction_frames.items():
        fr2 = fr.copy()
        fr2["target"] = tgt
        all_test_preds.append(fr2)
    if all_test_preds:
        pd.concat(all_test_preds, ignore_index=True).to_csv(run_dir / "test_predictions.csv", index=False)

    summary = {
        "run_id": cfg.run_id,
        "run_dir": str(run_dir),
        "modelling_dataset_rows": int(len(df)),
        "modelling_dataset_cols": int(df.shape[1]),
        "split_train_rows": int(len(train_df)),
        "split_val_rows": int(len(val_df)),
        "split_test_rows": int(len(test_df)),
        "random_seed": cfg.random_seed,
        "targets": list(ALL_TARGETS),
        "candidates": ["ridge", "extra_trees", "xgb", "lgbm", "catboost"],
        "baselines": ["bl_persist"],
        "selections": [
            {
                "target": row["target"],
                "selected_model": row["selected_model"],
                "val_metrics": json.loads(row["val_metrics"]),
                "persistence_val_metrics": json.loads(row["persistence_val_metrics"]),
                "test_metrics": json.loads(row["test_metrics"]),
                "persistence_test_metrics": json.loads(row["persistence_test_metrics"]),
            }
            for row in selections_rows
        ],
        "library_versions": cfg.library_versions,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (run_dir / "experiment_config.json").write_text(json.dumps(cfg.__dict__, indent=2, default=str), encoding="utf-8")

    feature_defs = {
        "feature_columns": feature_cols,
        "target_columns": target_cols,
        "definitions": {"_task": "next-day NEA 24h forecast absolute (lagged-only features) (Phase 3)"},
    }
    (run_dir / "feature_definitions.json").write_text(json.dumps(feature_defs, indent=2), encoding="utf-8")

    return summary


def _get_persistence_baseline(national: pd.DataFrame, df: pd.DataFrame, target: str, src_col: str):
    """Get persistence baseline (wf_now) for each row in df."""
    nat = national.sort_values("timestamp").reset_index(drop=True)
    if nat["timestamp"].dt.tz is None:
        nat["timestamp"] = nat["timestamp"].dt.tz_localize("Asia/Singapore")
    else:
        nat["timestamp"] = nat["timestamp"].dt.tz_convert("Asia/Singapore")

    out = []
    for _, row in df.iterrows():
        t0 = row["t0"]
        eligible = nat[nat["timestamp"] <= t0]
        if eligible.empty:
            out.append(np.nan)
        else:
            latest = eligible.sort_values("timestamp").iloc[-1]
            if target == "forecast_code_next_day":
                out.append(_str(latest, src_col))
            else:
                out.append(_num(latest, src_col))
    return np.array(out)


def _load_inputs(cfg: ExperimentConfig) -> Tuple[pd.DataFrame, pd.DataFrame]:
    log.info("Ingesting PM2.5 ...")
    pm25_long, _ = ingest_pm25(str(cfg.raw_pm25_csv), ("north", "south", "east", "west", "central"))
    log.info("Ingesting Weather 24h ...")
    national, _period, _ = ingest_weather(str(cfg.raw_weather_dir))
    return pm25_long, national


if __name__ == "__main__":
    cfg = ExperimentConfig()
    summary = run_experiment_v3(cfg)
    print("=" * 70)
    print("Phase 3 Weather experiment complete.")
    print("  run_id          :", summary['run_id'])
    print("  run_dir         :", summary['run_dir'])
    print("  modelling rows  :", summary['modelling_dataset_rows'])
    print("  split           : train={}, val={}, test={}".format(
        summary['split_train_rows'], summary['split_val_rows'], summary['split_test_rows']))
    print("  targets         :", summary['targets'])
    print("=" * 70)
    print("Selections:")
    for sel in summary["selections"]:
        print("  {:<38} -> {}".format(sel['target'], sel['selected_model']))