# Spatio-Temporal Transformer for Traffic Forecasting

## Data
- Source: `traffic/data/processed/zone_speed_series_raw.csv`
- 1,173 complete snapshots, 8 zones, ~15 days (2026-08-21 to 2026-09-05)
- No resampling, no interpolation.

## Model
- Small Transformer encoder
- Input: sequence of 6 real snapshots, each snapshot = 8 zones × 9 features
- Zone embeddings + temporal positional encoding
- 2 encoder layers, 4 heads, d_model=32
- Predicts next real snapshot avg_speed for 8 zones

## Split
Chronological 70/15/15 on sequences (derived from snapshot order).

## Results (test set)
- Transformer MAE: 0.2349 km/h, RMSE: 0.3022 km/h
- Persistence MAE: 0.1019 km/h, RMSE: 0.1986 km/h
- XGBoost MAE: 0.1010 km/h, RMSE: 0.3840 km/h
- ST-LSTM MAE: 0.108 km/h, RMSE: 0.401 km/h

## Conclusion
Transformer does NOT beat XGBoost (higher MAE/RMSE). XGBoost remains the best model.
