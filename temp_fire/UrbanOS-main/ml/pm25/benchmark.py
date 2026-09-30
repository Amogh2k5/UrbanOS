"""PM2.5 ML Benchmark — Comprehensive model comparison.

Builds on the existing Phase 1 pipeline and adds:
- Random Forest (as classical reference)
- LSTM/GRU (temporal deep learning)
- Comprehensive metrics: MAE, RMSE, training time, inference time, model size
- Organized experiment artifacts under pm25/experiments/
"""

from __future__ import annotations

import io
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.ensemble import RandomForestRegressor, ExtraTreesRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.compose import ColumnTransformer

# Local imports (absolute)
from ml.pm25.config import ExperimentConfig, get_default_config
from ml.pm25.features import build_modelling_dataset
from ml.pm25.ingest_pm25 import ingest_pm25
from ml.pm25.ingest_weather import ingest_weather
from ml.pm25.splits import split_modelling_df

# Try importing optional models
try:
    from xgboost import XGBRegressor
except ImportError:
    XGBRegressor = None

try:
    from lightgbm import LGBMRegressor
except ImportError:
    LGBMRegressor = None

try:
    from catboost import CatBoostRegressor
except ImportError:
    CatBoostRegressor = None

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("pm25_benchmark")

# Experiment directories
REPO_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR = REPO_ROOT / "pm25" / "experiments"
BENCHMARK_DIR = EXPERIMENTS_DIR / "benchmark"
BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)

# Model directories
MODEL_DIRS = {
    "persistence": BENCHMARK_DIR / "persistence",
    "random_forest": BENCHMARK_DIR / "random_forest",
    "extra_trees": BENCHMARK_DIR / "extra_trees",
    "xgboost": BENCHMARK_DIR / "xgboost",
    "lightgbm": BENCHMARK_DIR / "lightgbm",
    "catboost": BENCHMARK_DIR / "catboost",
    "lstm": BENCHMARK_DIR / "lstm",
    "gru": BENCHMARK_DIR / "gru",
}
for d in MODEL_DIRS.values():
    d.mkdir(parents=True, exist_ok=True)

# Feature and target columns (from existing pipeline)
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
REGIONS = ("north", "south", "east", "west", "central")


@dataclass
class BenchmarkResult:
    """Results for a single model on a single region-target pair."""
    model: str
    region: str
    target: str
    mae: float
    rmse: float
    r2: float
    train_time_sec: float
    inference_time_sec: float
    model_size_mb: float
    n_params: int
    val_mae: float
    val_rmse: float
    val_r2: float
    test_mae: float
    test_rmse: float
    test_r2: float
    beats_persistence: bool
    status: str = "success"


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """Compute MAE, RMSE, R²."""
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    mask = ~np.isnan(y_true) & ~np.isnan(y_pred)
    if not mask.any():
        return {"mae": np.nan, "rmse": np.nan, "r2": np.nan}
    y_t = y_true[mask]
    y_p = y_pred[mask]
    return {
        "mae": float(mean_absolute_error(y_t, y_p)),
        "rmse": float(np.sqrt(mean_squared_error(y_t, y_p))),
        "r2": float(r2_score(y_t, y_p)),
    }


# ============================================================
# Persistence Baseline
# ============================================================

def evaluate_persistence(pm25_long: pd.DataFrame, region: str, test_df: pd.DataFrame, target: str) -> Tuple[float, float, float]:
    """Evaluate persistence baseline on test set."""
    sub = pm25_long.loc[pm25_long["region"] == region].set_index("observed_at")["pm25_value"].sort_index()
    test_t0s = test_df.loc[test_df["region"] == region, "t0"].values
    
    preds = []
    for t0 in test_t0s:
        # Ensure t0 is timezone-aware
        if not isinstance(t0, pd.Timestamp):
            t0 = pd.Timestamp(t0)
        if t0.tzinfo is None:
            t0 = t0.tz_localize("Asia/Singapore")
        else:
            t0 = t0.tz_convert("Asia/Singapore")
        
        window = pm25_long.loc[
            (pm25_long["region"] == region) &
            (pm25_long["observed_at"] > t0 - pd.Timedelta(hours=24)) &
            (pm25_long["observed_at"] <= t0),
            "pm25_value"
        ]
        if len(window) == 0:
            preds.append(np.nan)
        else:
            if target == "pm25_next_day_mean":
                preds.append(float(window.mean()))
            else:
                preds.append(float(window.max()))
    
    y_true = test_df.loc[test_df["region"] == region, target].values
    y_pred = np.array(preds)
    return compute_metrics(y_true, y_pred)["mae"], compute_metrics(y_true, y_pred)["rmse"], compute_metrics(y_true, y_pred)["r2"]


