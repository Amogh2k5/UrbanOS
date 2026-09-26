import os
import json
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Config
CSV_PATH = "traffic/data/processed/zone_speed_series_raw.csv"
SEQ_LEN = 6
PRED_HORIZON = 1
BATCH_SIZE = 16
D_MODEL = 32
K_HOP = 2
NUM_LAYERS = 2
DROPOUT = 0.1
LR = 1e-3
EPOCHS = 100
PATIENCE = 15
SEED = 42
torch.manual_seed(SEED)
np.random.seed(SEED)

EXP_DIR = "traffic/experiments/dcrnn"
os.makedirs(EXP_DIR, exist_ok=True)

# Zone centroids
ZONE_CENTROIDS = {
    'SG_NORTH': (1.42, 103.78),
    'SG_NORTH_EAST': (1.37, 103.90),
    'SG_CENTRAL_NORTH': (1.33, 103.83),
    'SG_CENTRAL_SOUTH': (1.29, 103.85),
    'SG_EAST': (1.33, 103.95),
    'SG_WEST_NORTH': (1.37, 103.70),
    'SG_WEST_SOUTH': (1.30, 103.70),
    'SG_SENTOSA': (1.25, 103.82),
}

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat/2)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon/2)**2
    return 2 * R * np.arcsin(np.sqrt(a))

def build_adjacency(zones):
    n = len(zones)
    coords = np.array([ZONE_CENTROIDS[z] for z in zones])
    dist = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            dist[i,j] = haversine(coords[i,0], coords[i,1], coords[j,0], coords[j,1])
    sigma = np.median(dist[dist>0])
    adj = np.exp(-dist**2 / (2*sigma**2))
    np.fill_diagonal(adj, 1.0)
    # Row and column normalize for diffusion
    row_sum = adj.sum(axis=1, keepdims=True)
    adj_fwd = adj / (row_sum + 1e-6)
    col_sum = adj.sum(axis=0, keepdims=True)
    adj_bwd = adj / (col_sum + 1e-6)
    return torch.FloatTensor(adj_fwd), torch.FloatTensor(adj_bwd)

class DiffusionConv(nn.Module):
    def __init__(self, in_dim, out_dim, K=2):
        super().__init__()
        self.K = K
        self.weights_fwd = nn.Parameter(torch.FloatTensor(K, in_dim, out_dim))
        self.weights_bwd = nn.Parameter(torch.FloatTensor(K, in_dim, out_dim))
        self.reset_parameters()
    
    def reset_parameters(self):
        nn.init.xavier_uniform_(self.weights_fwd)
        nn.init.xavier_uniform_(self.weights_bwd)
    
    def forward(self, x, adj_fwd, adj_bwd):
        # x: (B, T, N, C_in)
        B, T, N, C = x.shape
        out = torch.zeros(B, T, N, self.weights_fwd.shape[2], device=x.device)
        for k in range(self.K):
            if k == 0:
                x_k_fwd = x
                x_k_bwd = x
            elif k == 1:
                x_k_fwd = torch.einsum('ij,btjc->btic', adj_fwd, x)
                x_k_bwd = torch.einsum('ij,btjc->btic', adj_bwd, x)
            else:
                x_k_fwd = torch.einsum('ij,btjc->btic', adj_fwd, x_k_fwd)
                x_k_bwd = torch.einsum('ij,btjc->btic', adj_bwd, x_k_bwd)
            out += torch.einsum('btic,co->btio', x_k_fwd, self.weights_fwd[k])
            out += torch.einsum('btic,co->btio', x_k_bwd, self.weights_bwd[k])
        return out

