import os
import json
import logging
import sqlite3
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
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

def load_link_metadata():
    """Load static link metadata: link_id, start/end coords, zone_id."""
    logger.info("Loading link metadata...")
    with get_db_connection() as conn:
        # Get distinct link metadata from the observations table (first occurrence)
        query = """
            SELECT link_id,
                   MAX(start_latitude) as start_lat,
                   MAX(start_longitude) as start_lon,
                   MAX(end_latitude) as end_lat,
                   MAX(end_longitude) as end_lon,
                   MAX(zone_id) as zone_id
            FROM traffic_observations
            GROUP BY link_id
        """
        df = pd.read_sql_query(query, conn)
        logger.info(f"Loaded metadata for {len(df)} links")
        return df

def build_graph(link_meta, link_id_to_idx, coord_tol=1e-4):
    """Build adjacency based on endpoint proximity."""
    logger.info("Building graph edges...")
    coords = []
    for idx, row in link_meta.iterrows():
        coords.append((row['link_id'], row['start_lat'], row['start_lon']))
        coords.append((row['link_id'], row['end_lat'], row['end_lon']))
    coord_df = pd.DataFrame(coords, columns=['link_id','lat','lon'])
    coord_df['lat_grid'] = (coord_df['lat'] / coord_tol).round().astype(int)
    coord_df['lon_grid'] = (coord_df['lon'] / coord_tol).round().astype(int)
    edges = set()
    for _, group in coord_df.groupby(['lat_grid','lon_grid']):
        links = group['link_id'].unique()
        for a in links:
            for b in links:
                if a != b:
                    edges.add((a,b))
    edge_list = list(edges)
    logger.info(f"Graph edges: {len(edge_list)}")
    # map to integer indices
    src = [link_id_to_idx[e[0]] for e in edge_list]
    dst = [link_id_to_idx[e[1]] for e in edge_list]
    return torch.tensor([src, dst], dtype=torch.long)

def load_snapshots(link_ids):
    """Load speed snapshots for given link_ids, ordered by time."""
    logger.info("Loading snapshots for selected links...")
    with get_db_connection() as conn:
        placeholders = ','.join(['?' for _ in link_ids])
        query = f"""
            SELECT observed_at, link_id, speed_midpoint
            FROM traffic_observations
            WHERE link_id IN ({placeholders})
              AND road_category IN (2,3,4,5,6)
              AND speed_midpoint >= 0
              AND speed_midpoint <= 120
            ORDER BY observed_at, link_id
        """
        df = pd.read_sql_query(query, conn, params=link_ids)
        logger.info(f"Loaded {len(df)} observations")
        df['observed_at'] = pd.to_datetime(df['observed_at']).dt.tz_convert(SG_OFFSET)
        # Filter to continuous period
        continuous_start = pd.Timestamp('2026-08-21 13:53:00', tz=SG_OFFSET)
        df = df[df['observed_at'] >= continuous_start].reset_index(drop=True)
        logger.info(f"Observations after continuous filter: {len(df)}")
        return df

def build_snapshot_tensors(df, link_id_to_idx):
    """Convert snapshot dataframe to list of feature tensors per time step."""
    snapshots = []
    times = sorted(df['observed_at'].unique())
    for t in times:
        sub = df[df['observed_at']==t].set_index('link_id')
        feat = torch.zeros(len(link_id_to_idx), 1, dtype=torch.float32)
        for lid, idx in link_id_to_idx.items():
            if lid in sub.index:
                feat[idx,0] = sub.loc[lid, 'speed_midpoint']
        snapshots.append(feat)
    return snapshots, times

class SimpleGCN(nn.Module):
    def __init__(self, in_feats, hidden, out_feats):
        super().__init__()
        self.conv1 = nn.Linear(in_feats, hidden)
        self.conv2 = nn.Linear(hidden, out_feats)
    def forward(self, x, edge_index):
        # x: (batch, N, in_feats) or (N, in_feats)
        if x.dim() == 3:
            # batch size expected 1
            x = x.squeeze(0)
            out = self._forward_single(x, edge_index)
            return out.unsqueeze(0)
        else:
            return self._forward_single(x, edge_index)

    def _forward_single(self, x, edge_index):
        # x: (N, in_feats)
        row, col = edge_index
        N = x.size(0)
        # add self-loops
        row = torch.cat([row, torch.arange(N, device=x.device)])
        col = torch.cat([col, torch.arange(N, device=x.device)])
        deg = torch.bincount(col, minlength=N).float()
        deg_inv_sqrt = deg.pow(-0.5)
        deg_inv_sqrt[deg_inv_sqrt == float('inf')] = 0
        norm = deg_inv_sqrt[row] * deg_inv_sqrt[col]
        # first layer
        out = torch.zeros_like(x)
        out.index_add_(0, row, x[col] * norm.unsqueeze(-1))
        out = F.relu(self.conv1(out))
        # second layer
        out2 = torch.zeros_like(out)
        out2.index_add_(0, row, out[col] * norm.unsqueeze(-1))
        out2 = self.conv2(out2)
        return out2

