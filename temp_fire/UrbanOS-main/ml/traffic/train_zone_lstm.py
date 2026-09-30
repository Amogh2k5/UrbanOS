import json
import logging
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CSV_PATH = "traffic/data/processed/zone_speed_series_train.csv"
MODEL_DIR = "traffic/experiments/zone_lstm"
SEQ_LEN = 12   # 1 hour (12 * 5min)
HORIZON = 1    # next 5 min
BATCH_SIZE = 16
HIDDEN = 32
LAYERS = 1
DROPOUT = 0.1
LR = 1e-3
EPOCHS = 50
PATIENCE = 10

import os, pathlib
pathlib.Path(MODEL_DIR).mkdir(parents=True, exist_ok=True)

def load_series():
    df = pd.read_csv(CSV_PATH, parse_dates=['timestamp'])
    df = df.sort_values(['zone_id','timestamp'])
    zones = sorted(df['zone_id'].unique())
    # pivot
    wide = df.pivot(index='timestamp', columns='zone_id', values='zone_avg_speed')
    wide = wide[zones]
    return wide.values.astype(np.float32), zones  # (T, Z)

def make_sequences(data, seq_len, horizon):
    X, y = [], []
    T, Z = data.shape
    for i in range(T - seq_len - horizon + 1):
        X.append(data[i:i+seq_len])
        y.append(data[i+seq_len:i+seq_len+horizon])
    return np.array(X), np.array(y)  # (N, seq_len, Z), (N, horizon, Z)

class MultiZoneLSTM(nn.Module):
    def __init__(self, n_zones, hidden, layers, dropout, horizon):
        super().__init__()
        self.n_zones = n_zones
        self.horizon = horizon
        self.lstm = nn.LSTM(input_size=n_zones, hidden_size=hidden,
                            num_layers=layers, dropout=dropout if layers>1 else 0,
                            batch_first=True)
        self.fc = nn.Linear(hidden, n_zones*horizon)
    def forward(self, x):
        # x: (B, seq_len, Z)
        out, _ = self.lstm(x)
        last = out[:,-1,:]
        out = self.fc(last)
        return out.view(-1, self.horizon, self.n_zones)