class DCRNNCell(nn.Module):
    def __init__(self, input_dim, hidden_dim, num_zones, K=2):
        super().__init__()
        self.hidden_dim = hidden_dim
        self.num_zones = num_zones
        self.diff_conv = DiffusionConv(input_dim + hidden_dim, 2 * hidden_dim, K)
        self.gate_conv = DiffusionConv(input_dim + hidden_dim, hidden_dim, K)
    
    def forward(self, x, h, adj_fwd, adj_bwd):
        # x: (B, N, C_in), h: (B, N, H)
        combined = torch.cat([x, h], dim=-1)
        gates = self.diff_conv(combined.unsqueeze(1), adj_fwd, adj_bwd).squeeze(1)
        r, u = gates.chunk(2, dim=-1)
        r = torch.sigmoid(r)
        u = torch.sigmoid(u)
        
        c_combined = torch.cat([x, r * h], dim=-1)
        c = self.gate_conv(c_combined.unsqueeze(1), adj_fwd, adj_bwd).squeeze(1)
        c = torch.tanh(c)
        
        h_new = u * h + (1 - u) * c
        return h_new

class DCRNN(nn.Module):
    def __init__(self, num_zones, in_features, hidden_dim, K=2, num_layers=2, dropout=0.1):
        super().__init__()
        self.num_zones = num_zones
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        self.in_proj = nn.Linear(in_features, hidden_dim)
        self.cells = nn.ModuleList([
            DCRNNCell(hidden_dim, hidden_dim, num_zones, K) for _ in range(num_layers)
        ])
        self.dropout = nn.Dropout(dropout)
        self.out_proj = nn.Linear(hidden_dim, 1)
    
    def forward(self, x, adj_fwd, adj_bwd):
        # x: (B, T, N, F)
        B, T, N, F = x.shape
        x = self.in_proj(x)  # (B, T, N, H)
        
        h_states = [torch.zeros(B, N, self.hidden_dim, device=x.device) for _ in range(self.num_layers)]
        
        for t in range(T):
            x_t = x[:, t]  # (B, N, H)
            for layer_idx, cell in enumerate(self.cells):
                h_states[layer_idx] = cell(x_t, h_states[layer_idx], adj_fwd, adj_bwd)
                x_t = h_states[layer_idx]
                if layer_idx < self.num_layers - 1:
                    x_t = self.dropout(x_t)
        
        out = self.out_proj(h_states[-1]).squeeze(-1)  # (B, N)
        return out

def load_data():
    df = pd.read_csv(CSV_PATH, parse_dates=['timestamp'])
    df = df.sort_values(['timestamp','zone_id']).reset_index(drop=True)
    zones = sorted(df['zone_id'].unique())
    zone_to_idx = {z:i for i,z in enumerate(zones)}
    df['zone_idx'] = df['zone_id'].map(zone_to_idx)
    
    df['hour'] = df['timestamp'].dt.hour
    df['minute'] = df['timestamp'].dt.minute
    df['day_of_week'] = df['timestamp'].dt.dayofweek
    df['is_weekend'] = (df['day_of_week']>=5).astype(int)
    df['is_peak'] = ((df['hour']>=7)&(df['hour']<=9) | (df['hour']>=17)&(df['hour']<=19)).astype(int)
    
    feature_cols = ['avg_speed','min_speed','max_speed','link_count','hour','minute','day_of_week','is_weekend','is_peak']
    
    snapshots = df.groupby('timestamp').apply(
        lambda g: g.sort_values('zone_idx')[feature_cols].values
    ).reset_index()
    
    data_arrays = np.stack(snapshots[0].values)
    timestamps = snapshots['timestamp'].values
    T, Z, F = data_arrays.shape
    logger.info(f"Total snapshots {T}, zones {Z}, features {F}")
    return data_arrays, timestamps, zones, feature_cols

def make_sequences(data, seq_len):
    X, y = [], []
    for i in range(len(data) - seq_len):
        X.append(data[i:i+seq_len])
        y.append(data[i+seq_len, :, 0])
    return np.array(X), np.array(y)

