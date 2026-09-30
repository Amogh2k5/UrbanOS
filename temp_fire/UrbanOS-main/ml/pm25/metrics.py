"""Evaluation metrics (spec §10).

Compute MAE (primary), RMSE (primary), and R² (secondary) per region, per target, per model.
Plus the persistence delta (ML_metric − persistence_metric) on validation and test.
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


def mae(y_true, y_pred) -> float:
    return float(mean_absolute_error(y_true, y_pred))


def rmse(y_true, y_pred) -> float:
    return float(np.sqrt(mean_squared_error(y_true, y_pred)))


def r2(y_true, y_pred) -> float:
    return float(r2_score(y_true, y_pred))


def all_metrics(y_true, y_pred) -> dict:
    return {
        "mae": mae(y_true, y_pred),
        "rmse": rmse(y_true, y_pred),
        "r2": r2(y_true, y_pred),
        "n": int(len(y_true)),
    }
