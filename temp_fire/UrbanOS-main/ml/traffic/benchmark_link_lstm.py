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

# Region mapping
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
            SELECT observed_at, link_id, road_name, road_category, speed_midpoint,
                   zone_id, zone_name
            FROM traffic_observations
            WHERE observed_at IN ({placeholders})
              AND road_category IN (2,3,4,5,6)
              AND speed_midpoint >= 0
              AND speed_midpoint <= 120
            ORDER BY observed_at, link_id
        """
        df = pd.read_sql_query(query, conn, params=timestamps)
        logger.info(f"Loaded {len(df):,} observations for {df['observed_at'].nunique()} snapshots")
        df['observed_at'] = pd.to_datetime(df['observed_at']).dt.tz_convert(SG_OFFSET)
        return df

def create_lag_features(df):
    """Create lag features with 5±1 min interval guard."""
    logger.info("Creating temporal lag features with interval guard...")
    df = df.copy()
    df['observed_at'] = pd.to_datetime(df['observed_at'])
    df = df.sort_values(['link_id', 'observed_at']).reset_index(drop=True)
    # compute time diff to previous snapshot per link
    df['prev_timestamp'] = df.groupby('link_id')['observed_at'].shift(1)
    df['time_diff_minutes'] = (df['observed_at'] - df['prev_timestamp']).dt.total_seconds() / 60
    tolerance = 1.0
    expected = 5
    valid_interval = (df['time_diff_minutes'] >= expected - tolerance) & \
                     (df['time_diff_minutes'] <= expected + tolerance)
    # speed_lag_1 only if valid interval
    df['speed_lag_1'] = np.where(valid_interval, df.groupby('link_id')['speed_midpoint'].shift(1), np.nan)
    # for simplicity, we only need current speed and next speed; but we need sequences of length SEQ_LEN
    # We'll later build sequences using only rows where we have a contiguous block of valid intervals.
    # We'll drop rows where lag is NaN (cannot form proper sequence)
    df = df.dropna(subset=['speed_lag_1']).reset_index(drop=True)
    df = df.drop(columns=['prev_timestamp','time_diff_minutes'])
    logger.info(f"Rows with valid lag-1: {len(df):,}")
    return df

def build_sequences_per_link(df, seq_len=6, max_links=5000):
    """Create sequences for each link separately, then concatenate."""
    logger.info(f"Building sequences with seq_len={seq_len}, max_links={max_links}...")
    # Sample a subset of links for faster benchmarking
    unique_links = df['link_id'].unique()
    if len(unique_links) > max_links:
        np.random.seed(SEED)
        selected_links = np.random.choice(unique_links, max_links, replace=False)
        df = df[df['link_id'].isin(selected_links)].copy()
        logger.info(f"Sampled {max_links} links out of {len(unique_links)}")
    all_X = []
    all_y = []
    all_meta = []  # (link_id, region, current_speed)
    for link_id, g in df.groupby('link_id'):
        g = g.sort_values('observed_at').reset_index(drop=True)
        speeds = g['speed_midpoint'].values.astype(np.float32)
        if len(speeds) < seq_len + 1:
            continue
        for i in range(len(speeds) - seq_len):
            X = speeds[i:i+seq_len]
            y = speeds[i+seq_len]  # next absolute speed
            all_X.append(X)
            all_y.append(y)
            row = g.iloc[i+seq_len-1]
            all_meta.append({
                'link_id': link_id,
                'region': row.get('zone_id'),  # zone_id maps to region via REGION_ZONE_MAP
                'current_speed': speeds[i+seq_len-1],
                'observed_at': row['observed_at']
            })
    if not all_X:
        raise ValueError("No sequences generated")
    X_arr = np.array(all_X, dtype=np.float32)  # (N, seq_len)
    y_arr = np.array(all_y, dtype=np.float32)  # (N,)
    meta_df = pd.DataFrame(all_meta)
    logger.info(f"Total sequences: {len(X_arr):,}")
    return X_arr, y_arr, meta_df

def chronological_split_indices(n_samples, train_ratio=0.7, val_ratio=0.15):
    train_end = int(n_samples * train_ratio)
    val_end = int(n_samples * (train_ratio + val_ratio))
    train_idx = np.arange(0, train_end)
    val_idx = np.arange(train_end, val_end)
    test_idx = np.arange(val_end, n_samples)
    return train_idx, val_idx, test_idx

class SimpleLSTM(nn.Module):
    def __init__(self, input_size=1, hidden_size=64, output_size=1, dropout=0.1):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, batch_first=True)
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size, output_size)

    def forward(self, x):
        # x: (batch, seq_len, 1)
        out, _ = self.lstm(x)
        out = out[:, -1, :]
        out = self.dropout(out)
        out = self.fc(out)
        return out.squeeze(-1)

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
    preds_all = np.concatenate(preds_all)
    targets_all = np.concatenate(targets_all)
    mae = mean_absolute_error(targets_all, preds_all)
    rmse = np.sqrt(mean_squared_error(targets_all, preds_all))
    return mae, rmse, preds_all, targets_all

def persistence_baseline_link(meta_df, test_idx):
    # persistence predicts current_speed (last in sequence)
    test_meta = meta_df.iloc[test_idx].reset_index(drop=True)
    # We need the current_speed corresponding to each test sequence; meta has current_speed.
    # target true next speed is y[test_idx]
    # we don't have y here; but we can compute mae using actual target speeds later.
    # We'll compute persistence mae in main using y.
    pass

def main():
    logger.info("=== LINK-LEVEL LSTM BENCHMARK ===")
    df = load_complete_snapshots()
    df = create_lag_features(df)
    # Continuous period filter
    continuous_start = pd.Timestamp('2026-08-21 13:53:00', tz=SG_OFFSET)
    df = df[df['observed_at'] >= continuous_start].reset_index(drop=True)
    logger.info(f"After continuous filter: {len(df):,} rows")
    SEQ_LEN = 6
    X, y, meta = build_sequences_per_link(df, seq_len=SEQ_LEN)
    logger.info(f"Sequences: {X.shape}, targets: {y.shape}, links: {meta['link_id'].nunique()}")
    # Split
    train_idx, val_idx, test_idx = chronological_split_indices(len(X))
    logger.info(f"Train {len(train_idx)}, Val {len(val_idx)}, Test {len(test_idx)}")
    # Normalize using training data only
    train_mean = X[train_idx].mean()
    train_std = X[train_idx].std()
    X_norm = (X - train_mean) / train_std
    y_mean = y[train_idx].mean()
    y_std = y[train_idx].std()
    y_norm = (y - y_mean) / y_std
    # DataLoaders
    def make_loader(indices, shuffle=False):
        xs = torch.from_numpy(X_norm[indices]).unsqueeze(-1)  # (N, seq_len, 1)
        ys = torch.from_numpy(y_norm[indices])
        ds = TensorDataset(xs, ys)
        return DataLoader(ds, batch_size=256, shuffle=shuffle)
    train_loader = make_loader(train_idx, shuffle=True)
    val_loader = make_loader(val_idx, shuffle=False)
    test_loader = make_loader(test_idx, shuffle=False)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    logger.info(f"Using device: {device}")
    model = SimpleLSTM(input_size=1, hidden_size=64, output_size=1, dropout=0.1)
    import time
    start = time.time()
    model = train_model(model, train_loader, val_loader, epochs=15, lr=1e-3, patience=5, device=device)
    train_time = time.time() - start
    logger.info(f"Training time: {train_time:.1f}s")
    # Evaluate on test (denormalize predictions)
    model.eval()
    preds_norm = []
    targets_norm = []
    with torch.no_grad():
        for xb, yb in test_loader:
            xb = xb.to(device)
            preds = model(xb).cpu().numpy()
            preds_norm.append(preds)
            targets_norm.append(yb.numpy())
    preds_norm = np.concatenate(preds_norm)
    targets_norm = np.concatenate(targets_norm)
    # denormalize
    preds = preds_norm * y_std + y_mean
    targets = targets_norm * y_std + y_mean
    test_mae = mean_absolute_error(targets, preds)
    test_rmse = np.sqrt(mean_squared_error(targets, preds))
    # Persistence baseline: predict current_speed (meta current_speed) for test indices
    test_meta = meta.iloc[test_idx].reset_index(drop=True)
    pers_preds = test_meta['current_speed'].values
    pers_mae = mean_absolute_error(targets, pers_preds)
    pers_rmse = np.sqrt(mean_squared_error(targets, pers_preds))
    improvement = (pers_mae - test_mae) / pers_mae * 100
    logger.info(f"Test MAE: {test_mae:.4f}, RMSE: {test_rmse:.4f}")
    logger.info(f"Persistence MAE: {pers_mae:.4f}, RMSE: {pers_rmse:.4f}")
    logger.info(f"Improvement vs persistence: {improvement:.2f}%")
    # Regional aggregation
    # Map zone_id to region
    zone_to_region = {}
    for region, zones in REGION_ZONE_MAP.items():
        for z in zones:
            zone_to_region[z] = region
    test_meta = test_meta.copy()
    test_meta['region'] = test_meta['region'].map(zone_to_region)
    # For each region, collect predictions and targets
    region_mae = {}
    region_pers_mae = {}
    for region in REGION_ORDER:
        mask = test_meta['region'] == region
        if mask.sum() == 0:
            continue
        idxs = np.where(mask)[0]
        region_mae[region] = mean_absolute_error(targets[idxs], preds[idxs])
        region_pers_mae[region] = mean_absolute_error(targets[idxs], pers_preds[idxs])
    logger.info("Regional MAE:")
    for r in REGION_ORDER:
        if r in region_mae:
            logger.info(f"  {r}: LSTM MAE={region_mae[r]:.4f}, Persistence MAE={region_pers_mae[r]:.4f}")
    # Sanity
    logger.info(f"Pred speed stats: min={preds.min():.2f}, max={preds.max():.2f}, mean={preds.mean():.2f}, median={np.median(preds):.2f}")
    logger.info(f"% below 0: {(preds < 0).mean()*100:.1f}%")
    logger.info(f"% above 120: {(preds > 120).mean()*100:.1f}%")
    # Inference time
    model.eval()
    start = time.time()
    with torch.no_grad():
        for _ in range(10):
            _ = model(torch.from_numpy(X_norm[test_idx[:1]]).unsqueeze(-1).to(device))
    infer_time = (time.time() - start) / 10 * 1000
    logger.info(f"Inference time per batch (size 1): {infer_time:.2f} ms")
    print("\nSUMMARY")
    print(f"Model | Test MAE | Test RMSE | Persistence MAE | Improvement | September MAE | Training Time | Inference Time | Qualifies?")
    print(f"LinkLSTM | {test_mae:.4f} | {test_rmse:.4f} | {pers_mae:.4f} | {improvement:.2f}% | N/A | {train_time:.1f}s | {infer_time:.2f}ms | {test_mae < pers_mae}")

if __name__ == '__main__':
    main()