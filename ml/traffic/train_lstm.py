"""UrbanOS Traffic ML — Experimental LSTM Forecasting Pipeline.

Zone-level aggregation (8 zones) with regular 5-min time series.
Compares LSTM vs persistence vs existing XGBoost on same test horizon.
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.preprocessing import StandardScaler

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SEED = 42
np.random.seed(SEED)
torch.manual_seed(SEED)

SG_OFFSET = timezone(timedelta(hours=8))

DB_PATH = Path("data/traffic_observations_train.db")
MODEL_DIR = Path("traffic/models")
PROCESSED_DIR = Path("traffic/data/processed")
EXPERIMENT_DIR = Path("traffic/experiments/lstm")

os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)
os.makedirs(EXPERIMENT_DIR, exist_ok=True)

# LSTM Hyperparameters
SEQUENCE_LENGTH = 4  # 4 * ~5min = ~20 min history (reduced due to limited data)
PREDICTION_HORIZON = 1  # predict next step
BATCH_SIZE = 16
HIDDEN_SIZE = 32
NUM_LAYERS = 1
DROPOUT = 0.1
LEARNING_RATE = 1e-3
EPOCHS = 30
PATIENCE = 8

ZONE_IDS = [
    "SG_NORTH", "SG_NORTH_EAST", "SG_CENTRAL_NORTH", "SG_CENTRAL_SOUTH",
    "SG_EAST", "SG_WEST_NORTH", "SG_WEST_SOUTH", "SG_SENTOSA"
]


@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def load_complete_snapshots_zone_level() -> pd.DataFrame:
    """Load complete snapshots and aggregate to zone-level average speed."""
    logger.info("Loading complete snapshots and aggregating to zone level...")

    with get_db_connection() as conn:
        complete_timestamps = conn.execute("""
            SELECT observed_at FROM (
                SELECT observed_at, COUNT(*) as cnt
                FROM traffic_observations
                GROUP BY observed_at
                HAVING cnt = 143787
            )
            ORDER BY observed_at
        """).fetchall()

        timestamps = [r[0] for r in complete_timestamps]
        logger.info(f"Found {len(timestamps)} complete snapshots")

        if not timestamps:
            raise ValueError("No complete snapshots found")

        # Load in chunks to avoid large IN clause
        all_dfs = []
        chunk_size = 10
        for i in range(0, len(timestamps), chunk_size):
            chunk = timestamps[i:i+chunk_size]
            placeholders = ','.join(['?' for _ in chunk])
            query = f"""
                SELECT observed_at, zone_id, speed_midpoint
                FROM traffic_observations
                WHERE observed_at IN ({placeholders})
                  AND road_category IN (2,3,4,5,6)
                  AND speed_midpoint >= 0
                  AND speed_midpoint <= 120
                  AND zone_id IS NOT NULL
            """
            df_chunk = pd.read_sql_query(query, conn, params=chunk)
            all_dfs.append(df_chunk)

        df = pd.concat(all_dfs, ignore_index=True)

    logger.info(f"Loaded {len(df):,} observations for {df['observed_at'].nunique()} snapshots")

    df['observed_at'] = pd.to_datetime(df['observed_at']).dt.tz_convert(SG_OFFSET)

    # Aggregate to zone-level mean speed per timestamp
    zone_df = df.groupby(['observed_at', 'zone_id'])['speed_midpoint'].mean().reset_index()
    zone_df = zone_df.rename(columns={'speed_midpoint': 'zone_avg_speed'})

    logger.info(f"Aggregated to {zone_df['zone_id'].nunique()} zones, {zone_df['observed_at'].nunique()} timestamps")
    return zone_df


def create_regular_time_series(zone_df: pd.DataFrame) -> pd.DataFrame:
    """Use original timestamps directly (irregular but roughly 5-min during active periods).
    Sort and ensure we have a continuous sequence per zone."""
    logger.info("Using original timestamps (no resampling)...")

    # Simply sort by zone and timestamp
    long = zone_df.sort_values(['zone_id', 'observed_at']).reset_index(drop=True)

    logger.info(f"Series: {len(long)} rows, {long['zone_id'].nunique()} zones, {long['observed_at'].nunique()} timestamps")
    logger.info(f"Time range: {long['observed_at'].min()} to {long['observed_at'].max()}")

    return long


def add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add calendar features for each timestamp."""
    df = df.copy()
    df['hour'] = df['observed_at'].dt.hour
    df['minute'] = df['observed_at'].dt.minute
    df['day_of_week'] = df['observed_at'].dt.dayofweek
    df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
    df['is_peak'] = ((df['hour'] >= 7) & (df['hour'] <= 9) | (df['hour'] >= 17) & (df['hour'] <= 19)).astype(int)
    df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
    df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)
    df['dow_sin'] = np.sin(2 * np.pi * df['day_of_week'] / 7)
    df['dow_cos'] = np.cos(2 * np.pi * df['day_of_week'] / 7)
    return df