def train():
    data, zones = load_series()
    logger.info(f"Data shape {data.shape}, zones {zones}")

    # Scale per zone using training portion
    # Chronological split 70/15/15
    T = data.shape[0]
    train_end = int(T*0.7)
    val_end = int(T*0.85)
    train_data = data[:train_end]
    val_data = data[train_end:val_end]
    test_data = data[val_end:]

    # Scalers per zone
    scalers = [StandardScaler() for _ in range(data.shape[1])]
    for z in range(data.shape[1]):
        scalers[z].fit(train_data[:,z].reshape(-1,1))
    def scale(arr):
        out = np.empty_like(arr)
        for z in range(arr.shape[1]):
            out[:,z] = scalers[z].transform(arr[:,z].reshape(-1,1)).flatten()
        return out
    def inv_scale(arr):
        out = np.empty_like(arr)
        for z in range(arr.shape[1]):
            out[:,z] = scalers[z].inverse_transform(arr[:,z].reshape(-1,1)).flatten()
        return out

    train_s = scale(train_data)
    val_s = scale(val_data)
    test_s = scale(test_data)

    X_tr, y_tr = make_sequences(train_s, SEQ_LEN, HORIZON)
    X_va, y_va = make_sequences(val_s, SEQ_LEN, HORIZON)
    X_te, y_te = make_sequences(test_s, SEQ_LEN, HORIZON)

    logger.info(f"Seq counts train {len(X_tr)} val {len(X_va)} test {len(X_te)}")

    train_loader = DataLoader(TensorDataset(torch.from_numpy(X_tr), torch.from_numpy(y_tr)),
                              batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(TensorDataset(torch.from_numpy(X_va), torch.from_numpy(y_va)),
                            batch_size=BATCH_SIZE, shuffle=False)
    test_loader = DataLoader(TensorDataset(torch.from_numpy(X_te), torch.from_numpy(y_te)),
                             batch_size=BATCH_SIZE, shuffle=False)

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = MultiZoneLSTM(n_zones=len(zones), hidden=HIDDEN, layers=LAYERS,
                          dropout=DROPOUT, horizon=HORIZON).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    crit = nn.MSELoss()

    best_val = float('inf')
    patience_ctr = 0
    best_state = None

    for epoch in range(1, EPOCHS+1):
        model.train()
        tr_losses = []
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad()
            pred = model(xb)
            loss = crit(pred, yb)
            loss.backward()
            opt.step()
            tr_losses.append(loss.item())
        # val
        model.eval()
        va_losses = []
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                pred = model(xb)
                loss = crit(pred, yb)
                va_losses.append(loss.item())
        tr_loss = np.mean(tr_losses)
        va_loss = np.mean(va_losses)
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
    preds, trues = [], []
    with torch.no_grad():
        for xb, yb in test_loader:
            xb = xb.to(device)
            pred = model(xb).cpu().numpy()
            preds.append(pred)
            trues.append(yb.numpy())
    preds = np.vstack(preds)   # (N, horizon, Z)
    trues = np.vstack(trues)

    # Inverse scale
    # reshape to (N*horizon, Z)
    N, H, Z = preds.shape
    preds_flat = preds.reshape(-1, Z)
    trues_flat = trues.reshape(-1, Z)
    preds_inv = inv_scale(preds_flat).reshape(N, H, Z)
    trues_inv = inv_scale(trues_flat).reshape(N, H, Z)

    # Metrics per zone and overall
    mae_per_zone = []
    rmse_per_zone = []
    for zi, zone in enumerate(zones):
        mae = mean_absolute_error(trues_inv[:,0,zi], preds_inv[:,0,zi])
        rmse = np.sqrt(mean_squared_error(trues_inv[:,0,zi], preds_inv[:,0,zi]))
        mae_per_zone.append(mae)
        rmse_per_zone.append(rmse)
        logger.info(f"Zone {zone}: MAE={mae:.4f} RMSE={rmse:.4f}")

    overall_mae = mean_absolute_error(trues_inv[:,0,:].flatten(), preds_inv[:,0,:].flatten())
    overall_rmse = np.sqrt(mean_squared_error(trues_inv[:,0,:].flatten(), preds_inv[:,0,:].flatten()))
    logger.info(f"Overall MAE={overall_mae:.4f} RMSE={overall_rmse:.4f}")

    # Persistence baseline on same test set
    # Persistence: predict last known speed (t) as t+1
    # Build persistence using original (unscaled) test_data sequences
    # Need to align: for each test sequence, the input last step is at index corresponding to test_data index
    # Simpler: compute persistence on test_s sequences using last step of X_te (scaled) then inverse.
    pers_scaled = X_te[:,-1,:]  # (N, Z)
    pers_flat = pers_scaled.reshape(-1, Z)
    pers_inv = inv_scale(pers_flat).reshape(N, 1, Z)
    pers_mae = mean_absolute_error(trues_inv[:,0,:].flatten(), pers_inv[:,0,:].flatten())
    pers_rmse = np.sqrt(mean_squared_error(trues_inv[:,0,:].flatten(), pers_inv[:,0,:].flatten()))
    logger.info(f"Persistence MAE={pers_mae:.4f} RMSE={pers_rmse:.4f}")

    # Save model and scalers
    torch.save({
        'model_state': model.state_dict(),
        'scalers': scalers,
        'zones': zones,
        'seq_len': SEQ_LEN,
        'horizon': HORIZON,
    }, f"{MODEL_DIR}/zone_lstm.pt")
    # Save metrics
    metrics = {
        'overall_mae': float(overall_mae),
        'overall_rmse': float(overall_rmse),
        'persistence_mae': float(pers_mae),
        'persistence_rmse': float(pers_rmse),
        'beats_persistence': overall_mae < pers_mae,
        'per_zone': {zones[i]: {'mae': float(mae_per_zone[i]), 'rmse': float(rmse_per_zone[i])} for i in range(len(zones))},
        'config': {
            'seq_len': SEQ_LEN, 'horizon': HORIZON, 'hidden': HIDDEN, 'layers': LAYERS,
            'dropout': DROPOUT, 'lr': LR, 'epochs_trained': epoch
        }
    }
    with open(f"{MODEL_DIR}/metrics.json", 'w') as f:
        json.dump(metrics, f, indent=2)
    logger.info(f"Saved model and metrics to {MODEL_DIR}")

if __name__ == "__main__":
    train()