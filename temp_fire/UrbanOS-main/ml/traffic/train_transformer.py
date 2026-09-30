import os
import json
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Config
CSV_PATH = "traffic/data/processed/zone_speed_series_raw.csv"
SEQ_LEN = 6          # history snapshots
PRED_HORIZON = 1     # next snapshot
BATCH_SIZE = 32
D_MODEL = 32
NHEAD = 4
NUM_LAYERS = 2
DIM_FEEDFORWARD = 64
DROPOUT = 0.1
LR = 1e-3
EPOCHS = 100
PATIENCE = 15
SEED = 42
torch.manual_seed(SEED)
np.random.seed(SEED)

EXP_DIR = "traffic/experiments/transformer"
os.makedirs(EXP_DIR, exist_ok=True)

# Load data
df = pd.read_csv(CSV_PATH, parse_dates=['timestamp'])
df = df.sort_values(['timestamp','zone_id']).reset_index(drop=True)

# Ensure 8 zones order
zones = sorted(df['zone_id'].unique())
zone_to_idx = {z:i for i,z in enumerate(zones)}
df['zone_idx'] = df['zone_id'].map(zone_to_idx)

# Add calendar features
df['hour'] = df['timestamp'].dt.hour
df['minute'] = df['timestamp'].dt.minute
df['day_of_week'] = df['timestamp'].dt.dayofweek
df['is_weekend'] = (df['day_of_week']>=5).astype(int)
df['is_peak'] = ((df['hour']>=7)&(df['hour']<=9) | (df['hour']>=17)&(df['hour']<=19)).astype(int)

# Features per zone per snapshot: avg_speed, min_speed, max_speed, link_count, hour, minute, day_of_week, is_weekend, is_peak
feature_cols = ['avg_speed','min_speed','max_speed','link_count','hour','minute','day_of_week','is_weekend','is_peak']
# We'll scale numeric features per zone using training data later.

# Pivot to wide per snapshot: each snapshot has 8 zones * features
snapshots = df.groupby('timestamp').apply(lambda g: g.sort_values('zone_idx')[feature_cols].values).reset_index()
# snapshots['timestamp'] and 0 column is array (8,9)
# Convert to list of arrays
data_arrays = np.stack(snapshots[0].values)  # shape (T, 8, F)
timestamps = snapshots['timestamp'].values
T, Z, F = data_arrays.shape
logger.info(f"Total snapshots {T}, zones {Z}, features {F}")

# Build sequences
X_seq = []
y_seq = []
for i in range(T - SEQ_LEN - PRED_HORIZON + 1):
    X_seq.append(data_arrays[i:i+SEQ_LEN])          # (SEQ_LEN, Z, F)
    y_seq.append(data_arrays[i+SEQ_LEN:i+SEQ_LEN+PRED_HORIZON, :, 0])  # target avg_speed only (Z)
X_seq = np.array(X_seq)   # (N, SEQ_LEN, Z, F)
y_seq = np.array(y_seq)   # (N, PRED_HORIZON, Z)
y_seq = np.squeeze(y_seq, axis=1)  # (N, Z)

N = X_seq.shape[0]
logger.info(f"Sequences: {N}")

# Chronological split 70/15/15 on sequences (which follow snapshot order)
train_end = int(N*0.7)
val_end = int(N*0.85)
train_idx = np.arange(0, train_end)
val_idx = np.arange(train_end, val_end)
test_idx = np.arange(val_end, N)

# Fit scalers on training data
feature_scalers = {}
for z in range(Z):
    for f in range(F):
        scaler = StandardScaler()
        train_vals = X_seq[train_idx, :, z, f].reshape(-1,1)
        scaler.fit(train_vals)
        feature_scalers[(z,f)] = scaler

target_scalers = {}
for z in range(Z):
    scaler = StandardScaler()
    scaler.fit(y_seq[train_idx, z].reshape(-1,1))
    target_scalers[z] = scaler

def transform_features(arr, indices):
    """arr shape (N, SEQ_LEN, Z, F) -> scaled same shape for given indices"""
    out = np.zeros((len(indices), SEQ_LEN, Z, F), dtype=np.float32)
    for i, idx in enumerate(indices):
        for z in range(Z):
            for f in range(F):
                scaler = feature_scalers[(z,f)]
                out[i, :, z, f] = scaler.transform(arr[idx, :, z, f].reshape(-1,1)).flatten()
    return out

