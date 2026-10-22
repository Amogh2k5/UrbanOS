"""
Energy Data Pipeline for UrbanOS.

Handles retrieval, validation, and processing of official Singapore energy datasets.
Sources:
- EMA half-hourly system demand data (if accessible)
- data.gov.sg official datasets (peak demand, solar, consumption)

This module provides a reproducible pipeline from source to forecast-ready data.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
import requests

from .data import DATASETS, fetch_snapshot
from .models import EnergyReport

log = logging.getLogger(__name__)

SG = timezone(timedelta(hours=8))

def _fetch_ema_halfhourly_demand() -> Optional[pd.DataFrame]:
    """
    Attempt to fetch EMA half-hourly system demand data.
    
    The EMA half-hourly system demand data page is behind Cloudflare protection.
    This function attempts to access it but falls back gracefully.
    
    Returns:
        DataFrame with half-hourly demand data, or None if unavailable.
    """
    # EMA half-hourly system demand data URL
    # This endpoint is behind Cloudflare/Incapsula protection
    # and cannot be accessed via automated requests without proper authentication
    ema_url = "https://www.ema.gov.sg/resources/statistics/half-hourly-system-demand-data"
    
    log.info("EMA half-hourly demand data source is behind Cloudflare protection.")
    log.info("Automated access not available without proper authentication.")
    log.info("Please manually download from: https://www.ema.gov.sg/resources/statistics/half-hourly-system-demand-data")
    
    # Check for manually downloaded file
    manual_path = Path("data/energy/ema_halfhourly_demand.csv")
    if manual_path.exists():
        log.info(f"Loading manual EMA data from {manual_path}")
        try:
            df = pd.read_csv(manual_path)
            # Validate required columns
            required_cols = {"timestamp", "demand_mw"}
            if not required_cols.issubset(set(df.columns)):
                log.warning(f"Manual EMA data missing required columns. Found: {df.columns.tolist()}")
                return None
            # Parse timestamps
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.sort_values("timestamp").reset_index(drop=True)
            log.info(f"Loaded {len(df)} half-hourly records from manual EMA data")
            return df
        except Exception as e:
            log.error(f"Failed to load manual EMA data: {e}")
            return None
    
    return None


def _load_data_gov_sg_datasets() -> Dict[str, Any]:
    """
    Load all datasets from data.gov.sg using the existing data module.
    
    Returns:
        Snapshot dictionary with datasets and metadata.
    """
    return fetch_snapshot()


def _process_peak_demand_to_monthly(snapshot: Dict[str, Any]) -> pd.DataFrame:
    """
    Process peak demand data to monthly time series.
    
    Args:
        snapshot: Raw snapshot from fetch_snapshot()
        
    Returns:
        DataFrame with columns: period (YYYY-MM), demand_mw (float)
    """
    peak_data = snapshot.get("datasets", {}).get("peak_demand")
    if not peak_data or not peak_data.get("records"):
        raise ValueError("Peak demand data not available")
    
    records = peak_data["records"]
    rows = []
    for row in records:
        year = int(row.get("year", 0))
        month = int(row.get("mth", 0))
        value = row.get("peak_system_demand_mw")
        
        if year == 0 or month == 0 or value is None:
            continue
            
        try:
            demand_mw = float(str(value).replace(",", ""))
        except (ValueError, TypeError):
            continue
            
        period = f"{year:04d}-{month:02d}"
        rows.append({"period": period, "demand_mw": demand_mw})
    
    df = pd.DataFrame(rows)
    df = df.sort_values("period").reset_index(drop=True)
    df["period_dt"] = pd.to_datetime(df["period"] + "-01")
    df = df.set_index("period_dt").sort_index()
    
    return df[["demand_mw"]]


def build_energy_dataset() -> EnergyDataset:
    """
    Build complete energy dataset from all available official sources.
    
    Returns:
        EnergyDataset with national peak demand and other verified datasets.
        NOTE: Regional demand is NOT included as no official regional demand data is available.
    """
    log.info("Building energy dataset from official sources...")
    
    # Load snapshot from data.gov.sg
    snapshot = _load_data_gov_sg_datasets()
    
    # Try to get EMA half-hourly data (will fall back to manual file)
    ema_data = _fetch_ema_halfhourly_demand()
    
    # Process national peak demand to monthly
    national_demand = _process_peak_demand_to_monthly(snapshot)
    log.info(f"Loaded national peak demand: {len(national_demand)} months ({national_demand.index.min()} to {national_demand.index.max()})")
    
    metadata = {
        "source": "data.gov.sg official datasets",
        "national_data_period": f"{national_demand.index.min().strftime('%Y-%m')} to {national_demand.index.max().strftime('%Y-%m')}",
        "data_freshness": datetime.now(SG).isoformat(),
        "note": "Only national-level data available. No official regional electricity demand data published by EMA.",
        "ema_halfhourly_available": ema_data is not None,
    }
    
    return EnergyDataset(
        national_peak_demand=national_demand,
        zone_demand={},  # Empty - no official regional data available
        metadata=metadata,
    )


# =============================================================================
# Feature Engineering
# =============================================================================

def create_features(df: pd.DataFrame, target_col: str = "demand_mw", max_lags: int = 12) -> pd.DataFrame:
    """
    Create time series features for forecasting.
    
    Args:
        df: DataFrame with datetime index and target column
        target_col: Name of target column
        max_lags: Maximum number of lag features to create
        
    Returns:
        DataFrame with features and target
    """
    df = df.copy()
    
    # Ensure datetime index
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame must have DatetimeIndex")
    
    # Target
    df["target"] = df[target_col]
    
    # Lag features
    for lag in range(1, max_lags + 1):
        df[f"lag_{lag}"] = df["target"].shift(lag)
    
    # Rolling statistics
    for window in [3, 6, 12]:
        df[f"rolling_mean_{window}"] = df["target"].rolling(window=window, min_periods=1).mean()
        df[f"rolling_std_{window}"] = df["target"].rolling(window=window, min_periods=1).std()
    
    # Calendar features
    df["month"] = df.index.month
    df["quarter"] = df.index.quarter
    df["year"] = df.index.year
    df["month_sin"] = np.sin(2 * np.pi * df.index.month / 12)
    df["month_cos"] = np.cos(2 * np.pi * df.index.month / 12)
    
    # Trend
    df["trend"] = np.arange(len(df))
    
    # Drop rows with NaN in target (last row after shift)
    df = df.dropna(subset=["target"])
    
    return df


def prepare_training_data(national_demand: pd.DataFrame, target_col: str = "demand_mw") -> Tuple[pd.DataFrame, pd.Series]:
    """
    Prepare training data for national peak demand forecasting.
    
    Args:
        national_demand: DataFrame with datetime index and demand_mw column
        target_col: Name of demand column
        
    Returns:
        Tuple of (X, y) for national peak demand forecasting
    """
    if "demand_mw" not in national_demand.columns:
        log.warning("Target column demand_mw not found, skipping")
        return pd.DataFrame(), pd.Series()
        
    # Create features
    feat_df = create_features(national_demand, target_col="demand_mw")
    
    # Drop rows with NaN in features (first 12 rows due to lags)
    feat_df = feat_df.dropna()
    
    if len(feat_df) < 24:  # Need at least 2 years of data
        log.warning(f"Insufficient data: {len(feat_df)} samples")
        return pd.DataFrame(), pd.Series()
        
    # Drop both the original target column and the engineered "target" column
    cols_to_drop = ["target", "demand_mw"]
    X = feat_df.drop(columns=[c for c in ["target", "demand_mw"] if c in feat_df.columns])
    y = feat_df["target"]
    
    log.info(f"Prepared national training data: {len(X)} samples, {X.shape[1]} features")
    return X, y


# =============================================================================
# Baseline Models
# =============================================================================

class BaselineForecaster:
    """Simple baseline forecasters for benchmarking."""
    
    def __init__(self, method: str = "persistence"):
        """
        Args:
            method: "persistence" (last value), "seasonal_naive" (same month last year), or "seasonal_persistence"
        """
        self.method = method
        self.last_values = {}
        self.history = None
    
    def fit(self, series: pd.Series):
        """Fit on historical series."""
        self.history = series.copy()
        self.last_values = series.iloc[-1] if len(series) > 0 else None
    
    def predict(self, horizon: int = 1) -> np.ndarray:
        """Generate predictions."""
        if self.method == "persistence":
            # Persistence: next value = last observed value
            return np.full(horizon, self.last_values)
        elif self.method == "seasonal_naive":
            # Seasonal naive: same month last year
            if len(self.history) < 12:
                return np.full(horizon, self.history.iloc[-1] if len(self.history) > 0 else 0)
            last_year = self.history.iloc[-12:]
            return np.tile(last_year.values, (horizon // 12) + 1)[:horizon]
        else:
            raise ValueError(f"Unknown method: {self.method}")


class SeasonalPersistenceForecaster:
    """Seasonal naive forecaster (same month last year)."""
    
    def __init__(self, seasonal_period: int = 12):
        self.seasonal_period = seasonal_period
        self.history = None
    
    def fit(self, series: pd.Series):
        self.history = series.copy()
    
    def predict(self, horizon: int = 1) -> np.ndarray:
        if len(self.history) < self.seasonal_period:
            return np.full(horizon, self.history.iloc[-1] if len(self.history) > 0 else 0)
        
        # Get the last seasonal cycle
        last_cycle = self.history.iloc[-self.seasonal_period:]
        # Tile to cover horizon
        return np.tile(last_cycle.values, (horizon // self.seasonal_period) + 1)[:horizon]


# =============================================================================
# ML Models
# =============================================================================

def train_xgboost_model(X_train: pd.DataFrame, y_train: pd.Series, params: Optional[Dict] = None):
    """Train XGBoost model and return a wrapper with scikit-learn compatible predict method."""
    try:
        import xgboost as xgb
    except ImportError:
        log.warning("XGBoost not installed, skipping")
        return None
    
    default_params = {
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
        "verbosity": 0,
    }
    
    if params:
        default_params.update(params)
    
    dtrain = xgb.DMatrix(X_train, label=y_train)  # Disable enable_categorical to avoid column name parsing issues
    booster = xgb.train(default_params, dtrain, num_boost_round=500, verbose_eval=False)
    
    # Wrap booster to provide sklearn-like predict interface
    class XGBoostWrapper:
        def __init__(self, booster, feature_names):
            self.booster = booster
            self.feature_names = feature_names
        
        def predict(self, X):
            if isinstance(X, pd.DataFrame):
                X = X[self.feature_names]
                dtest = xgb.DMatrix(X)  # Disable enable_categorical
            else:
                dtest = xgb.DMatrix(X)
            return self.booster.predict(dtest)
    
    return XGBoostWrapper(booster, list(X_train.columns))


def train_random_forest_model(X_train: pd.DataFrame, y_train: pd.Series, params: Optional[Dict] = None):
    """Train Random Forest model."""
    from sklearn.ensemble import RandomForestRegressor
    
    default_params = {
        "n_estimators": 200,
        "max_depth": 10,
        "min_samples_split": 5,
        "min_samples_leaf": 2,
        "random_state": 42,
        "n_jobs": -1,
    }
    
    if params:
        default_params.update(params)
    
    model = RandomForestRegressor(**default_params)
    model.fit(X_train, y_train)
    return model


# =============================================================================
# Evaluation
# =============================================================================

def evaluate_forecast(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """Compute evaluation metrics."""
    mask = ~np.isnan(y_true) & ~np.isnan(y_pred)
    if not mask.any():
        return {"mae": np.nan, "rmse": np.nan, "mape": np.nan}
    
    y_t = y_true[mask]
    y_p = y_pred[mask]
    
    mae = np.mean(np.abs(y_t - y_p))
    rmse = np.sqrt(np.mean((y_t - y_p) ** 2))
    
    # MAPE with protection against division by zero
    mape_values = np.abs((y_t - y_p) / np.where(y_t != 0, y_t, np.nan)) * 100
    mape = np.nanmean(mape_values)
    
    return {"mae": float(mae), "rmse": float(rmse), "mape": float(mape)}


def walk_forward_validation(
    X: pd.DataFrame,
    y: pd.Series,
    model_train_fn,
    initial_train_size: int,
    step_size: int = 1,
    horizon: int = 1,
) -> Dict[str, Any]:
    """
    Perform walk-forward validation for time series.
    
    Args:
        X: Feature matrix
        y: Target series
        model_train_fn: Function that trains model given (X_train, y_train)
        initial_train_size: Initial training window size
        step_size: Step size for rolling forward
        horizon: Forecast horizon
        
    Returns:
        Dictionary with predictions, actuals, and metrics
    """
    predictions = []
    actuals = []
    train_sizes = []
    
    n_samples = len(X)
    
    for i in range(initial_train_size, n_samples - horizon + 1, step_size):
        # Train on data up to i
        X_train = X.iloc[:i]
        y_train = y.iloc[:i]
        
        if len(y_train) < 12:  # Need minimum data
            continue
            
        try:
            model = model_train_fn(X_train, y_train)
            
            # Handle case where model training returns None (e.g., optional dependency not available)
            if model is None:
                log.warning(f"Model training returned None at index {i}, skipping step")
                continue
            
            # Predict next step(s)
            X_test = X.iloc[i:i+horizon]
            if len(X_test) == 0:
                continue
                
            # Handle different model interfaces
            if hasattr(model, "predict"):
                # Check if it's a baseline forecaster (predict takes horizon, not X)
                import inspect
                sig = inspect.signature(model.predict)
                params = list(sig.parameters.keys())
                if "horizon" in params and "X" not in params:
                    # Baseline forecaster: predict takes horizon
                    y_pred = model.predict(horizon)
                else:
                    # ML model: predict takes X
                    y_pred = model.predict(X_test)
            else:
                # Fallback for baseline forecasters without predict method
                y_pred = model.predict(horizon)
            
            y_true = y.iloc[i:i+horizon].values
            
            predictions.extend(y_pred[:len(y_true)])
            actuals.extend(y_true)
            train_sizes.append(len(y_train))
            
        except Exception as e:
            log.warning(f"Walk-forward step failed at index {i}: {e}")
            continue
    
    if not predictions:
        return {"predictions": [], "actuals": [], "metrics": {}}
    
    metrics = evaluate_forecast(np.array(actuals), np.array(predictions))
    
    return {
        "predictions": predictions,
        "actuals": actuals,
        "metrics": metrics,
        "train_sizes": train_sizes,
    }


# =============================================================================
# Model Registry & Persistence
# =============================================================================

MODEL_DIR = Path("ml/energy/models")
MODEL_DIR.mkdir(parents=True, exist_ok=True)


def save_model(model: Any, metadata: Dict[str, Any], model_name: str = "energy_forecast"):
    """Save model and metadata."""
    timestamp = datetime.now(SG).strftime("%Y%m%d_%H%M%S")
    model_path = MODEL_DIR / f"{model_name}_{timestamp}.joblib"
    meta_path = MODEL_DIR / f"{model_name}_{timestamp}_meta.json"
    
    joblib.dump(model, model_path)
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2, default=str)
    
    log.info(f"Saved model to {model_path}")
    return model_path, meta_path


def load_latest_model(model_name: str = "energy_forecast"):
    """Load latest model artifact."""
    model_files = list(MODEL_DIR.glob(f"{model_name}_*.joblib"))
    if not model_files:
        return None, None
    
    latest_model = max(model_files, key=lambda f: f.stat().st_mtime)
    meta_file = latest_model.with_name(latest_model.stem + "_meta.json")
    
    model = joblib.load(latest_model)
    metadata = {}
    if meta_file.exists():
        with open(meta_file) as f:
            metadata = json.load(f)
    
    return model, metadata


# =============================================================================
# Main Forecasting Pipeline
# =============================================================================

@dataclass
class ForecastResult:
    """Result of a forecast."""
    zone: str
    target_period: str  # YYYY-MM
    predicted_demand_mw: float
    model_name: str
    baseline_mae: Optional[float]
    model_mae: Optional[float]
    generated_at: datetime


def run_forecast_pipeline() -> Dict[str, Any]:
    """
    Run national peak demand forecasting pipeline.
    
    Returns:
        Dictionary with national forecast results.
    """
    log.info("Starting national peak demand forecast pipeline...")
    
    # Build dataset
    dataset = build_energy_dataset()
    
    # Prepare training data for national peak demand
    X, y = prepare_training_data(dataset.national_peak_demand)
    
    if X.empty or y.empty:
        raise ValueError("No training data available for national peak demand")
    
    log.info(f"Training national peak demand model ({len(X)} samples)...")
    
    # Baseline: Seasonal naive (same month last year)
    baseline = SeasonalPersistenceForecaster(seasonal_period=12)
    baseline.fit(dataset.national_peak_demand["demand_mw"])
    
    # Walk-forward validation for baseline
    def make_baseline(X_tr, y_tr):
        forecaster = SeasonalPersistenceForecaster(12)
        forecaster.fit(y_tr)
        return forecaster
    
    baseline_result = walk_forward_validation(
        X, y,
        make_baseline,
        initial_train_size=24,
        step_size=6,  # Larger step for faster validation
        horizon=1,
    )
    
    baseline_mae = baseline_result["metrics"].get("mae", np.nan)
    
    # Try ML models if enough data
    best_model = None
    best_mae = baseline_mae
    best_model_name = "seasonal_naive"
    
    if len(X) >= 36:  # Need at least 3 years for ML
        # Try Random Forest
        try:
            rf_model = train_random_forest_model(X, y)
            rf_result = walk_forward_validation(
                X, y,
                lambda X_tr, y_tr: train_random_forest_model(X_tr, y_tr),
                initial_train_size=24,
                step_size=6,  # Larger step for faster validation
                horizon=1,
            )
            rf_mae = rf_result["metrics"].get("mae", np.inf)
            
            if rf_mae < best_mae:
                best_mae = rf_mae
                best_model = rf_model
                best_model_name = "random_forest"
                log.info(f"Random Forest beat baseline: MAE={rf_mae:.2f}")
            except ImportError:
                pass
            
            # Try XGBoost
            try:
                xgb_model = train_xgboost_model(X, y)
                if xgb_model:
                    xgb_result = walk_forward_validation(
                        X, y,
                        lambda X_tr, y_tr: train_xgboost_model(X_tr, y_tr),
                        initial_train_size=24,
                        step_size=6,  # Larger step for faster validation
                        horizon=1,
                    )
                    xgb_mae = xgb_result["metrics"].get("mae", np.inf)
                    
                    if xgb_mae < best_mae:
                        best_mae = xgb_mae
                        best_model = xgb_model
                        best_model_name = "xgboost"
                        log.info(f"XGBoost beat baseline: MAE={xgb_mae:.2f}")
                except ImportError:
                    pass
        
        # Generate forecast for next month
        last_date = dataset.national_peak_demand.index[-1]
        next_month = last_date + pd.DateOffset(months=1)
        target_period = next_month.strftime("%Y-%m")
        
        if best_model_name == "seasonal_naive":
            # Use seasonal naive
            baseline.fit(dataset.national_peak_demand["demand_mw"])
            pred = baseline.predict(horizon=1)[0]
            model_name = "seasonal_naive"
        else:
            # Use best ML model
            X_latest = create_features(dataset.national_peak_demand, target_col="demand_mw").iloc[[-1]]
            pred = best_model.predict(X_latest)[0]
            model_name = "random_forest"  # or "xgboost"
        
        log.info(f"National forecast for {target_period} = {pred:.1f} MW (model: {best_model_name}, MAE: {best_mae:.1f})")
        
        return {
            "national_forecast": {
                "target_period": target_period,
                "predicted_demand_mw": float(pred),
                "model_name": best_model_name,
                "baseline_mae": float(baseline_mae) if not np.isnan(baseline_mae) else None,
                "model_mae": float(best_mae) if not np.isnan(best_mae) else None,
                "generated_at": datetime.now(SG).isoformat(),
            },
            "metadata": {
                "source": "data.gov.sg official peak demand dataset",
                "data_period": f"{dataset.national_peak_demand.index.min().strftime('%Y-%m')} to {dataset.national_peak_demand.index.max().strftime('%Y-%m')}",
                "note": "National peak system demand forecast. No official regional electricity demand data available from EMA.",
                "model_name": best_model_name,
                "baseline_mae": float(baseline_mae) if not np.isnan(baseline_mae) else None,
                "model_mae": float(best_mae) if not np.isnan(best_mae) else None,
                "data_freshness": datetime.now(SG).isoformat(),
                "limitations": [
                    "Based on national peak system demand data from EMA (data.gov.sg)",
                    "Monthly granularity only (no half-hourly data available)",
                    "Data ends July 2021 - not current",
                    "No official regional electricity demand data available from EMA",
                    "Forecast is for national peak system demand, not regional consumption"
                ]
            },
            "generated_at": datetime.now(SG).isoformat(),
        }


# =============================================================================
# Training Entry Point
# =============================================================================

def train_and_persist_models():
    """Train and persist national peak demand model."""
    log.info("Starting model training pipeline...")
    
    # Build dataset
    dataset = build_energy_dataset()
    
    # Prepare training data
    X, y = prepare_training_data(dataset.national_peak_demand)
    
    if X.empty or y.empty:
        raise ValueError("No training data available")
    
    # Evaluate baselines
    baseline = SeasonalPersistenceForecaster(12)
    baseline.fit(dataset.national_peak_demand["demand_mw"])
    
    baseline_result = walk_forward_validation(
        X, y,
        lambda X_tr, y_tr: SeasonalPersistenceForecaster(12).fit(y_tr),
        initial_train_size=24,
        step_size=1,
        horizon=1,
    )
    
    baseline_mae = baseline_result["metrics"].get("mae", np.inf)
    best_mae = baseline_mae
    best_model = None
    best_name = "seasonal_naive"
    
    # Random Forest
    try:
        rf_result = walk_forward_validation(
            X, y,
            lambda X_tr, y_tr: train_random_forest_model(X_tr, y_tr),
            initial_train_size=24,
            step_size=1,
            horizon=1,
        )
        rf_mae = rf_result["metrics"].get("mae", np.inf)
        if rf_mae < best_mae:
            best_mae = rf_mae
            best_model = train_random_forest_model(X, y)
            best_name = "random_forest"
    except ImportError:
        pass
    
    # XGBoost
    try:
        xgb_result = walk_forward_validation(
            X, y,
            lambda X_tr, y_tr: train_xgboost_model(X_tr, y_tr),
            initial_train_size=24,
            step_size=1,
            horizon=1,
        )
        xgb_mae = xgb_result["metrics"].get("mae", np.inf)
        if xgb_mae < best_mae:
            best_mae = xgb_mae
            best_model = train_xgboost_model(X, y)
            best_name = "xgboost"
    except ImportError:
        pass
    
    # LightGBM
    try:
        lgb_result = walk_forward_validation(
            X, y,
            lambda X_tr, y_tr: train_lightgbm_model(X_tr, y_tr),
            initial_train_size=24,
            step_size=1,
            horizon=1,
        )
        lgb_mae = lgb_result["metrics"].get("mae", np.inf)
        if lgb_mae < best_mae:
            best_mae = lgb_mae
            best_model = train_lightgbm_model(X, y)
            best_name = "lightgbm"
    except ImportError:
        pass
    
    # CatBoost
    try:
        cat_result = walk_forward_validation(
            X, y,
            lambda X_tr, y_tr: train_catboost_model(X_tr, y_tr),
            initial_train_size=24,
            step_size=1,
            horizon=1,
        )
        cat_mae = cat_result["metrics"].get("mae", np.inf)
        if cat_mae < best_mae:
            best_mae = cat_mae
            best_model = train_catboost_model(X, y)
            best_name = "catboost"
    except ImportError:
        pass
    
    # If ML model beats baseline, use it
    if best_model is not None:
        best_model = best_model
    else:
        best_model = baseline
    
    # Save model
    model_path = f"models/energy_national.joblib"
    joblib.dump(best_model, model_path)
    saved_models = {"national": model_path}
    
    log.info(f"Saved {best_name} model for national peak demand with MAE: {best_mae:.2f}")
    
    return {
        "models": saved_models,
        "metadata": {
            "source": "data.gov.sg official peak demand dataset",
            "data_period": "2005-2021",
            "target": "national peak system demand (MW)",
            "model": best_name,
            "mae": float(best_mae),
        },
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Run training
    result = train_and_persist_models()
    print(json.dumps(result, indent=2, default=str))
    
    # Generate forecast
    forecast_result = run_forecast_pipeline()
    print("\nForecasts:")
    for zone, fc in forecast_result["forecasts"].items():
        print(f"  {zone}: {fc.predicted_demand_mw:.1f} MW for {fc.target_period} (model: {fc.model_name})")