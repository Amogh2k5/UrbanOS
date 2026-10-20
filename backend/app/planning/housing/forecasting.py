"""HDB Resale Price Forecasting Module.

Next-quarter median resale price forecasting by town and flat type.
Uses the official HDB median resale price dataset (data.gov.sg: d_b51323a474ba789fb4cc3db58a3116d4).

Prediction target:
- Median resale price (SGD) per town and flat type for the next quarter
- Frequency: Quarterly
- Horizon: 1 quarter ahead (t+1)
- Unit: SGD

Method:
- Leakage-safe walk-forward validation
- Baseline 1: Last-quarter persistence (prev quarter median)
- Baseline 2: Same-quarter-last-year seasonal persistence (4 quarters ago)
- Model: Gradient-boosted trees (XGBoost) only if it beats both baselines on held-out test quarters
- Sample size check: minimum 8 quarters per town/flat-type series required for ML
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd

from .data import fetch_housing_snapshot
from .processing import _str, _number, _period_key, build_housing_report
from .models import HousingReport

log = logging.getLogger(__name__)
SG = timezone(timedelta(hours=8))

# Model artifact directory
REPO_ROOT = Path(__file__).resolve().parents[4]
MODELS_DIR = REPO_ROOT / "ml" / "housing" / "models" / "production"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Forecasting configuration
MIN_QUARTERS_PER_SERIES = 8      # minimum quarters per town/flat-type series for ML
TEST_QUARTERS = 4                # hold-out test quarters
MIN_TRAIN_QUARTERS = 4           # minimum training quarters
MAX_LAGS = 4                     # maximum lag features

TARGET_COL = "median_price"
PERIOD_COL = "quarter"
TOWN_COL = "town"
FLAT_TYPE_COL = "flat_type"


def _quarter_to_ts(quarter: str) -> pd.Timestamp:
    """Convert 'YYYY-QN' to quarter-end timestamp for sorting."""
    m = re.match(r"(\d{4})-Q([1-4])", quarter, re.I)
    if not m:
        return pd.NaT
    year, q = int(m.group(1)), int(m.group(2))
    month = q * 3
    return pd.Timestamp(year=year, month=month, day=1, tz="Asia/Singapore")


def _ts_to_quarter(ts: pd.Timestamp) -> str:
    """Convert timestamp to 'YYYY-QN' format."""
    q = (ts.month - 1) // 3 + 1
    return f"{ts.year}-Q{q}"


def _next_quarter(quarter: str) -> str:
    """Return the next quarter string."""
    m = re.match(r"(\d{4})-Q([1-4])", quarter, re.I)
    if not m:
        return quarter
    year, q = int(m.group(1)), int(m.group(2))
    if q == 4:
        return f"{year + 1}-Q1"
    return f"{year}-Q{q + 1}"


def _prev_quarter(quarter: str) -> str:
    """Return the previous quarter string."""
    m = re.match(r"(\d{4})-Q([1-4])", quarter, re.I)
    if not m:
        return quarter
    year, q = int(m.group(1)), int(m.group(2))
    if q == 1:
        return f"{year - 1}-Q4"
    return f"{year}-Q{q - 1}"


@dataclass
class SeriesData:
    """Time series data for one town/flat-type combination."""
    town: str
    flat_type: str
    periods: List[str]
    values: List[float]
    timestamps: List[pd.Timestamp]


@dataclass
class BaselineResult:
    """Result from a baseline prediction."""
    method: str
    predictions: Dict[str, float]  # quarter -> predicted value
    mae: Optional[float] = None
    rmse: Optional[float] = None
    mape: Optional[float] = None


@dataclass
class ModelResult:
    """Result from model training and evaluation."""
    model_type: str
    predictions: Dict[str, float]
    mae: Optional[float] = None
    rmse: Optional[float] = None
    mape: Optional[float] = None
    feature_importance: Optional[Dict[str, float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ForecastPoint:
    """Single forecast point for a town/flat-type combination."""
    town: str
    flat_type: str
    forecast_period: str
    predicted_price: float
    method: str
    unit: str = "SGD"
    baseline_comparison: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ForecastReport:
    """Complete forecast report with evaluation."""
    target_quarter: str
    forecasts: List[ForecastPoint]
    method_used: str
    evaluation: Dict[str, Any]
    generated_at: datetime
    model_version: str
    data_freshness: str
    limitations: List[str]


def _fetch_and_prepare_data() -> List[SeriesData]:
    """Fetch housing snapshot and prepare time series by town/flat-type."""
    snapshot = fetch_housing_snapshot()
    median = snapshot["sources"]["median_resale"]
    
    if median.status != "available":
        raise ValueError("Median resale dataset unavailable")
    
    records = []
    for r in median.records:
        period = _str(r, "quarter", "Quarter")
        town = _str(r, "town", "Town")
        flat = _str(r, "flat_type", "Flat Type")
        price = _number(_str(r, "price", "Price"))
        
        if period and town and flat and price is not None:
            # Normalize town name (uppercase for consistency)
            town_norm = town.upper()
            records.append({
                "period": period,
                "town": town_norm,
                "flat_type": flat,
                "price": price,
                "ts": _quarter_to_ts(period),
            })
    
    if not records:
        raise ValueError("No valid records found in median resale data")
    
    df = pd.DataFrame(records)
    df = df.sort_values(["town", "flat_type", "ts"]).reset_index(drop=True)
    
    # Check for duplicates
    dupes = df.duplicated(subset=["town", "flat_type", "period"], keep=False)
    if dupes.any():
        log.warning(f"Found {dupes.sum()} duplicate town/flat-type/period records; keeping last")
        df = df.drop_duplicates(subset=["town", "flat_type", "period"], keep="last")
    
    # Group by town/flat_type
    series_list = []
    for (town, flat_type), group in df.groupby(["town", "flat_type"]):
        group = group.sort_values("ts")
        periods = group["period"].tolist()
        values = group["price"].tolist()
        timestamps = group["ts"].tolist()
        
        # Check minimum quarters
        if len(periods) >= MIN_QUARTERS_PER_SERIES:
            series_list.append(SeriesData(
                town=town,
                flat_type=flat_type,
                periods=periods,
                values=values,
                timestamps=timestamps,
            ))
        else:
            log.debug(f"Series {town}|{flat_type} has only {len(periods)} quarters, skipping ML")
    
    log.info(f"Prepared {len(series_list)} series with >= {MIN_QUARTERS_PER_SERIES} quarters")
    return series_list


def _create_features(series: SeriesData) -> pd.DataFrame:
    """Create lag and calendar features for a single series."""
    df = pd.DataFrame({
        "period": series.periods,
        "value": series.values,
        "ts": series.timestamps,
    })
    
    # Target: next quarter value
    df["target"] = df["value"].shift(-1)
    
    # Lag features
    for lag in range(1, MAX_LAGS + 1):
        df[f"lag_{lag}"] = df["value"].shift(lag)
    
    # Rolling statistics on available lags
    lag_cols = [f"lag_{lag}" for lag in range(1, MAX_LAGS + 1)]
    df["rolling_mean_3"] = df[lag_cols[:3]].mean(axis=1, skipna=True)
    df["rolling_std_3"] = df[lag_cols[:3]].std(axis=1, skipna=True)
    
    # Calendar features
    df["quarter_num"] = df["ts"].dt.quarter
    df["year"] = df["ts"].dt.year
    df["quarter_sin"] = np.sin(2 * np.pi * df["quarter_num"] / 4)
    df["quarter_cos"] = np.cos(2 * np.pi * df["quarter_num"] / 4)
    
    # Trend feature (linear trend over available lags)
    df["trend"] = np.arange(len(df))
    
    # Drop rows where target is NaN (last quarter)
    df = df.dropna(subset=["target"]).reset_index(drop=True)
    
    return df


def _prepare_training_data(series_list: List[SeriesData]) -> Tuple[pd.DataFrame, pd.Series]:
    """Prepare combined training data from all series."""
    all_features = []
    all_targets = []
    
    for series in series_list:
        feat_df = _create_features(series)
        if len(feat_df) < MIN_TRAIN_QUARTERS:
            continue
        
        # Add series identifiers as categorical features
        feat_df["town"] = series.town
        feat_df["flat_type"] = series.flat_type
        
        feature_cols = [c for c in feat_df.columns if c not in ["period", "value", "target", "ts", "town", "flat_type"]]
        X = feat_df[feature_cols]
        y = feat_df["target"]
        
        all_features.append(X)
        all_targets.append(y)
    
    if not all_features:
        raise ValueError("No series have sufficient data for training")
    
    X_all = pd.concat(all_features, ignore_index=True)
    y_all = pd.concat(all_targets, ignore_index=True)
    
    return X_all, y_all


def _time_based_split(periods: List[str], test_quarters: int = TEST_QUARTERS) -> Tuple[List[int], List[int]]:
    """Split indices by time: last test_quarters for test, rest for train."""
    n = len(periods)
    if n <= test_quarters + MIN_TRAIN_QUARTERS:
        return list(range(n - 1)), [n - 1]  # fallback: leave-one-out
    
    test_start = n - test_quarters
    train_idx = list(range(test_start))
    test_idx = list(range(test_start, n))
    return train_idx, test_idx


def _compute_metrics(y_true: Any, y_pred: Any) -> Tuple[float, float, float]:
    """Compute MAE, RMSE, MAPE."""
    y_true_arr = np.asarray(y_true)
    y_pred_arr = np.asarray(y_pred)
    mask = ~np.isnan(y_true_arr) & ~np.isnan(y_pred_arr)
    if not mask.any():
        return float("nan"), float("nan"), float("nan")

    y_t = y_true_arr[mask]
    y_p = y_pred_arr[mask]

    mae = np.mean(np.abs(y_t - y_p))
    rmse = np.sqrt(np.mean((y_t - y_p) ** 2))
    mape = np.mean(np.abs((y_t - y_p) / np.where(y_t != 0, y_t, np.nan))) * 100
    mape = float(np.nanmean(mape)) if not np.all(np.isnan(mape)) else float("nan")

    return float(mae), float(rmse), float(mape)


def _evaluate_baseline_persistence(series: SeriesData) -> BaselineResult:
    """Last-quarter persistence baseline."""
    predictions = {}
    y_true = []
    y_pred = []
    
    for i in range(1, len(series.periods)):
        pred_period = series.periods[i]
        pred_value = series.values[i - 1]
        predictions[pred_period] = pred_value
        y_true.append(series.values[i])
        y_pred.append(pred_value)
    
    mae, rmse, mape = _compute_metrics(np.array(y_true), np.array(y_pred))
    return BaselineResult(
        method="persistence_last_quarter",
        predictions=predictions,
        mae=mae,
        rmse=rmse,
        mape=mape,
    )


def _evaluate_baseline_seasonal(series: SeriesData) -> BaselineResult:
    """Same-quarter-last-year persistence baseline."""
    predictions = {}
    y_true = []
    y_pred = []
    
    for i in range(4, len(series.periods)):
        pred_period = series.periods[i]
        pred_value = series.values[i - 4]
        predictions[pred_period] = pred_value
        y_true.append(series.values[i])
        y_pred.append(pred_value)
    
    mae, rmse, mape = _compute_metrics(np.array(y_true), np.array(y_pred))
    return BaselineResult(
        method="persistence_same_quarter_last_year",
        predictions=predictions,
        mae=mae,
        rmse=rmse,
        mape=mape,
    )


def _train_xgboost_model(X_train: pd.DataFrame, y_train: pd.Series) -> Any:
    """Train XGBoost model."""
    try:
        import xgboost as xgb
    except ImportError:
        log.warning("XGBoost not available; skipping ML model")
        return None
    
    # Use native XGBoost for better control
    dtrain = xgb.DMatrix(X_train, label=y_train, enable_categorical=True)
    
    params = {
        "objective": "reg:squarederror",
        "eval_metric": "rmse",
        "eta": 0.05,
        "max_depth": 6,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 3,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "random_state": 42,
        "nthread": -1,
    }
    
    # Train with early stopping on a validation split
    n_train = len(X_train)
    val_split = int(n_train * 0.8)
    if val_split > 10:
        dtrain_sub = xgb.DMatrix(X_train.iloc[:val_split], label=y_train.iloc[:val_split])
        dval = xgb.DMatrix(X_train.iloc[val_split:], label=y_train.iloc[val_split:])
        evals = [(dtrain_sub, "train"), (dval, "val")]
        model = xgb.train(params, dtrain_sub, num_boost_round=500, evals=evals,
                          early_stopping_rounds=30, verbose_eval=False)
    else:
        model = xgb.train(params, dtrain, num_boost_round=200, verbose_eval=False)
    
    return model


def _predict_xgboost(model: Any, X: pd.DataFrame) -> np.ndarray:
    """Generate predictions from XGBoost model."""
    import xgboost as xgb
    dtest = xgb.DMatrix(X, enable_categorical=True)
    return model.predict(dtest)


def _evaluate_model_on_series(model: Any, series: SeriesData, feature_cols: List[str]) -> BaselineResult:
    """Evaluate model on a single series using walk-forward."""
    predictions = {}
    y_true = []
    y_pred = []
    
    df = _create_features(series)
    if len(df) < 2:
        return BaselineResult(method="xgboost", predictions={}, mae=None, rmse=None, mape=None)
    
    # Walk-forward: train on expanding window, predict next
    for i in range(MIN_TRAIN_QUARTERS, len(df)):
        train_df = df.iloc[:i]
        test_row = df.iloc[i:i+1]
        
        if len(train_df) < MIN_TRAIN_QUARTERS:
            continue
        
        X_train = train_df[feature_cols]
        y_train = train_df["target"]
        X_test = test_row[feature_cols]
        y_test = test_row["target"].values[0]
        
        try:
            model = _train_xgboost_model(X_train, y_train)
            if model is None:
                continue
            pred = _predict_xgboost(model, X_test)[0]
            pred_period = df.iloc[i]["period"]
            predictions[pred_period] = float(pred)
            y_true.append(y_test)
            y_pred.append(float(pred))
        except Exception as e:
            log.debug(f"Prediction failed for {series.town}|{series.flat_type} at {pred_period}: {e}")
            continue
    
    mae, rmse, mape = _compute_metrics(np.array(y_true), np.array(y_pred))
    return BaselineResult(
        method="xgboost_walkforward",
        predictions=predictions,
        mae=mae,
        rmse=rmse,
        mape=mape,
    )


def evaluate_all_series(series_list: List[SeriesData]) -> Dict[str, Any]:
    """Run evaluation on all series with sufficient data."""
    results = {
        "series_evaluated": 0,
        "persistence_mae": [],
        "seasonal_mae": [],
        "xgboost_mae": [],
        "per_series": {},
    }
    
    feature_cols = [f"lag_{lag}" for lag in range(1, MAX_LAGS + 1)] + \
                   ["rolling_mean_3", "rolling_std_3", "quarter_sin", "quarter_cos", "trend"]
    
    for series in series_list:
        key = f"{series.town}|{series.flat_type}"
        
        # Evaluate baselines
        pers = _evaluate_baseline_persistence(series)
        seas = _evaluate_baseline_seasonal(series)
        
        # Try ML if enough data
        xgb_result = _evaluate_model_on_series(None, series, feature_cols)  # placeholder
        
        # For now, just collect baseline results
        results["persistence_mae"].append(pers.mae)
        results["seasonal_mae"].append(seas.mae)
        results["per_series"][key] = {
            "persistence_mae": pers.mae,
            "seasonal_mae": seas.mae,
            "n_quarters": len(series.periods),
        }
        results["series_evaluated"] += 1
    
    # Aggregate metrics
    valid_pers = [m for m in results["persistence_mae"] if m is not None and not np.isnan(m)]
    valid_seas = [m for m in results["seasonal_mae"] if m is not None and not np.isnan(m)]
    
    results["aggregate"] = {
        "persistence_mae_mean": float(np.mean(valid_pers)) if valid_pers else None,
        "persistence_mae_median": float(np.median(valid_pers)) if valid_pers else None,
        "seasonal_mae_mean": float(np.mean(valid_seas)) if valid_seas else None,
        "seasonal_mae_median": float(np.median(valid_seas)) if valid_seas else None,
        "series_count": results["series_evaluated"],
    }
    
    return results


def train_and_persist_model() -> Dict[str, Any]:
    """Train final model on all data and persist artifacts."""
    log.info("Fetching and preparing data for model training...")
    series_list = _fetch_and_prepare_data()
    
    if not series_list:
        return {"status": "no_data", "message": "No series with sufficient data"}
    
    # Evaluate baselines first
    eval_results = evaluate_all_series(series_list)
    log.info(f"Baseline evaluation: {eval_results['aggregate']}")
    
    # For now, select the better baseline as production method
    pers_mae = eval_results["aggregate"]["persistence_mae_median"]
    seasonal_mae = eval_results["aggregate"]["seasonal_mae_median"]
    
    if pers_mae is not None and seasonal_mae is not None:
        if seasonal_mae < pers_mae:
            best_method = "seasonal_persistence"
            best_mae = seasonal_mae
        else:
            best_method = "persistence"
            best_mae = pers_mae
    elif pers_mae is not None:
        best_method = "persistence"
        best_mae = pers_mae
    elif seasonal_mae is not None:
        best_method = "seasonal_persistence"
        best_mae = seasonal_mae
    else:
        return {"status": "error", "message": "No baseline metrics available"}
    
    # Persist model metadata (using best baseline as "model" for now)
    model_metadata = {
        "model_type": best_method,
        "target": "median_resale_price_sgd",
        "frequency": "quarterly",
        "horizon": "1_quarter",
        "unit": "SGD",
        "feature_cols": [f"lag_{lag}" for lag in range(1, MAX_LAGS + 1)] + \
                        ["rolling_mean_3", "rolling_std_3", "quarter_sin", "quarter_cos", "trend"],
        "eval_results": eval_results["aggregate"],
        "best_method": best_method,
        "best_mae": best_mae,
        "trained_at": datetime.now(SG).isoformat(),
        "data_range": {
            "start": min(s.periods[0] for s in series_list),
            "end": max(s.periods[-1] for s in series_list),
        },
        "series_count": len(series_list),
        "min_quarters_per_series": MIN_QUARTERS_PER_SERIES,
        "test_quarters": TEST_QUARTERS,
        "model_version": f"housing_resale_v1_{datetime.now(SG).strftime('%Y%m%d')}",
    }
    
    # Save metadata
    metadata_path = MODELS_DIR / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(model_metadata, f, indent=2)
    
    # Create a simple baseline predictor artifact
    # For persistence: just store the latest values per series
    # For seasonal: store last 4 quarters per series
    baseline_artifact = {
        "method": best_method,
        "latest_values": {
            f"{s.town}|{s.flat_type}": {
                "period": s.periods[-1],
                "value": s.values[-1],
                "prev_period": s.periods[-2] if len(s.periods) > 1 else None,
                "prev_value": s.values[-2] if len(s.periods) > 1 else None,
                "seasonal_value": s.values[-4] if len(s.periods) >= 4 else None,
                "seasonal_period": s.periods[-4] if len(s.periods) >= 4 else None,
            }
            for s in series_list
        },
        "trained_at": datetime.now(SG).isoformat(),
    }
    
    artifact_path = MODELS_DIR / "baseline_predictor.joblib"
    joblib.dump(baseline_artifact, artifact_path)
    
    log.info(f"Persisted {best_method} baseline predictor to {artifact_path}")
    return {"status": "success", "metadata": model_metadata, "artifact_path": str(artifact_path)}


def load_baseline_predictor() -> Dict[str, Any]:
    """Load persisted baseline predictor."""
    artifact_path = MODELS_DIR / "baseline_predictor.joblib"
    if not artifact_path.exists():
        raise FileNotFoundError(f"Baseline predictor not found at {artifact_path}")
    return joblib.load(artifact_path)


def load_model_metadata() -> Dict[str, Any]:
    """Load model metadata."""
    metadata_path = MODELS_DIR / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Model metadata not found at {metadata_path}")
    with open(metadata_path) as f:
        return json.load(f)


def generate_forecast(target_quarter: Optional[str] = None) -> ForecastReport:
    """Generate next-quarter forecast using persisted baseline predictor."""
    predictor = load_baseline_predictor()
    metadata = load_model_metadata()
    
    method = predictor["method"]
    latest_values = predictor["latest_values"]
    
    # Determine target quarter
    if target_quarter is None:
        # Use the next quarter after the latest available period
        all_periods = set()
        for v in latest_values.values():
            all_periods.add(v["period"])
            if v.get("prev_period"):
                all_periods.add(v["prev_period"])
        latest_period = max(all_periods, key=_period_key)
        target_quarter = _next_quarter(latest_period)
    else:
        # Validate target quarter is in the future
        latest_period = max(v["period"] for v in latest_values.values())
        if _period_key(target_quarter) <= _period_key(latest_period):
            raise ValueError(f"Target quarter {target_quarter} must be after latest data {latest_period}")
    
    forecasts = []
    limitations = [
        f"Method: {method} (statistical baseline, not ML)",
        f"Forecast horizon: 1 quarter ahead ({target_quarter})",
        "Based on HDB median resale prices by town and flat type (official data.gov.sg dataset)",
        "Town/flat-type combinations with insufficient history excluded",
        "This is an analytical forecast, not an official HDB price index",
    ]
    
    if method == "persistence":
        for key, data in latest_values.items():
            town, flat_type = key.split("|", 1)
            forecasts.append(ForecastPoint(
                town=town,
                flat_type=flat_type,
                forecast_period=target_quarter,
                predicted_price=data["value"],
                method="persistence",
                baseline_comparison={"mae": metadata["eval_results"].get("persistence_mae_median")},
            ))
            limitations.append(f"Using last-quarter persistence for {key}")
    elif method == "seasonal_persistence":
        for key, data in latest_values.items():
            town, flat_type = key.split("|", 1)
            if data.get("seasonal_value") is not None:
                forecasts.append(ForecastPoint(
                    town=town,
                    flat_type=flat_type,
                    forecast_period=target_quarter,
                    predicted_price=data["seasonal_value"],
                    method="seasonal_persistence",
                    baseline_comparison={"mae": metadata["eval_results"].get("seasonal_mae_median")},
                ))
            else:
                forecasts.append(ForecastPoint(
                    town=town,
                    flat_type=flat_type,
                    forecast_period=target_quarter,
                    predicted_price=data["value"],
                    method="persistence_fallback",
                    baseline_comparison={"mae": metadata["eval_results"].get("persistence_mae_median")},
                ))
                limitations.append(f"Seasonal data unavailable for {key}, using persistence fallback")
    
    return ForecastReport(
        target_quarter=target_quarter,
        forecasts=forecasts,
        method_used=method,
        evaluation={
            "method": method,
            "mae": metadata["eval_results"].get(f"{method.split('_')[0]}_mae_median"),
            "baseline_comparison": metadata["eval_results"],
        },
        generated_at=datetime.now(SG),
        model_version=metadata["model_version"],
        data_freshness=max(v["period"] for v in latest_values.values()),
        limitations=limitations,
    )


def run_forecast_training() -> Dict[str, Any]:
    """CLI entry point for training."""
    return train_and_persist_model()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_forecast_training()
    print(json.dumps(result, indent=2, default=str))