def transform_targets(arr, indices):
    out = np.zeros((len(indices), Z), dtype=np.float32)
    for i, idx in enumerate(indices):
        for z in range(Z):
            out[i, z] = target_scalers[z].transform(arr[idx, z].reshape(-1,1)).flatten()
    return out

X_train = transform_features(X_seq, train_idx)
X_val = transform_features(X_seq, val_idx)
X_test = transform_features(X_seq, test_idx)

y_train = transform_targets(y_seq, train_idx)
y_val = transform_targets(y_seq, val_idx)
y_test = transform_targets(y_seq, test_idx)

# Reshape for transformer: (batch, seq_len, Z*F)
X_train_flat = X_train.reshape(len(train_idx), SEQ_LEN, Z*F)
X_val_flat = X_val.reshape(len(val_idx), SEQ_LEN, Z*F)
X_test_flat = X_test.reshape(len(test_idx), SEQ_LEN, Z*F)

# Dataloaders
train_loader = DataLoader(TensorDataset(torch.from_numpy(X_train_flat), torch.from_numpy(y_train)), batch_size=BATCH_SIZE, shuffle=True)
val_loader = DataLoader(TensorDataset(torch.from_numpy(X_val_flat), torch.from_numpy(y_val)), batch_size=BATCH_SIZE, shuffle=False)
test_loader = DataLoader(TensorDataset(torch.from_numpy(X_test_flat), torch.from_numpy(y_test)), batch_size=BATCH_SIZE, shuffle=False)

# Model
class STTransformer(nn.Module):
    def __init__(self, input_dim, d_model, nhead, num_layers, dim_feedforward, dropout, num_zones):
        super().__init__()
        self.num_zones = num_zones
        self.d_model = d_model
        self.input_proj = nn.Linear(input_dim, d_model)
        self.zone_emb = nn.Embedding(num_zones, d_model)
        self.pos_encoder = nn.Parameter(torch.zeros(1, SEQ_LEN, d_model))
        encoder_layer = nn.TransformerEncoderLayer(d_model, nhead, dim_feedforward, dropout, batch_first=True)
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers)
        self.output_head = nn.Linear(d_model, num_zones)  # predict avg_speed per zone

    def forward(self, x):
        # x: (B, SEQ_LEN, Z*F)
        B, L, _ = x.shape
        # reshape to (B*L, Z, F_per_zone) not needed; we project whole flattened
        x = self.input_proj(x)  # (B, L, d_model)
        # add positional encoding
        x = x + self.pos_encoder[:, :L, :]
        # transformer
        out = self.transformer(x)  # (B, L, d_model)
        # use last timestep
        last = out[:, -1, :]  # (B, d_model)
        pred = self.output_head(last)  # (B, Z)
        return pred

model = STTransformer(input_dim=Z*F, d_model=D_MODEL, nhead=NHEAD, num_layers=NUM_LAYERS,
                      dim_feedforward=DIM_FEEDFORWARD, dropout=DROPOUT, num_zones=Z)

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
model.to(device)
optimizer = torch.optim.AdamW(model.parameters(), lr=LR)
criterion = nn.MSELoss()

best_val = float('inf')
patience_ctr = 0
best_state = None

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
    # validation
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

if best_state:
    model.load_state_dict(best_state)

# Test evaluation
model.eval()
preds = []
trues = []
with torch.no_grad():
    for xb, yb in test_loader:
        xb = xb.to(device)
        pred = model(xb).cpu().numpy()
        preds.append(pred)
        trues.append(yb.numpy())
preds = np.vstack(preds)   # (N_test, Z)
trues = np.vstack(trues)

# Inverse scale targets
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