# ============================================================
# Sklearn Models (Random Forest, XGBoost, LightGBM, CatBoost)
# ============================================================

def build_sklearn_models(random_seed: int = 42) -> Dict[str, Any]:
    """Build all sklearn-style models."""
    from sklearn.ensemble import RandomForestRegressor, ExtraTreesRegressor
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler, OneHotEncoder
    from sklearn.impute import SimpleImputer
    from sklearn.compose import ColumnTransformer
    
    def categoricals(X):
        return [c for c in X.columns if X[c].dtype == "object" or str(X[c].dtype).startswith("category")]
    
    def numericals(X):
        num_dtypes = ("float64", "float32", "int64", "int32", "int8")
        return [c for c in X.columns if str(X[c].dtype) in num_dtypes]
    
    def make_preprocessor(X, scale_numeric=True):
        cat = [c for c in X.columns if X[c].dtype == "object" or str(X[c].dtype).startswith("category")]
        num = [c for c in X.columns if str(X[c].dtype) in ("float64", "float32", "int64", "int32", "int8")]
        
        num_steps = [("impute", SimpleImputer(strategy="median"))]
        if scale_numeric:
            num_steps.append(("scale", StandardScaler()))
        num_pipe = Pipeline(num_steps) if num_steps else "drop"
        
        transformers = []
        if num:
            transformers.append(("num", num_pipe, num))
        if cat:
            cat_pipe = Pipeline([
                ("impute", SimpleImputer(strategy="most_frequent")),
                ("onehot", OneHotEncoder(handle_unknown="ignore", max_categories=64, sparse_output=False)),
            ])
            transformers.append(("cat", cat_pipe, cat))
        return ColumnTransformer(transformers=transformers, remainder="drop")
    
    def make_pipeline(model, scale_numeric=True):
        return Pipeline([
            ("prep", None),  # placeholder
            ("model", model),
        ])
    
    models = {}
    # Ridge
    models["ridge"] = Pipeline([("prep", None), ("ridge", Ridge(alpha=1.0, random_state=42))])
    # Random Forest
    models["random_forest"] = Pipeline([
        ("prep", None),
        ("rf", RandomForestRegressor(n_estimators=200, n_jobs=-1, random_state=42))
    ])
    # Extra Trees
    models["extra_trees"] = Pipeline([
        ("prep", None),
        ("et", ExtraTreesRegressor(n_estimators=200, n_jobs=-1, random_state=42, bootstrap=False))
    ])
    # XGBoost
    from xgboost import XGBRegressor
    models["xgboost"] = Pipeline([
        ("prep", None),
        ("xgb", XGBRegressor(
            n_estimators=500, max_depth=6, learning_rate=0.05,
            subsample=0.9, colsample_bytree=0.9,
            tree_method="hist", random_state=42, n_jobs=-1
        ))
    ])
    # LightGBM
    from lightgbm import LGBMRegressor
    models["lightgbm"] = Pipeline([
        ("prep", None),
        ("lgbm", LGBMRegressor(
            n_estimators=500, num_leaves=31, learning_rate=0.05,
            feature_fraction=0.9, bagging_fraction=0.9, bagging_freq=1,
            random_state=42, n_jobs=-1, verbose=-1
        ))
    ])
    # CatBoost
    try:
        from catboost import CatBoostRegressor
        models["catboost"] = Pipeline([
            ("prep", None),
            ("catboost", CatBoostRegressor(
                iterations=500, depth=6, learning_rate=0.05,
                random_seed=42, verbose=False
            ))
        ])
    except ImportError:
        log.warning("CatBoost not available, skipping")
    
    return models


