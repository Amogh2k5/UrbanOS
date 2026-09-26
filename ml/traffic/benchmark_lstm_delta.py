import os
import json
import logging
import sqlite3
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.metrics import mean_absolute_error, mean_squared_error
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SEED = 42
np.random.seed(SEED)
torch.manual_seed(SEED)

SG_OFFSET = timezone(timedelta(hours=8))
DB_PATH = Path("data/traffic_observations_train.db")

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

REGION_ZONE_MAP = {
    "Central North": ["SG_CENTRAL_NORTH"],
    "Central South": ["SG_CENTRAL_SOUTH"],
    "East": ["SG_EAST"],
    "North": ["SG_NORTH", "SG_NORTH_EAST"],
    "West": ["SG_WEST_NORTH", "SG_WEST_SOUTH"],
}
REGION_ORDER = ["Central North", "Central South", "East", "North", "West"]

def load_complete_snapshots():
    logger.info("Loading complete snapshots from database...")
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
        placeholders = ','.join(['?' for _ in timestamps])
        query = f"""
            SELECT observed_at, zone_id, speed_midpoint
            FROM traffic_observations
            WHERE observed_at IN ({placeholders})
              AND road_category IN (2,3,4,5,6)
              AND speed_midpoint >= 0
              AND speed_midpoint <= 120
            ORDER BY observed_at, zone_id
        """
        df = pd.read_sql_query(query, conn, params=timestamps)
        logger.info(f"Loaded {len(df):,} observations for {df['observed_at'].nunique()} snapshots")
        df['observed_at'] = pd.to_datetime(df['observed_at']).dt.tz_convert(SG_OFFSET)
        return df

def aggregate_to_regions(df):
    zone_to_region = {}
    for region, zones in REGION_ZONE_MAP.items():
        for z in zones:
            zone_to_region[z] = region
    df = df.copy()
    df['region'] = df['zone_id'].map(zone_to_region)
    df = df.dropna(subset=['region'])
    agg = df.groupby(['observed_at', 'region'])['speed_midpoint'].mean().reset_index()
    pivot = agg.pivot(index='observed_at', columns='region', values='speed_midpoint')
    pivot = pivot.reindex(columns=REGION_ORDER)
    pivot = pivot.sort_index()
    return pivot

def build_sequences_delta(pivot_df, seq_len):
    """Create sequences for predicting delta (next - current) per region."""
    data = pivot_df.values.astype(np.float32)  # (T, 5)
    T = data.shape[0]
    X, y = [], []
    for i in range(T - seq_len):
        # input: seq_len past speeds
        X.append(data[i:i+seq_len])
        # target: delta = speed at t+1 - speed at t (where t = i+seq_len-1)
        current = data[i+seq_len-1]
        nxt = data[i+seq_len]
        delta = nxt - current
        y.append(delta)
    X = np.array(X)  # (N, seq_len, 5)
    y = np.array(y)  # (N, 5)
    return X, y, data

def chronological_split_indices(n_samples, train_ratio=0.7, val_ratio=0.15):
    train_end = int(n_samples * train_ratio)
    val_end = int(n_samples * (train_ratio + val_ratio))
    train_idx = np.arange(0, train_end)
    val_idx = np.arange(train_end, val_end)
    test_idx = np.arange(val_end, n_samples)
    return train_idx, val_idx, test_idx

class SimpleLSTM(nn.Module):
    def __init__(self, input_size=5, hidden_size=64, output_size=5, dropout=0.1):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, batch_first=True)
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size, output_size)

    def forward(self, x):
        out, _ = self.lstm(x)
        out = out[:, -1, :]
        out = self.dropout(out)
        out = self.fc(out)
        return out

def train_model(model, train_loader, val_loader, epochs=50, lr=1e-3, patience=10, device='cpu'):
    model.to(device)
    criterion = nn.L1Loss()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    best_val = float('inf')
    best_state = None
    patience_counter = 0
    for epoch in range(epochs):
        model.train()
        train_losses = []
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad()
            preds = model(xb)
            loss = criterion(preds, yb)
            loss.backward()
            optimizer.step()
            train_losses.append(loss.item())
        model.eval()
        val_losses = []
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                preds = model(xb)
                loss = criterion(preds, yb)
                val_losses.append(loss.item())
        val_mae = np.mean(val_losses)
        logger.info(f"Epoch {epoch+1}: train MAE={np.mean(train_losses):.4f}, val MAE={val_mae:.4f}")
        if val_mae < best_val:
            best_val = val_mae
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1
            if patience_counter >= patience:
                logger.info(f"Early stopping at epoch {epoch+1}")
                break
    if best_state:
        model.load_state_dict(best_state)
    return model

