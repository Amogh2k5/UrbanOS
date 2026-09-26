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

CSV_PATH = "traffic/data/processed/zone_speed_series_raw.csv"
SEQ_LEN = 6
PRED_HORIZON = 1
BATCH_SIZE = 16
D_MODEL = 32
NUM_LAYERS = 4
DROPOUT = 0.1
LR = 1e-3
EPOCHS = 100
PATIENCE = 15
SEED = 42
torch.manual_seed(SEED)
np.random.seed(SEED)

EXP_DIR = "traffic/experiments/tcn"
os.makedirs(EXP_DIR, exist_ok=True)

class Chomp1d(nn.Module):
    def __init__(self, chomp_size):
        super().__init__()
        self.chomp_size = chomp_size
    
    def forward(self, x):
        return x[:, :, :, :-self.chomp_size].contiguous()

class TemporalBlock(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size, dilation, dropout=0.1):
        super().__init__()
        padding = (kernel_size - 1) * dilation
        self.conv1 = nn.Conv2d(in_channels, out_channels, (1, kernel_size), 
                               padding=(0, padding), dilation=(1, dilation))
        self.chomp1 = Chomp1d(padding)
        self.relu1 = nn.ReLU()
        self.dropout1 = nn.Dropout(dropout)
        
        self.conv2 = nn.Conv2d(out_channels, out_channels, (1, kernel_size),
                               padding=(0, padding), dilation=(1, dilation))
        self.chomp2 = Chomp1d(padding)
        self.relu2 = nn.ReLU()
        self.dropout2 = nn.Dropout(dropout)
        
        self.net = nn.Sequential(
            self.conv1, self.chomp1, self.relu1, self.dropout1,
            self.conv2, self.chomp2, self.relu2, self.dropout2
        )
        self.downsample = nn.Conv2d(in_channels, out_channels, (1, 1)) if in_channels != out_channels else None
        self.relu = nn.ReLU()
        self.init_weights()
    
    def init_weights(self):
        self.conv1.weight.data.normal_(0, 0.01)
        self.conv2.weight.data.normal_(0, 0.01)
        if self.downsample:
            self.downsample.weight.data.normal_(0, 0.01)
    
    def forward(self, x):
        out = self.net(x)
        res = x if self.downsample is None else self.downsample(x)
        return self.relu(out + res)

class TCN(nn.Module):
    def __init__(self, num_zones, in_features, d_model, num_layers=4, kernel_size=3, dropout=0.1):
        super().__init__()
        self.num_zones = num_zones
        self.in_proj = nn.Conv2d(in_channels=in_features, out_channels=D_MODEL, kernel_size=(1,1))
        
        layers = []
        for i in range(num_layers):
            dilation = 2 ** i
            layers.append(TemporalBlock(D_MODEL, D_MODEL, kernel_size=3, dilation=dilation, dropout=DROPOUT))
        
        self.tcn = nn.Sequential(*layers)
        self.output_conv = nn.Conv2d(D_MODEL, 1, (1, 1))
    
    def forward(self, x):
        # x: (B, T, N, F)
        B, T, N, F = x.shape
        x = x.permute(0, 3, 2, 1).contiguous()  # (B, F, N, T)
        x = self.in_proj(x)  # (B, D_MODEL, N, T)
        x = self.tcn(x)  # (B, D_MODEL, N, T)
        # Take last time step
        x = x[:, :, :, -1:]  # (B, D_MODEL, N, 1)
        x = self.output_conv(x)  # (B, 1, N, 1)
        return x.squeeze(1).squeeze(-1)  # (B, N)

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
    logger.info("TCN TRAINING STARTED")
    logger.info("="*60)
    
    data, timestamps, zones, feature_cols = load_data()
    
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
    model = TCN(num_zones=len(zones), in_features=F, d_model=D_MODEL, 
                num_layers=NUM_LAYERS, dropout=DROPOUT).to(device)
    
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
            pred = model(xb)
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
                pred = model(xb)
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
    
    model.eval()
    preds, trues = [], []
    with torch.no_grad():
        for xb, yb in test_loader:
            xb = xb.to(device)
            pred = model(xb).cpu().numpy()
            preds.append(pred)
            trues.append(yb.numpy())
    preds = np.vstack(preds)
    trues = np.vstack(trues)
    
    preds_inv = np.zeros_like(preds)
    trues_inv = np.zeros_like(trues)
    for z in range(len(zones)):
        preds_inv[:,z] = target_scalers[z].inverse_transform(preds[:,z].reshape(-1,1)).flatten()
        trues_inv[:,z] = target_scalers[z].inverse_transform(trues[:,z].reshape(-1,1)).flatten()
    
    mae_per_zone = []
    rmse_per_zone = []
    for z in range(len(zones)):
        mae = mean_absolute_error(trues_inv[:,z], preds_inv[:,z])
        rmse = np.sqrt(mean_squared_error(trues_inv[:,z], preds_inv[:,z]))
        mae_per_zone.append(mae)
        rmse_per_zone.append(rmse)
        logger.info(f"Zone {zones[z]}: MAE={mae:.4f} RMSE={rmse:.4f}")
    
    overall_mae = mean_absolute_error(trues_inv.flatten(), preds_inv.flatten())
    overall_rmse = np.sqrt(mean_squared_error(trues_inv.flatten(), preds_inv.flatten()))
    logger.info(f"Overall MAE={overall_mae:.4f} RMSE={overall_rmse:.4f}")
    
    last_hist = X[test_idx, -1, :, 0]
    pers_mae = mean_absolute_error(trues_inv.flatten(), last_hist.flatten())
    pers_rmse = np.sqrt(mean_squared_error(trues_inv.flatten(), last_hist.flatten()))
    logger.info(f"Persistence MAE={pers_mae:.4f} RMSE={pers_rmse:.4f}")
    
    torch.save({
        'model_state': model.state_dict(),
        'feature_scalers': feature_scalers,
        'target_scalers': target_scalers,
        'zones': zones,
        'seq_len': SEQ_LEN,
        'feature_cols': feature_cols,
        'config': {
            'd_model': D_MODEL, 'num_layers': NUM_LAYERS,
            'dropout': DROPOUT, 'lr': LR, 'seq_len': SEQ_LEN
        }
    }, f"{EXP_DIR}/tcn.pt")
    
    metrics = {
        'tcn': {'mae': float(overall_mae), 'rmse': float(overall_rmse)},
        'persistence': {'mae': float(pers_mae), 'rmse': float(pers_rmse)},
        'per_zone': {zones[i]: {'mae': float(mae_per_zone[i]), 'rmse': float(rmse_per_zone[i])} for i in range(len(zones))},
        'config': {
            'seq_len': SEQ_LEN, 'pred_horizon': PRED_HORIZON,
            'train_sequences': int(len(train_idx)), 'val_sequences': int(len(val_idx)), 'test_sequences': int(len(test_idx)),
            'parameter_count': param_count, 'train_time': train_time
        }
    }
    with open(f"{EXP_DIR}/metrics.json", 'w') as f:
        json.dump(metrics, f, indent=2)
    
    logger.info(f"TCN completed. Artifacts saved to {EXP_DIR}")
    return metrics

if __name__ == "__main__":
    main()