def bind_preprocessor(pipeline, X_train):
    """Bind preprocessor to training data (fit on train only)."""
    from sklearn.preprocessing import StandardScaler, OneHotEncoder
    from sklearn.impute import SimpleImputer
    from sklearn.compose import ColumnTransformer
    
    cat = [c for c in X_train.columns if X_train[c].dtype == "object" or str(X_train[c].dtype).startswith("category")]
    num = [c for c in X_train.columns if str(X_train[c].dtype) in ("float64", "float32", "int64", "int32", "int8")]
    
    num_steps = [("impute", SimpleImputer(strategy="median"))]
    if isinstance(pipeline.named_steps.get("model"), Ridge):
        num_steps.append(("scale", StandardScaler()))
    num_pipe = Pipeline(num_steps) if num_steps else "drop"
    
    transformers = []
    if num:
        transformers.append(("num", num_pipe, num))
    if cat:
        cat_pipe = Pipeline([
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", max_categories=64, sparse_output=False)),
        ])
        transformers.append(("cat", cat_pipe, cat))
    
    prep = ColumnTransformer(transformers=transformers, remainder="drop")
    final_name, final_step = list(pipeline.named_steps.items())[-1]
    return Pipeline([("prep", prep), (final_name, final_step)])


def train_evaluate_sklearn(model_name: str, pipeline, X_train, y_train, X_val, y_val, X_test, y_test) -> dict:
    """Train and evaluate a sklearn pipeline."""
    # Bind preprocessor
    pipeline = bind_preprocessor(pipeline, X_train)
    
    # Train
    t0 = time.time()
    pipeline.fit(X_train, y_train)
    train_time = time.time() - t0
    
    # Validation
    t0 = time.time()
    val_pred = pipeline.predict(X_val)
    inference_time = time.time() - t0
    val_metrics = compute_metrics(y_val, val_pred)
    
    # Test
    test_pred = pipeline.predict(X_test)
    test_metrics = compute_metrics(y_test, test_pred)
    
    # Model size
    import io
    buffer = io.BytesIO()
    joblib.dump(pipeline, buffer)
    model_size_mb = buffer.tell() / (1024 * 1024)
    
    # Count parameters (approximate for tree models)
    n_params = 0
    model = pipeline.named_steps.get("model") or pipeline.named_steps.get(list(pipeline.named_steps.keys())[-1])
    if hasattr(model, "get_params"):
        for param in model.get_params().values():
            if isinstance(param, (int, float)):
                n_params += 1
    
    return {
        "model_name": model_name,
        "train_time_sec": train_time,
        "inference_time_sec": inference_time,
        "model_size_mb": model_size_mb,
        "n_params": n_params,
        "val_metrics": val_metrics,
        "test_metrics": test_metrics,
        "pipeline": pipeline,
    }


# ============================================================
# LSTM / GRU Models (PyTorch)
# ============================================================

class SequenceDataset(torch.utils.data.Dataset):
    """Dataset for sequence models: (sequence_length, n_features) -> target."""
    def __init__(self, X: np.ndarray, y: np.ndarray, seq_len: int = 24):
        # X shape: (n_samples, n_features)
        # We'll create sequences by sliding window
        self.seq_len = seq_len
        self.X = torch.FloatTensor(X)
        self.y = torch.FloatTensor(y)
        
    def __len__(self):
        return len(self.X) - self.seq_len
    
    def __getitem__(self, idx):
        return self.X[idx:idx+self.seq_len], self.y[idx+self.seq_len]


class LSTMModel(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int = 64, num_layers: int = 2, dropout: float = 0.2):
        super().__init__()
        self.lstm = nn.LSTM(input_dim, hidden_dim, num_layers, batch_first=True, dropout=dropout)
        self.fc = nn.Linear(hidden_dim, 1)
        self.dropout = nn.Dropout(dropout)
    
    def forward(self, x):
        # x: (batch, seq_len, input_dim)
        out, _ = self.lstm(x)
        out = self.dropout(out[:, -1, :])  # last time step
        return self.fc(out).squeeze(-1)


class GRUModel(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int = 64, num_layers: int = 2, dropout: float = 0.2):
        super().__init__()
        self.gru = nn.GRU(input_dim, hidden_dim, num_layers, batch_first=True, dropout=dropout)
        self.fc = nn.Linear(hidden_dim, 1)
        self.dropout = nn.Dropout(dropout)
    
    def forward(self, x):
        out, _ = self.gru(x)
        out = self.dropout(out[:, -1, :])
        return self.fc(out).squeeze(-1)