def evaluate(model, loader, device='cpu'):
    model.eval()
    preds_all = []
    targets_all = []
    with torch.no_grad():
        for xb, yb in loader:
            xb = xb.to(device)
            preds = model(xb).cpu().numpy()
            preds_all.append(preds)
            targets_all.append(yb.numpy())
    preds_all = np.vstack(preds_all)
    targets_all = np.vstack(targets_all)
    mae = mean_absolute_error(targets_all, preds_all)
    rmse = np.sqrt(mean_squared_error(targets_all, preds_all))
    return mae, rmse, preds_all, targets_all

def persistence_baseline_delta(test_loader, device='cpu'):
    # persistence predicts zero delta
    all_targets = []
    for _, yb in test_loader:
        all_targets.append(yb.numpy())
    targets = np.vstack(all_targets)
    mae = mean_absolute_error(targets, np.zeros_like(targets))
    rmse = np.sqrt(mean_squared_error(targets, np.zeros_like(targets)))
    return mae, rmse

def main():
    logger.info("=== SIMPLE LSTM TRAFFIC BENCHMARK (DELTA TARGET) ===")
    df = load_complete_snapshots()
    pivot = aggregate_to_regions(df)
    logger.info(f"Pivot shape: {pivot.shape}, time range: {pivot.index.min()} to {pivot.index.max()}")
    continuous_start = pd.Timestamp('2026-08-21 13:53:00', tz=SG_OFFSET)
    pivot = pivot[pivot.index >= continuous_start]
    logger.info(f"After continuous filter: {pivot.shape}")
    SEQ_LEN = 6
    X, y, raw_speeds = build_sequences_delta(pivot, SEQ_LEN)
    logger.info(f"Sequences: {X.shape}, targets: {y.shape}")
    train_idx, val_idx, test_idx = chronological_split_indices(len(X))
    logger.info(f"Train {len(train_idx)}, Val {len(val_idx)}, Test {len(test_idx)}")
    def make_loader(indices, shuffle=False):
        xs = torch.from_numpy(X[indices])
        ys = torch.from_numpy(y[indices])
        ds = TensorDataset(xs, ys)
        return DataLoader(ds, batch_size=32, shuffle=shuffle)
    train_loader = make_loader(train_idx, shuffle=True)
    val_loader = make_loader(val_idx, shuffle=False)
    test_loader = make_loader(test_idx, shuffle=False)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    logger.info(f"Using device: {device}")
    model = SimpleLSTM(input_size=5, hidden_size=64, output_size=5, dropout=0.1)
    import time
    start = time.time()
    model = train_model(model, train_loader, val_loader, epochs=50, lr=1e-3, patience=10, device=device)
    train_time = time.time() - start
    logger.info(f"Training time: {train_time:.1f}s")
    test_mae, test_rmse, preds, targets = evaluate(model, test_loader, device)
    pers_mae, pers_rmse = persistence_baseline_delta(test_loader, device)
    improvement = (pers_mae - test_mae) / pers_mae * 100
    logger.info(f"Test MAE: {test_mae:.4f}, RMSE: {test_rmse:.4f}")
    logger.info(f"Persistence MAE: {pers_mae:.4f}, RMSE: {pers_rmse:.4f}")
    logger.info(f"Improvement vs persistence: {improvement:.2f}%")
    # Sanity
    logger.info(f"Pred delta stats: min={preds.min():.2f}, max={preds.max():.2f}, mean={preds.mean():.2f}, median={np.median(preds):.2f}")
    logger.info(f"Target delta stats: min={targets.min():.2f}, max={targets.max():.2f}, mean={targets.mean():.2f}, median={np.median(targets):.2f}")
    logger.info(f"% pred delta below -120: {(preds < -120).mean()*100:.1f}%")
    logger.info(f"% pred delta above 120: {(preds > 120).mean()*100:.1f}%")
    # Inference time
    model.eval()
    start = time.time()
    with torch.no_grad():
        for _ in range(10):
            _ = model(torch.from_numpy(X[test_idx[:1]]).to(device))
    infer_time = (time.time() - start) / 10 * 1000
    logger.info(f"Inference time per batch (size 1): {infer_time:.2f} ms")
    print("\nSUMMARY")
    print(f"Model | Test MAE | Test RMSE | Persistence MAE | Improvement | September MAE | Training Time | Inference Time | Qualifies?")
    print(f"SimpleLSTM | {test_mae:.4f} | {test_rmse:.4f} | {pers_mae:.4f} | {improvement:.2f}% | N/A | {train_time:.1f}s | {infer_time:.2f}ms | {test_mae < pers_mae}")

if __name__ == '__main__':
    main()