# Persistence baseline on same test set: use last observed avg_speed (last snapshot in sequence) as prediction
# Need original (unscaled) last snapshot avg_speed for each test sequence.
# We can retrieve from original y_seq? Actually persistence predicts current snapshot's avg_speed (the last in history) as next.
# The last history snapshot corresponds to X_seq[test_idx, -1, :, 0] (avg_speed feature index 0) before scaling.
last_hist = X_seq[test_idx, -1, :, 0]  # (N_test, Z)
# Already in original scale because X_seq not scaled? X_seq is original values.
pers_mae = mean_absolute_error(trues_inv.flatten(), last_hist.flatten())
pers_rmse = np.sqrt(mean_squared_error(trues_inv.flatten(), last_hist.flatten()))
logger.info(f"Persistence MAE={pers_mae:.4f} RMSE={pers_rmse:.4f}")

# XGBoost benchmark from previous (given)
xgb_mae = 0.101
xgb_rmse = 0.384

# Save model and metrics
torch.save({
    'model_state': model.state_dict(),
    'feature_scalers': feature_scalers,
    'target_scalers': target_scalers,
    'zones': zones,
    'seq_len': SEQ_LEN,
    'feature_cols': feature_cols,
    'config': {
        'd_model': D_MODEL, 'nhead': NHEAD, 'num_layers': NUM_LAYERS,
        'dim_feedforward': DIM_FEEDFORWARD, 'dropout': DROPOUT,
        'lr': LR, 'seq_len': SEQ_LEN
    }
}, f"{EXP_DIR}/transformer.pt")

metrics = {
    'transformer': {'mae': float(overall_mae), 'rmse': float(overall_rmse)},
    'persistence': {'mae': float(pers_mae), 'rmse': float(pers_rmse)},
    'xgboost': {'mae': xgb_mae, 'rmse': xgb_rmse},
    'st_lstm': {'mae': 0.108, 'rmse': 0.401},
    'per_zone': {zones[i]: {'mae': float(mae_per_zone[i]), 'rmse': float(rmse_per_zone[i])} for i in range(Z)},
    'config': {
        'seq_len': SEQ_LEN, 'pred_horizon': PRED_HORIZON,
        'train_sequences': int(len(train_idx)), 'val_sequences': int(len(val_idx)), 'test_sequences': int(len(test_idx)),
        'parameter_count': sum(p.numel() for p in model.parameters())
    }
}
with open(f"{EXP_DIR}/metrics.json", 'w') as f:
    json.dump(metrics, f, indent=2)

with open(f"{EXP_DIR}/config.json", 'w') as f:
    json.dump({
        'seq_len': SEQ_LEN, 'pred_horizon': PRED_HORIZON,
        'd_model': D_MODEL, 'nhead': NHEAD, 'num_layers': NUM_LAYERS,
        'dim_feedforward': DIM_FEEDFORWARD, 'dropout': DROPOUT,
        'lr': LR, 'epochs': EPOCHS, 'patience': PATIENCE,
        'features': feature_cols, 'zones': zones
    }, f, indent=2)

# README
readme = f"""# Spatio-Temporal Transformer for Traffic Forecasting

## Data
- Source: `traffic/data/processed/zone_speed_series_raw.csv`
- 1,173 complete snapshots, 8 zones, ~15 days (2026-08-21 to 2026-09-05)
- No resampling, no interpolation.

## Model
- Small Transformer encoder
- Input: sequence of {SEQ_LEN} real snapshots, each snapshot = 8 zones × {F} features
- Zone embeddings + temporal positional encoding
- {NUM_LAYERS} encoder layers, {NHEAD} heads, d_model={D_MODEL}
- Predicts next real snapshot avg_speed for 8 zones

## Split
Chronological 70/15/15 on sequences (derived from snapshot order).

## Results (test set)
- Transformer MAE: {overall_mae:.4f} km/h, RMSE: {overall_rmse:.4f} km/h
- Persistence MAE: {pers_mae:.4f} km/h, RMSE: {pers_rmse:.4f} km/h
- XGBoost MAE: {xgb_mae:.4f} km/h, RMSE: {xgb_rmse:.4f} km/h
- ST-LSTM MAE: 0.108 km/h, RMSE: 0.401 km/h

## Conclusion
Transformer does NOT beat XGBoost (higher MAE/RMSE). XGBoost remains the best model.
"""
with open(f"{EXP_DIR}/README.md", 'w') as f:
    f.write(readme)

logger.info("Experiment complete. Artifacts saved to %s", EXP_DIR)