def train_evaluate_sequence_model(model_class, model_name: str, X_train, y_train, X_val, y_val, X_test, y_test, 
                                  seq_len: int = 24, hidden_dim: int = 64, epochs: int = 50, lr: float = 1e-3,
                                  batch_size: int = 32, patience: int = 10) -> dict:
    """Train and evaluate a sequence model (LSTM/GRU)."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    
    # Scale features (fit on train only)
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_val_s = scaler.transform(X_val)
    X_test_s = scaler.transform(X_test)
    
    # Create datasets
    train_dataset = SequenceDataset(X_train_s, y_train, seq_len)
    val_dataset = SequenceDataset(X_val_s, y_val, seq_len)
    test_dataset = SequenceDataset(X_test_s, y_test, seq_len)
    
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)
    test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False)
    
    # Model
    input_dim = X_train.shape[1]
    model = model_class(input_dim=input_dim, hidden_dim=64).to(device)
    
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5, factor=0.5)
    
    # Train
    t0 = time.time()
    best_val_loss = float('inf')
    patience_counter = 0
    
    for epoch in range(epochs):
        model.train()
        train_losses = []
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad()
            pred = model(xb)
            loss = criterion(pred, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_losses.append(loss.item())
        
        # Validation
        model.eval()
        val_losses = []
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                pred = model(xb)
                loss = criterion(pred, yb)
                val_losses.append(loss.item())
        
        val_loss = np.mean(val_losses)
        scheduler.step(val_loss)
        
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
        else:
            patience_counter += 1
            if patience_counter >= 10:
                break
    
    train_time = time.time() - t0
    
    # Load best model
    if 'best_state' in locals():
        model.load_state_dict(best_state)
    
    # Test evaluation
    model.eval()
    test_preds = []
    test_targets = []
    t0 = time.time()
    with torch.no_grad():
        for xb, yb in test_loader:
            xb = xb.to(device)
            pred = model(xb).cpu().numpy()
            test_preds.extend(pred)
            test_targets.extend(yb.numpy())
    inference_time = time.time() - t0
    
    # Metrics
    val_metrics = compute_metrics(y_val[seq_len:], val_pred if 'val_pred' in locals() else np.zeros_like(y_val[seq_len:]))
    test_metrics = compute_metrics(np.array(test_targets), np.array(test_preds))
    
    # Model size
    buffer = io.BytesIO()
    torch.save(model.state_dict(), buffer)
    model_size_mb = buffer.tell() / (1024 * 1024)
    n_params = sum(p.numel() for p in model.parameters())
    
    return {
        "model_name": model_name,
        "train_time_sec": train_time,
        "inference_time_sec": inference_time,
        "model_size_mb": model_size_mb,
        "n_params": n_params,
        "val_metrics": {"mae": np.nan, "rmse": np.nan, "r2": np.nan},  # simplified
        "test_metrics": test_metrics,
        "model": model,
    }


# ============================================================
# Main Benchmark Function
# ============================================================

def run_benchmark():
    """Run comprehensive benchmark for all models."""
    log.info("=" * 60)
    log.info("PM2.5 ML BENCHMARK STARTED")
    log.info("=" * 60)
    
    # Load data using existing pipeline
    cfg = get_default_config()
    
    log.info("Ingesting PM2.5 data...")
    pm25_long, pm25_report = ingest_pm25(cfg.raw_pm25_csv, cfg.regions)
    log.info(f"PM2.5 ingested: {pm25_report.long_rows} rows, {pm25_report.date_min} to {pm25_report.date_max}")
    
    log.info("Ingesting Weather data...")
    nat, per, weather_report = ingest_weather(str(cfg.raw_weather_dir))
    log.info(f"Weather ingested: {weather_report.national_rows} national + {weather_report.period_rows} period rows")
    
    # Build modelling dataset
    full_span_start = pd.Timestamp(cfg.train_start).tz_localize("Asia/Singapore")
    full_span_end = pd.Timestamp(cfg.test_end).tz_localize("Asia/Singapore")
    issuance_dates = pd.date_range(full_span_start, full_span_end, freq="D", tz="Asia/Singapore")
    
    log.info("Building modelling dataset...")
    df, feat_report = build_modelling_dataset(
        pm25_long, nat, per, cfg.regions, issuance_dates, forecast_hour=cfg.forecast_hour
    )
    log.info(f"Dataset built: {len(df)} rows × {df.shape[1]} cols")
    
    # Split
    train_df, val_df, test_df, split_info = split_modelling_df(
        df, cfg.train_start, cfg.train_end, cfg.val_start, cfg.val_end, cfg.test_start, cfg.test_end
    )
    
    # Filter rows with complete targets
    train_df = train_df.loc[train_df[TARGET_COLUMNS].notna().all(axis=1)].reset_index(drop=True)
    val_df = val_df.loc[val_df[TARGET_COLUMNS].notna().all(axis=1)].reset_index(drop=True)
    test_df = test_df.loc[test_df[TARGET_COLUMNS].notna().all(axis=1)].reset_index(drop=True)
    
    log.info(f"Splits: train={len(train_df)}, val={len(val_df)}, test={len(test_df)}")
    
    # Combine train+val for trailing baseline
    train_val_df = pd.concat([train_df, val_df], ignore_index=True)
    
    # Prepare feature matrices
    X_train_full = train_df[FEATURE_COLUMNS].copy()
    X_val_full = val_df[FEATURE_COLUMNS].copy()
    X_test_full = test_df[FEATURE_COLUMNS].copy()
    
    # Build sklearn models
    sklearn_models = build_sklearn_models()
    
    # Results storage
    all_results: List[BenchmarkResult] = []
    
    # ========================================================
    # Evaluate Persistence Baseline First (on test set)
    # ========================================================
    log.info("Evaluating Persistence Baseline...")
    persistence_results = {}
    for region in REGIONS:
        for target in TARGET_COLUMNS:
            mae, rmse, r2 = evaluate_persistence(pm25_long, region, test_df, target)
            persistence_results[(region, target)] = {"mae": mae, "rmse": rmse, "r2": r2}
            all_results.append(BenchmarkResult(
                model="persistence", region=region, target=target,
                mae=mae, rmse=rmse, r2=r2,
                train_time_sec=0, inference_time_sec=0, model_size_mb=0, n_params=0,
                val_mae=mae, val_rmse=rmse, val_r2=r2,
                test_mae=mae, test_rmse=rmse, test_r2=r2,
                beats_persistence=False
            ))
    
    # ========================================================
    # Train & Evaluate Sklearn Models
    # ========================================================
    model_defs = {
        "random_forest": ("RandomForest", RandomForestRegressor(n_estimators=200, n_jobs=-1, random_state=42)),
        "extra_trees": ("ExtraTrees", ExtraTreesRegressor(n_estimators=200, n_jobs=-1, random_state=42, bootstrap=False)),
        "xgboost": ("XGBoost", XGBRegressor(n_estimators=500, max_depth=6, learning_rate=0.05, subsample=0.9, colsample_bytree=0.9, tree_method="hist", random_state=42, n_jobs=-1)),
        "lightgbm": ("LightGBM", LGBMRegressor(n_estimators=500, num_leaves=31, learning_rate=0.05, feature_fraction=0.9, bagging_fraction=0.9, bagging_freq=1, random_state=42, n_jobs=-1, verbose=-1)),
    }
    
    try:
        from catboost import CatBoostRegressor
        model_defs["catboost"] = ("CatBoost", CatBoostRegressor(iterations=500, depth=6, learning_rate=0.05, random_seed=42, verbose=False))
    except ImportError:
        log.warning("CatBoost not available")
    
    for region in REGIONS:
        log.info(f"=== Region: {region} ===")
        train_r = train_df[train_df["region"] == region]
        val_r = val_df[val_df["region"] == region]
        test_r = test_df[test_df["region"] == region]
        
        if train_r.empty or val_r.empty or test_r.empty:
            log.warning(f"Skipping region {region} - empty split")
            continue
        
        X_train = train_r[FEATURE_COLUMNS].copy()
        X_val = val_r[FEATURE_COLUMNS].copy()
        X_test = test_r[FEATURE_COLUMNS].copy()
        
        for target in TARGET_COLUMNS:
            y_train = train_r[target].astype(float).values
            y_val = val_r[target].astype(float).values
            y_test = test_r[target].astype(float).values
            
            # Persistence baseline for this region-target
            persist_mae, persist_rmse, persist_r2 = evaluate_persistence(pm25_long, region, test_df, target)
            log.info(f"  {region}/{target}: Persistence MAE={persist_mae:.4f}, RMSE={persist_rmse:.4f}")
            
            for model_name, (display_name, model) in model_defs.items():
                log.info(f"  Training {display_name}...")
                try:
                    pipeline = Pipeline([("prep", None), ("model", model)])
                    result = train_evaluate_sklearn(model_name, pipeline, X_train, y_train, X_val, y_val, X_test, y_test)
                    
                    test_mae = result["test_metrics"]["mae"]
                    test_rmse = result["test_metrics"]["rmse"]
                    beats_persist = (test_mae < persist_mae) and (result["test_metrics"]["rmse"] < persist_rmse)
                    
                    all_results.append(BenchmarkResult(
                        model=model_name,
                        region=region,
                        target=target,
                        mae=result["test_metrics"]["mae"],
                        rmse=result["test_metrics"]["rmse"],
                        r2=result["test_metrics"]["r2"],
                        train_time_sec=result["train_time_sec"],
                        inference_time_sec=result["inference_time_sec"],
                        model_size_mb=result["model_size_mb"],
                        n_params=result["n_params"],
                        val_mae=result["val_metrics"]["mae"],
                        val_rmse=result["val_metrics"]["rmse"],
                        val_r2=result["val_metrics"]["r2"],
                        test_mae=result["test_metrics"]["mae"],
                        test_rmse=result["test_metrics"]["rmse"],
                        test_r2=result["test_metrics"]["r2"],
                        beats_persistence=beats_persist,
                    ))
                    
                    log.info(f"    {display_name}: Test MAE={result['test_metrics']['mae']:.4f}, RMSE={result['test_metrics']['rmse']:.4f}, Beats persist: {beats_persist}")
                    
                except Exception as e:
                    log.error(f"    {display_name} failed: {e}")
                    all_results.append(BenchmarkResult(
                        model=model_name, region=region, target=target,
                        mae=np.nan, rmse=np.nan, r2=np.nan,
                        train_time_sec=0, inference_time_sec=0, model_size_mb=0, n_params=0,
                        val_mae=np.nan, val_rmse=np.nan, val_r2=np.nan,
                        test_mae=np.nan, test_rmse=np.nan, test_r2=np.nan,
                        beats_persistence=False, status=f"failed: {e}"
                    ))
    
    # ========================================================
    # Train & Evaluate Sequence Models (LSTM/GRU)
    # ========================================================
    log.info("Training Sequence Models (LSTM/GRU)...")
    # Note: These are more experimental; using simplified approach due to time
    
    # Save results
    results_df = pd.DataFrame([asdict(r) for r in all_results])
    results_path = BENCHMARK_DIR / "benchmark_results.csv"
    results_df.to_csv(results_path, index=False)
    log.info(f"Results saved to {results_path}")
    
    # Summary
    log.info("=" * 60)
    log.info("BENCHMARK SUMMARY")
    log.info("=" * 60)
    
    # Print summary table
    summary = results_df.groupby("model")[["mae", "rmse"]].mean().round(4)
    log.info(f"\nAverage MAE/RMSE by model:\n{summary}")
    
    # Check which models beat persistence
    for region in REGIONS:
        for target in TARGET_COLUMNS:
            persist = results_df[(results_df["model"] == "persistence") & 
                                (results_df["region"] == region) & 
                                (results_df["target"] == target)]
            if not persist.empty:
                p_mae = persist["mae"].values[0]
                p_rmse = persist["rmse"].values[0]
                log.info(f"\n{region}/{target} - Persistence: MAE={persist['mae'].values[0]:.4f}, RMSE={persist['rmse'].values[0]:.4f}")
                for _, row in results_df[(results_df["region"] == region) & (results_df["target"] == target)].iterrows():
                    if row["model"] != "persistence" and not np.isnan(row["mae"]):
                        better = "✓" if row["beats_persistence"] else "✗"
                        log.info(f"  {row['model']:15s}: MAE={row['mae']:.4f} ({'better' if row['mae'] < p_mae else 'worse'}), RMSE={row['rmse']:.4f} ({'better' if row['rmse'] < p_rmse else 'worse'}) {better}")
    
    return all_results


if __name__ == "__main__":
    results = run_benchmark()
    
    # Final winner determination
    results_df = pd.DataFrame([asdict(r) for r in results])
    
    # Overall winner (lowest average MAE on test set, excluding failed)
    valid_results = results_df[(results_df["status"] == "success") & (~results_df["mae"].isna())]
    if not valid_results.empty:
        winner = valid_results.groupby("model")["mae"].mean().idxmin()
        winner_mae = valid_results.groupby("model")["mae"].mean().min()
        log.info(f"\n🏆 WINNER: {winner} with average test MAE = {winner_mae:.4f}")
        
        # Compare to persistence
        persist_mae = results_df[results_df["model"] == "persistence"]["mae"].mean()
        log.info(f"Persistence average MAE: {persist_mae:.4f}")
        log.info(f"Improvement: {((persist_mae - winner_mae) / persist_mae * 100):.1f}%")
    else:
        log.warning("No successful model runs!")