def chronological_split_by_timestamp(df: pd.DataFrame, train_ratio: float = 0.7, val_ratio: float = 0.15) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Split by unique timestamps chronologically."""
    unique_timestamps = sorted(df['observed_at'].unique())
    n = len(unique_timestamps)

    train_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))

    train_ts = set(unique_timestamps[:train_end])
    val_ts = set(unique_timestamps[train_end:val_end])
    test_ts = set(unique_timestamps[val_end:])

    train_mask = df['observed_at'].isin(train_ts)
    val_mask = df['observed_at'].isin(val_ts)
    test_mask = df['observed_at'].isin(test_ts)

    logger.info(f"Train timestamps: {len(train_ts)} ({train_mask.sum()} rows)")
    logger.info(f"Val timestamps: {len(val_ts)} ({val_mask.sum()} rows)")
    logger.info(f"Test timestamps: {len(test_ts)} ({test_mask.sum()} rows)")
    logger.info(f"Train range: {min(train_ts)} to {max(train_ts)}")
    logger.info(f"Val range: {min(val_ts)} to {max(val_ts)}")
    logger.info(f"Test range: {min(test_ts)} to {max(test_ts)}")

    return train_mask, val_mask, test_mask


def create_lstm_sequences(df: pd.DataFrame, feature_cols: List[str], target_col: str,
                          seq_len: int, horizon: int) -> Tuple[np.ndarray, np.ndarray]:
    """Create sequences for LSTM: X shape (samples, seq_len, features), y shape (samples, horizon)."""
    sequences_X = []
    sequences_y = []

    for zone in df['zone_id'].unique():
        zone_data = df[df['zone_id'] == zone].sort_values('observed_at').reset_index(drop=True)
        if len(zone_data) < seq_len + horizon:
            continue

        features = zone_data[feature_cols].values
        targets = zone_data[target_col].values

        for i in range(len(zone_data) - seq_len - horizon + 1):
            sequences_X.append(features[i:i+seq_len])
            sequences_y.append(targets[i+seq_len:i+seq_len+horizon])

    return np.array(sequences_X), np.array(sequences_y)


class TrafficLSTM(nn.Module):
    """LSTM model for traffic speed forecasting."""

    def __init__(self, input_size: int, hidden_size: int, num_layers: int, dropout: float, horizon: int):
        super().__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.horizon = horizon

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0,
            batch_first=True
        )
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size, horizon)

    def forward(self, x):
        # x: (batch, seq_len, input_size)
        lstm_out, _ = self.lstm(x)
        # Use last hidden state
        last_hidden = lstm_out[:, -1, :]
        out = self.dropout(last_hidden)
        out = self.fc(out)
        return out  # (batch, horizon)


def train_lstm(model: nn.Module, train_loader: DataLoader, val_loader: DataLoader,
               device: torch.device, epochs: int, patience: int, lr: float) -> Dict[str, List[float]]:
    """Train LSTM with early stopping."""
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    history = {'train_loss': [], 'val_loss': []}
    best_val_loss = float('inf')
    patience_counter = 0
    best_state = None

    for epoch in range(epochs):
        # Training
        model.train()
        train_losses = []
        for X_batch, y_batch in train_loader:
            X_batch, y_batch = X_batch.to(device), y_batch.to(device)
            optimizer.zero_grad()
            pred = model(X_batch)
            loss = criterion(pred, y_batch)
            loss.backward()
            optimizer.step()
            train_losses.append(loss.item())

        # Validation
        model.eval()
        val_losses = []
        with torch.no_grad():
            for X_batch, y_batch in val_loader:
                X_batch, y_batch = X_batch.to(device), y_batch.to(device)
                pred = model(X_batch)
                loss = criterion(pred, y_batch)
                val_losses.append(loss.item())

        train_loss = np.mean(train_losses)
        val_loss = np.mean(val_losses)
        history['train_loss'].append(train_loss)
        history['val_loss'].append(val_loss)

        logger.info(f"Epoch {epoch+1}/{epochs}: Train Loss={train_loss:.4f}, Val Loss={val_loss:.4f}")

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            best_state = model.state_dict().copy()
        else:
            patience_counter += 1
            if patience_counter >= patience:
                logger.info(f"Early stopping at epoch {epoch+1}")
                break

    if best_state:
        model.load_state_dict(best_state)

    return history


def evaluate_lstm(model: nn.Module, test_loader: DataLoader, device: torch.device,
                  scaler_y: StandardScaler) -> Tuple[np.ndarray, np.ndarray]:
    """Evaluate LSTM on test set, return predictions and targets in original scale."""
    model.eval()
    all_preds = []
    all_targets = []

    with torch.no_grad():
        for X_batch, y_batch in test_loader:
            X_batch = X_batch.to(device)
            pred = model(X_batch).cpu().numpy()
            all_preds.append(pred)
            all_targets.append(y_batch.numpy())

    preds = np.vstack(all_preds)
    targets = np.vstack(all_targets)

    # Inverse transform
    preds_orig = scaler_y.inverse_transform(preds.reshape(-1, 1)).flatten()
    targets_orig = scaler_y.inverse_transform(targets.reshape(-1, 1)).flatten()

    return preds_orig, targets_orig


def evaluate_persistence(df_test: pd.DataFrame, target_col: str) -> Tuple[float, float]:
    """Persistence baseline: predict current speed as next speed."""
    # For each zone, persistence = current zone_avg_speed
    # Need to align: target at t is zone_avg_speed at t, persistence prediction is zone_avg_speed at t-1
    # But our target is already the next step, so persistence is current speed
    y_true = df_test[target_col].values
    y_pred = df_test['zone_avg_speed'].values  # current speed as prediction for next step

    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    return mae, rmse


def load_xgb_predictions_for_comparison() -> Tuple[float, float]:
    """Load existing XGBoost test metrics for comparison."""
    metrics_path = MODEL_DIR / "model_metrics_speed_change.json"
    if metrics_path.exists():
        with open(metrics_path) as f:
            metrics = json.load(f)
        return metrics.get('test_mae'), metrics.get('test_rmse')
    return None, None


def main():
    logger.info("=" * 60)
    logger.info("URBANOS TRAFFIC ML — EXPERIMENTAL LSTM FORECASTING")
    logger.info("=" * 60)

    # 1. Load and aggregate to zone level
    zone_df = load_complete_snapshots_zone_level()

    # 2. Create regular 5-min time series
    zone_df = create_regular_time_series(zone_df)

    # 3. Add calendar features
    zone_df = add_calendar_features(zone_df)

    # 4. Create target: next 5-min zone average speed
    zone_df['target_speed'] = zone_df.groupby('zone_id')['zone_avg_speed'].shift(-1)
    zone_df = zone_df.dropna(subset=['target_speed']).reset_index(drop=True)

    # 5. Feature columns
    feature_cols = [
        'zone_avg_speed', 'hour', 'minute', 'day_of_week', 'is_weekend', 'is_peak',
        'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos'
    ]

    # 6. Chronological split
    train_mask, val_mask, test_mask = chronological_split_by_timestamp(zone_df)

    # 7. Scale features using training data only
    scaler_X = StandardScaler()
    scaler_y = StandardScaler()

    X_train = scaler_X.fit_transform(zone_df.loc[train_mask, feature_cols])
    X_val = scaler_X.transform(zone_df.loc[val_mask, feature_cols])
    X_test = scaler_X.transform(zone_df.loc[test_mask, feature_cols])

    y_train = scaler_y.fit_transform(zone_df.loc[train_mask, ['target_speed']])
    y_val = scaler_y.transform(zone_df.loc[val_mask, ['target_speed']])
    y_test = scaler_y.transform(zone_df.loc[test_mask, ['target_speed']])

    # 8. Create sequences
    logger.info("Creating LSTM sequences...")
    X_train_seq, y_train_seq = create_lstm_sequences(
        zone_df[train_mask].assign(**{c: X_train[:, i] for i, c in enumerate(feature_cols)}),
        feature_cols, 'target_speed', SEQUENCE_LENGTH, PREDICTION_HORIZON
    )
    X_val_seq, y_val_seq = create_lstm_sequences(
        zone_df[val_mask].assign(**{c: X_val[:, i] for i, c in enumerate(feature_cols)}),
        feature_cols, 'target_speed', SEQUENCE_LENGTH, PREDICTION_HORIZON
    )
    X_test_seq, y_test_seq = create_lstm_sequences(
        zone_df[test_mask].assign(**{c: X_test[:, i] for i, c in enumerate(feature_cols)}),
        feature_cols, 'target_speed', SEQUENCE_LENGTH, PREDICTION_HORIZON
    )

    logger.info(f"Train sequences: {X_train_seq.shape}, Val: {X_val_seq.shape}, Test: {X_test_seq.shape}")

    if len(X_train_seq) == 0:
        logger.error("Not enough data for sequences! Need at least SEQUENCE_LENGTH + horizon per zone.")
        return

    # 9. Create DataLoaders
    train_ds = TensorDataset(torch.FloatTensor(X_train_seq), torch.FloatTensor(y_train_seq))
    val_ds = TensorDataset(torch.FloatTensor(X_val_seq), torch.FloatTensor(y_val_seq))
    test_ds = TensorDataset(torch.FloatTensor(X_test_seq), torch.FloatTensor(y_test_seq))

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False)
    test_loader = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False)

    # 10. Initialize and train LSTM
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    logger.info(f"Using device: {device}")

    model = TrafficLSTM(
        input_size=len(feature_cols),
        hidden_size=HIDDEN_SIZE,
        num_layers=NUM_LAYERS,
        dropout=DROPOUT,
        horizon=PREDICTION_HORIZON
    ).to(device)

    logger.info(f"Model parameters: {sum(p.numel() for p in model.parameters()):,}")

    history = train_lstm(model, train_loader, val_loader, device, EPOCHS, PATIENCE, LEARNING_RATE)

    # 11. Evaluate on test set
    lstm_preds, lstm_targets = evaluate_lstm(model, test_loader, device, scaler_y)

    lstm_mae = mean_absolute_error(lstm_targets, lstm_preds)
    lstm_rmse = np.sqrt(mean_squared_error(lstm_targets, lstm_preds))

    logger.info(f"\nLSTM Test MAE: {lstm_mae:.4f}, RMSE: {lstm_rmse:.4f}")

    # 12. Persistence baseline on same test set
    df_test = zone_df[test_mask].copy()
    # Need to align test sequences with original rows
    # For simplicity, compute persistence on the test timestamps that have sequences
    test_timestamps_with_seq = sorted(zone_df[test_mask]['observed_at'].unique())[SEQUENCE_LENGTH:]
    df_test_aligned = df_test[df_test['observed_at'].isin(test_timestamps_with_seq)]
    pers_mae, pers_rmse = evaluate_persistence(df_test_aligned, 'target_speed')
    logger.info(f"Persistence Test MAE: {pers_mae:.4f}, RMSE: {pers_rmse:.4f}")

    # 13. Load XGBoost metrics for comparison
    xgb_mae, xgb_rmse = load_xgb_predictions_for_comparison()
    if xgb_mae:
        logger.info(f"XGBoost (speed_change) Test MAE: {xgb_mae:.4f}, RMSE: {xgb_rmse:.4f}")
        logger.info("Note: XGBoost predicts speed_change (different target), not directly comparable")

    # 14. Save experiment results
    results = {
        'experiment': 'lstm_zone_level',
        'timestamp': datetime.now(SG_OFFSET).isoformat(),
        'data': {
            'n_zones': int(zone_df['zone_id'].nunique()),
            'n_timestamps_regular': int(zone_df['observed_at'].nunique()),
            'time_range': [str(zone_df['observed_at'].min()), str(zone_df['observed_at'].max())],
            'train_timestamps': int(train_mask.sum()),
            'val_timestamps': int(val_mask.sum()),
            'test_timestamps': int(test_mask.sum()),
            'sequence_length': SEQUENCE_LENGTH,
            'prediction_horizon': PREDICTION_HORIZON,
            'features': feature_cols,
        },
        'model': {
            'hidden_size': HIDDEN_SIZE,
            'num_layers': NUM_LAYERS,
            'dropout': DROPOUT,
            'learning_rate': LEARNING_RATE,
            'epochs_trained': len(history['train_loss']),
            'params': sum(p.numel() for p in model.parameters()),
        },
        'results': {
            'lstm': {'mae': float(lstm_mae), 'rmse': float(lstm_rmse)},
            'persistence': {'mae': float(pers_mae), 'rmse': float(pers_rmse)},
            'xgboost_speed_change': {'mae': float(xgb_mae) if xgb_mae else None, 'rmse': float(xgb_rmse) if xgb_rmse else None},
            'lstm_beats_persistence': lstm_mae < pers_mae,
        },
        'training_history': history,
    }

    results_path = EXPERIMENT_DIR / "lstm_experiment_results.json"
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Results saved to {results_path}")

    # Save model
    model_path = EXPERIMENT_DIR / "lstm_model.pt"
    torch.save({
        'model_state_dict': model.state_dict(),
        'scaler_X': scaler_X,
        'scaler_y': scaler_y,
        'feature_cols': feature_cols,
        'seq_len': SEQUENCE_LENGTH,
        'horizon': PREDICTION_HORIZON,
        'model_config': {
            'input_size': len(feature_cols),
            'hidden_size': HIDDEN_SIZE,
            'num_layers': NUM_LAYERS,
            'dropout': DROPOUT,
            'horizon': PREDICTION_HORIZON,
        }
    }, model_path)
    logger.info(f"Model saved to {model_path}")

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("EXPERIMENT SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Data: {results['data']['n_zones']} zones, {results['data']['n_timestamps_regular']} timestamps")
    logger.info(f"Sequence length: {SEQUENCE_LENGTH} (~20 min), Horizon: {PREDICTION_HORIZON} (5 min)")
    logger.info(f"LSTM MAE: {lstm_mae:.4f}, RMSE: {lstm_rmse:.4f}")
    logger.info(f"Persistence MAE: {pers_mae:.4f}, RMSE: {pers_rmse:.4f}")
    logger.info(f"LSTM beats persistence: {lstm_mae < pers_mae}")
    logger.info(f"\n⚠️  WARNING: Only ~18 hours of data with large gaps. LSTM needs weeks/months for meaningful results.")
    logger.info(f"This is an EXPERIMENTAL run — not suitable for production deployment.")

    return results


if __name__ == '__main__':
    main()