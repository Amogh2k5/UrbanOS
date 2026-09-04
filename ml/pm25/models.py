"""ML candidate model factory (spec §11).

Candidate models:
  M1: Ridge regression   (linear, with pipeline scaling + one-hot)
  M2: Random Forest / Extra Trees (configurable in experiment.py; default Extra Trees)
  M3: XGBoost
  M4: LightGBM
  M5: CatBoost (optional, native categorical handling — see config.ENABLE_CATBOOST rationale)

All candidates share the SAME feature matrix (same features, same chronological splits, same
target). No DL (spec §16, §22). Selecting by validation MAE (primary), RMSE (tiebreak), R² (secondary)
happens in experiment.py, not here.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


# Feature columns exposed to the model. The feature builder emits a stable ordered list.
# We pick the column lists here so models can drop the metadata/secondary columns.

# Categorical columns that need one-hot (for linear/ridge) OR native handling (catboost).
def categoricals(X: pd.DataFrame):
    return [c for c in X.columns if X[c].dtype == "object" or str(X[c].dtype).startswith("category")]


def numericals(X: pd.DataFrame):
    num_dtypes = ("float64", "float32", "int64", "int32", "int8")
    num = [c for c in X.columns if str(X[c].dtype) in num_dtypes]
    return num


def _build_preprocessor(X: pd.DataFrame, scale_numeric: bool) -> ColumnTransformer:
    cat = categoricals(X)
    num = numericals(X)
    cat_steps = None
    num_steps = []
    if num:
        num_steps.append(("impute", SimpleImputer(strategy="median")))
        if scale_numeric:
            num_steps.append(("scale", StandardScaler()))
    num_pipeline = Pipeline(num_steps) if num_steps else ("drop", "drop")

    transformers = []
    if num:
        transformers.append(("num", num_pipeline, num))
    if cat:
        cat_pipeline = Pipeline([
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", max_categories=64, sparse_output=False)),
        ])
        transformers.append(("cat", cat_pipeline, cat))
    return ColumnTransformer(transformers=transformers, remainder="drop")


def make_ridge(seed: int) -> Tuple[str, Pipeline]:
    """M1: Ridge regression. Standardization + one-hot for categoricals."""
    pp = lambda X: _build_preprocessor(X, scale_numeric=True)
    return (
        "ridge",
        Pipeline([
            ("prep", None),  # placeholder; set after first fit sees X
            ("ridge", Ridge(alpha=1.0, random_state=seed)),
        ]),
    )


def make_random_forest(seed: int, extra_trees: bool = True) -> Tuple[str, Any]:
    """M2: Random Forest or Extra Trees (spec §11.2 — 'Random Forest or Extra Trees')."""
    model_cls = ExtraTreesRegressor if extra_trees else RandomForestRegressor
    name = "extra_trees" if extra_trees else "random_forest"
    # Use the same one-hot preprocessor as Ridge — keeps categorical handling consistent across
    # all candidates. (Tree models can split on integers directly; one-hot is cleaner for the
    # NE/SW/transitional monsoon_flag and the weather codes that have no ordinal meaning.)
    return (
        name,
        Pipeline([
            ("prep", None),
            (name, model_cls(
                n_estimators=200,
                n_jobs=-1,
                random_state=seed,
                bootstrap=not extra_trees,  # ExtraTrees traditionally built without bootstrap
            )),
        ]),
    )


def make_xgb(seed: int) -> Tuple[str, Pipeline]:
    """M3: XGBoost (gradient-boosted trees). No native categorical — use one-hot pipeline."""
    from xgboost import XGBRegressor
    return (
        "xgb",
        Pipeline([
            ("prep", None),
            ("xgb", XGBRegressor(
                n_estimators=500,
                max_depth=6,
                learning_rate=0.05,
                subsample=0.9,
                colsample_bytree=0.9,
                tree_method="hist",
                random_state=seed,
                n_jobs=-1,
                early_stopping_rounds=None,  # No early stopping in fit-once; tuning is out-of-scope per spec
            )),
        ]),
    )


def make_lgbm(seed: int) -> Tuple[str, Pipeline]:
    """M4: LightGBM (gradient-boosted trees). No native categorical — use one-hot pipeline."""
    from lightgbm import LGBMRegressor
    return (
        "lgbm",
        Pipeline([
            ("prep", None),
            ("lgbm", LGBMRegressor(
                n_estimators=500,
                num_leaves=31,
                learning_rate=0.05,
                feature_fraction=0.9,
                bagging_fraction=0.9,
                bagging_freq=1,
                random_state=seed,
                n_jobs=-1,
                verbose=-1,
            )),
        ]),
    )


def make_catboost(seed: int) -> Tuple[str, Pipeline]:
    """M5: CatBoost. Rationale (config.ENABLE_CATBOOST): the Phase-1 feature set contains many
    categorical forecast codes (wf_forecast_code, wf_region_forecast_code, wf_wind_dir,
    monsoon_flag) and CatBoost handles them natively without one-hot — materially simpler
    pipeline than one-hot for the high-cardinality weather codes (audit Weather §8 notes a
    forecast-code vocabulary of ~19 codes nationally + region day/night variants). We use the
    same ColumnTransformer prep so all candidates share the same feature matrix; CatBoost then
    sees dense numeric and one-hot categorical features.
    """
    from catboost import CatBoostRegressor
    return (
        "catboost",
        Pipeline([
            ("prep", None),
            ("catboost", CatBoostRegressor(
                iterations=500,
                depth=6,
                learning_rate=0.05,
                random_seed=seed,
                verbose=False,
            )),
        ]),
    )


def all_candidates(seed: int, enable_catboost: bool, extra_trees: bool = True) -> Dict[str, Any]:
    """Return a dict {name: pipeline} of every candidate to evaluate.

    Every pipeline has its `prep` stage set to None on creation; the experiment runner
    binds the preprocessor right before fit() using the seen X columns (so it can match
    categorical columns actually present in the feature DataFrame).
    """
    cands = {}
    cands["ridge"] = make_ridge(seed)[1]
    name_et, et = make_random_forest(seed, extra_trees=extra_trees)
    cands[name_et] = et
    cands["xgb"] = make_xgb(seed)[1]
    cands["lgbm"] = make_lgbm(seed)[1]
    if enable_catboost:
        cands["catboost"] = make_catboost(seed)[1]
    return cands


def bind_prep(pipeline: Pipeline, X_train: pd.DataFrame) -> Pipeline:
    """Set the prep stage to match the columns of X_train (leakage-safe: fit on train only)."""
    # Use a copy so each candidate gets its own fitted prep without sharing state
    prep = _build_preprocessor(X_train, scale_numeric=isinstance(pipeline.steps[-1][1], Ridge))
    # Build a fresh Pipeline with the same final step
    final_name, final_step = pipeline.steps[-1]
    return Pipeline([("prep", prep), (final_name, final_step)])


def model_metadata(pipeline: Pipeline) -> dict:
    out = {}
    for name, step in pipeline.named_steps.items():
        cls = type(step).__name__
        params = {}
        # Collect fit-relevant hyperparams for reproducibility
        for key, val in step.get_params(deep=False).items():
            if isinstance(val, (int, float, str, bool, type(None))):
                params[key] = val
        out[name] = {"class": cls, "params": params}
    return out