def main():
    logger.info("=== LIGHTWEIGHT GNN BENCHMARK ===")
    # 1. Load link metadata
    link_meta = load_link_metadata()
    # Sample subset of links for speed (e.g., 2000)
    max_links = 2000
    if len(link_meta) > max_links:
        link_meta = link_meta.sample(n=max_links, random_state=SEED).reset_index(drop=True)
        logger.info(f"Sampled {max_links} links")
    link_ids = link_meta['link_id'].tolist()
    link_id_to_idx = {lid:i for i,lid in enumerate(link_ids)}
    # 3. Load snapshots
    snap_df = load_snapshots(link_ids)
    # Determine timestamps and links present in all timestamps
    timestamps = sorted(snap_df['observed_at'].unique())
    logger.info(f"Unique timestamps: {len(timestamps)}")
    # For each link, count timestamps present
    link_counts = snap_df.groupby('link_id')['observed_at'].nunique()
    full_links = link_counts[link_counts == len(timestamps)].index.tolist()
    logger.info(f"Links present in all snapshots: {len(full_links)}")
    if len(full_links) < 100:
        logger.error("Too few fully observed links")
        return
    # Restrict to fully observed links
    link_ids = full_links[:500]  # limit to 500 for speed
    link_id_to_idx = {lid:i for i,lid in enumerate(link_ids)}
    # Filter snap_df
    snap_df = snap_df[snap_df['link_id'].isin(link_ids)].reset_index(drop=True)
    logger.info(f"Using {len(link_ids)} links, observations: {len(snap_df)}")
    # Build snapshots
    snapshots, times = build_snapshot_tensors(snap_df, link_id_to_idx)
    # 2. Build graph after final link selection
    link_meta_sub = link_meta[link_meta['link_id'].isin(link_ids)].reset_index(drop=True)
    edge_index = build_graph(link_meta_sub, link_id_to_idx)
    T = len(snapshots)
    logger.info(f"Total snapshots: {T}")
    if T < 10:
        logger.error("Not enough snapshots")
        return
    # Chronological split on snapshots (70/15/15)
    train_end = int(T*0.7)
    val_end = int(T*0.85)
    train_times = times[:train_end]
    val_times = times[train_end:val_end]
    test_times = times[val_end:]
    # Build dataset: each sample is (x_t, y_{t+1}) for t in train/val/test (except last)
    def make_samples(time_list):
        xs, ys = [], []
        for i, t in enumerate(time_list[:-1]):
            xs.append(snapshots[times.index(t)])
            ys.append(snapshots[times.index(time_list[i+1])])
        return torch.stack(xs), torch.stack(ys)
    train_x, train_y = make_samples(train_times)
    val_x, val_y = make_samples(val_times)
    test_x, test_y = make_samples(test_times)
    logger.info(f"Train samples: {len(train_x)}, Val: {len(val_x)}, Test: {len(test_x)}")
    # Normalize using training data
    train_mean = train_x.mean()
    train_std = train_x.std().clamp_min(1e-6)
    def norm(x): return (x - train_mean) / train_std
    def denorm(x): return x * train_std + train_mean
    train_x_n = norm(train_x)
    train_y_n = norm(train_y)
    val_x_n = norm(val_x)
    val_y_n = norm(val_y)
    test_x_n = norm(test_x)
    test_y_n = norm(test_y)
    # DataLoaders
    def make_loader(x,y,shuffle):
        ds = TensorDataset(x, y)
        return DataLoader(ds, batch_size=1, shuffle=shuffle)
    train_loader = make_loader(train_x_n, train_y_n, True)
    val_loader = make_loader(val_x_n, val_y_n, False)
    test_loader = make_loader(test_x_n, test_y_n, False)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    logger.info(f"Device: {device}")
    model = SimpleGCN(in_feats=1, hidden=32, out_feats=1).to(device)
    edge_index = edge_index.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    criterion = nn.L1Loss()
    best_val = float('inf')
    patience = 5
    patience_ctr = 0
    import time
    start = time.time()
    for epoch in range(30):
        model.train()
        train_losses = []
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad()
            pred = model(xb, edge_index)
            loss = criterion(pred, yb)
            loss.backward()
            optimizer.step()
            train_losses.append(loss.item())
        # val
        model.eval()
        val_losses = []
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                pred = model(xb, edge_index)
                loss = criterion(pred, yb)
                val_losses.append(loss.item())
        val_mae = np.mean(val_losses)
        logger.info(f"Epoch {epoch+1}: train MAE={np.mean(train_losses):.4f}, val MAE={val_mae:.4f}")
        if val_mae < best_val:
            best_val = val_mae
            best_state = {k:v.cpu().clone() for k,v in model.state_dict().items()}
            patience_ctr = 0
        else:
            patience_ctr += 1
            if patience_ctr >= patience:
                logger.info("Early stopping")
                break
    train_time = time.time() - start
    model.load_state_dict(best_state)
    # Test evaluation
    model.eval()
    test_preds = []
    test_targets = []
    with torch.no_grad():
        for xb, yb in test_loader:
            xb = xb.to(device)
            pred = model(xb, edge_index).cpu()
            test_preds.append(denorm(pred))
            test_targets.append(denorm(yb))
    # shapes: list of (batch=1, N, 1) -> cat -> (B, N, 1)
    test_preds_tensor = torch.cat(test_preds)
    test_targets_tensor = torch.cat(test_targets)
    B, N, _ = test_preds_tensor.shape
    test_preds_2d = test_preds_tensor.view(B, N).numpy()
    test_targets_2d = test_targets_tensor.view(B, N).numpy()
    test_preds_flat = test_preds_2d.reshape(-1)
    test_targets_flat = test_targets_2d.reshape(-1)
    test_mae = mean_absolute_error(test_targets_flat, test_preds_flat)
    test_rmse = np.sqrt(mean_squared_error(test_targets_flat, test_preds_flat))
    # Persistence baseline on test
    pers_preds_2d = denorm(test_x).view(B, N).numpy()
    pers_mae = mean_absolute_error(test_targets_flat, pers_preds_2d.reshape(-1))
    pers_rmse = np.sqrt(mean_squared_error(test_targets_flat, pers_preds_2d.reshape(-1)))
    improvement = (pers_mae - test_mae) / pers_mae * 100
    logger.info(f"Test MAE: {test_mae:.4f}, RMSE: {test_rmse:.4f}")
    logger.info(f"Persistence MAE: {pers_mae:.4f}, RMSE: {pers_rmse:.4f}")
    logger.info(f"Improvement vs persistence: {improvement:.2f}%")
    # Regional MAE
    link_meta = link_meta.set_index('link_id')
    zone_to_region = {}
    for region, zones in REGION_ZONE_MAP.items():
        for z in zones:
            zone_to_region[z] = region
    region_mae = {}
    region_pers_mae = {}
    for region in REGION_ORDER:
        idxs = [link_id_to_idx[lid] for lid in link_ids if zone_to_region.get(link_meta.loc[lid,'zone_id']) == region]
        if not idxs:
            continue
        region_mae[region] = mean_absolute_error(test_targets_2d[:, idxs].reshape(-1), test_preds_2d[:, idxs].reshape(-1))
        region_pers_mae[region] = mean_absolute_error(test_targets_2d[:, idxs].reshape(-1), pers_preds_2d[:, idxs].reshape(-1))
    logger.info("Regional MAE:")
    for r in REGION_ORDER:
        if r in region_mae:
            logger.info(f"  {r}: GNN MAE={region_mae[r]:.4f}, Persistence MAE={region_pers_mae[r]:.4f}")
    # Sanity
    logger.info(f"Pred speed stats: min={test_preds.min():.2f}, max={test_preds.max():.2f}, mean={test_preds.mean():.2f}, median={np.median(test_preds):.2f}")
    logger.info(f"% below 0: {(test_preds < 0).mean()*100:.1f}%")
    logger.info(f"% above 120: {(test_preds > 120).mean()*100:.1f}%")
    # Inference time
    model.eval()
    start = time.time()
    with torch.no_grad():
        for _ in range(10):
            _ = model(test_x_n[:1].to(device), edge_index)
    infer_time = (time.time() - start) / 10 * 1000
    logger.info(f"Inference time per batch (size 1): {infer_time:.2f} ms")
    print("\nSUMMARY")
    print(f"Model | Test MAE | Test RMSE | Persistence MAE | Improvement | September MAE | Training Time | Inference Time | Qualifies?")
    print(f"LinkGNN | {test_mae:.4f} | {test_rmse:.4f} | {pers_mae:.4f} | {improvement:.2f}% | N/A | {train_time:.1f}s | {infer_time:.2f}ms | {test_mae < pers_mae}")

if __name__ == '__main__':
    main()