def main():
    logger.info("="*60)
    logger.info("DCRNN TRAINING STARTED")
    logger.info("="*60)
    
    data, timestamps, zones, feature_cols = load_data()
    adj_fwd, adj_bwd = build_adjacency(zones)
    logger.info(f"Adjacency matrices shape: {adj_fwd.shape}")
    
    X, y = make_sequences(data, SEQ_LEN)
    N = len(X)
    logger.info(f"Sequences: {N}")
    
    train_end = int(N*0.7)
    val_end = int(N*0.85)
    train_idx = np.arange(0, train_end)
    val_idx = np.arange(train_end, val_end)
    test_idx = np.arange(val_end, N)
    logger.info(f"Train/Val/Test: {len(train_idx)}/{len(val_idx)}/{len(test_idx)}")
    
    Z, F = data.shape[1], data.shape[2]
    feature_scalers = {}
    for z in range(Z):
        for f in range(F):
            scaler = StandardScaler()
            scaler.fit(X[train_idx, :, z, f].reshape(-1,1))
            feature_scalers[(z,f)] = scaler
    
    target_scalers = {}
    for z in range(Z):
        scaler = StandardScaler()
        scaler.fit(y[train_idx, z].reshape(-1,1))
        target_scalers[z] = scaler
    
    def scale_X(arr, idx):
        out = np.zeros_like(arr[idx], dtype=np.float32)
        for i, idx_val in enumerate(idx):
            for z in range(Z):
                for f in range(F):
                    scaler = feature_scalers[(z,f)]
                    out[i, :, z, f] = scaler.transform(arr[idx_val, :, z, f].reshape(-1,1)).flatten()
        return out
    
    def scale_y(arr, idx):
        out = np.zeros((len(idx), Z), dtype=np.float32)
        for i, idx_val in enumerate(idx):
            for z in range(Z):
                out[i, z] = target_scalers[z].transform(arr[idx_val, z].reshape(-1,1)).flatten()
        return out
    
    X_train = scale_X(X, train_idx)
    X_val = scale_X(X, val_idx)
    X_test = scale_X(X, test_idx)
    y_train = scale_y(y, train_idx)
    y_val = scale_y(y, val_idx)
    y_test = scale_y(y, test_idx)
    
    train_loader = DataLoader(TensorDataset(torch.from_numpy(X_train), torch.from_numpy(y_train)), 
                              batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(TensorDataset(torch.from_numpy(X_val), torch.from_numpy(y_val)), 
                            batch_size=BATCH_SIZE, shuffle=False)
    test_loader = DataLoader(TensorDataset(torch.from_numpy(X_test), torch.from_numpy(y_test)), 
                             batch_size=BATCH_SIZE, shuffle=False)
    
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = DCRNN(num_zones=Z, in_features=F, hidden_dim=D_MODEL, K=K_HOP, 
                  num_layers=NUM_LAYERS, dropout=DROPOUT).to(device)
    adj_fwd, adj_bwd = adj_fwd.to(device), adj_bwd.to(device)
    
    param_count = sum(p.numel() for p in model.parameters())
    logger.info(f"Model parameters: {param_count:,}")
    
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR)
    criterion = nn.MSELoss()
    
    best_val = float('inf')
    patience_ctr = 0
    best_state = None
    start_time = time.time()
    
    for epoch in range(1, EPOCHS+1):
        model.train()
        train_losses = []
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad()
            pred = model(xb, adj_fwd, adj_bwd)
            loss = criterion(pred, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_losses.append(loss.item())
        
        model.eval()
        val_losses = []
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                pred = model(xb, adj_fwd, adj_bwd)
                loss = criterion(pred, yb)
                val_losses.append(loss.item())
        
        tr_loss = np.mean(train_losses)
        va_loss = np.mean(val_losses)
        logger.info(f"Epoch {epoch}: train {tr_loss:.4f} val {va_loss:.4f}")
        
        if va_loss < best_val:
            best_val = va_loss
            patience_ctr = 0
            best_state = {k:v.cpu().clone() for k,v in model.state_dict().items()}
        else:
            patience_ctr += 1
            if patience_ctr >= PATIENCE:
                logger.info("Early stopping")
                break
    
    train_time = time.time() - start_time
    logger.info(f"Training completed in {train_time:.1f}s")
    
    if best_state:
        model.load_state_dict(best_state)
    
    # Test
    model.eval()
    preds, trues = [], []
    with torch.no_grad():
        for xb, yb in test_loader:
            xb = xb.to(device)
            pred = model(xb, adj_fwd, adj_bwd).cpu().numpy()
            preds.append(pred)
            trues.append(yb.numpy())
    preds = np.vstack(preds)
    trues = np.vstack(trues)
    
    # Inverse scale
    preds_inv = np.zeros_like(preds)
    trues_inv = np.zeros_like(trues)
    for z in range(Z):
        preds_inv[:,z] = target_scalers[z].inverse_transform(preds[:,z].reshape(-1,1)).flatten()
        trues_inv[:,z] = target_scalers[z].inverse_transform(trues[:,z].reshape(-1,1)).flatten()
    
    # Metrics
    mae_per_zone = []
    rmse_per_zone = []
    for z in range(Z):
        mae = mean_absolute_error(trues_inv[:,z], preds_inv[:,z])
        rmse = np.sqrt(mean_squared_error(trues_inv[:,z], preds_inv[:,z]))
        mae_per_zone.append(mae)
        rmse_per_zone.append(rmse)
        logger.info(f"Zone {zones[z]}: MAE={mae:.4f} RMSE={rmse:.4f}")
    
    overall_mae = mean_absolute_error(trues_inv.flatten(), preds_inv.flatten())
    overall_rmse = np.sqrt(mean_squared_error(trues_inv.flatten(), preds_inv.flatten()))
    logger.info(f"Overall MAE={overall_mae:.4f} RMSE={overall_rmse:.4f}")
    
    # Persistence
    last_hist = X[test_idx, -1, :, 0]
    pers_mae = mean_absolute_error(trues_inv.flatten(), last_hist.flatten())
    pers_rmse = np.sqrt(mean_squared_error(trues_inv.flatten(), last_hist.flatten()))
    logger.info(f"Persistence MAE={pers_mae:.4f} RMSE={pers_rmse:.4f}")
    
    # Save
    torch.save({
        'model_state': model.state_dict(),
        'feature_scalers': feature_scalers,
        'target_scalers': target_scalers,
        'zones': zones,
        'adj_fwd': adj_fwd.cpu(),
        'adj_bwd': adj_bwd.cpu(),
        'seq_len': SEQ_LEN,
        'feature_cols': feature_cols,
        'config': {
            'd_model': D_MODEL, 'K': K_HOP, 'num_layers': NUM_LAYERS,
            'dropout': DROPOUT, 'lr': LR, 'seq_len': SEQ_LEN
        }
    }, f"{EXP_DIR}/dcrnn.pt")
    
    metrics = {
        'dcrnn': {'mae': float(overall_mae), 'rmse': float(overall_rmse)},
        'persistence': {'mae': float(pers_mae), 'rmse': float(pers_rmse)},
        'per_zone': {zones[i]: {'mae': float(mae_per_zone[i]), 'rmse': float(rmse_per_zone[i])} for i in range(Z)},
        'config': {
            'seq_len': SEQ_LEN, 'pred_horizon': PRED_HORIZON,
            'train_sequences': int(len(train_idx)), 'val_sequences': int(len(val_idx)), 'test_sequences': int(len(test_idx)),
            'parameter_count': param_count, 'train_time': train_time
        }
    }
    with open(f"{EXP_DIR}/metrics.json", 'w') as f:
        json.dump(metrics, f, indent=2)
    
    logger.info(f"DCRNN completed. Artifacts saved to {EXP_DIR}")
    return metrics

if __name__ == "__main__":
    main()