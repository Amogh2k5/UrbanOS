import pandas as pd
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Replicate what the endpoint does
from backend.app.environment.pm25.predictor import PM25Predictor
from backend.app.environment.weather.data import WeatherForecastStore
from backend.app.environment.pm25.data import Pm25ObservationStore
from ml.pm25.config import RAW_PM25_CSV, RAW_WEATHER_DIR, REGIONS

SG_OFFSET = timezone(timedelta(hours=8))
now_sg = pd.Timestamp(datetime.now(SG_OFFSET))
STALENESS_THRESHOLD_DAYS = 7

weather_store = WeatherForecastStore()
pm25_store = Pm25ObservationStore()
latest_forecast_ts = weather_store.get_latest_forecast_timestamp()

print('Latest forecast:', latest_forecast_ts)

latest_forecast = pd.Timestamp(latest_forecast_ts)
weather_age_days = (now_sg - latest_forecast).total_seconds() / 86400
print('Weather age:', weather_age_days)

latest_pm25_obs_ts = pm25_store.get_latest_observation_timestamp()
print('Latest PM2.5:', latest_pm25_obs_ts)
latest_pm25_obs = pd.Timestamp(latest_pm25_obs_ts)
pm25_age_days = (now_sg - latest_pm25_obs).total_seconds() / 86400
print('PM25 age:', pm25_age_days)

# Determine t0 from latest PM2.5 observation
pm25_long = pm25_store.to_long_dataframe(REGIONS)
obs = pm25_long["observed_at"]
if obs.dt.tz is None:
    obs = obs.dt.tz_localize("Asia/Singapore")
else:
    obs = obs.dt.tz_convert("Asia/Singapore")
max_obs = obs.max()
print('Max obs:', max_obs)

t0_candidate = max_obs.normalize() + pd.Timedelta(hours=23)
if t0_candidate > max_obs:
    t0_candidate = max_obs.normalize() - pd.Timedelta(days=1) + pd.Timedelta(hours=23)
    if t0_candidate > max_obs:
        t0_candidate = max_obs.floor("h")

cap = latest_forecast.normalize() + pd.Timedelta(hours=23)
if cap < t0_candidate:
    t0_candidate = cap if cap <= max_obs else max_obs.floor("h")

prediction_timestamp = t0_candidate
print('Prediction timestamp:', prediction_timestamp)

# Get predictor
predictor = PM25Predictor(
    runs_dir=Path("ml/pm25/runs"),
    run_id="phase1_v1",
    models_dir=Path("ml/pm25/models/production"),
)

# Run prediction
features_df, per_region, diagnostics = predictor.predict_all_regions(
    prediction_timestamp=prediction_timestamp,
    pm25_csv=RAW_PM25_CSV,
    weather_dir=RAW_WEATHER_DIR,
    weather_store=weather_store,
    pm25_store=pm25_store,
)

print('Per region:')
for region, pred in per_region.items():
    print(f"  {region}: mean={pred.pm25_next_day_mean}, max={pred.pm25_next_day_max}")

# Now test the response builder
def _build_pm25_prediction_response(
    predictor, per_region, diagnostics, prediction_timestamp
):
    regions = ("north", "south", "east", "west", "central")
    predictions = []
    for region in regions:
        pred = per_region.get(region)
        if pred is None:
            predictions.append({
                "region": region,
                "available": False,
                "unavailable_reason": "No prediction returned for region",
                "next_day_mean_ugm3": None,
                "next_day_max_ugm3": None,
                "model": None,
                "is_ml_model": False,
                "fallback_reason": None,
            })
            continue
    
        predictions.append({
            "region": region,
            "available": pred.selected_model != "MISSING_FEATURES",
            "unavailable_reason": pred.fallback_reason if pred.selected_model == "MISSING_FEATURES" else None,
            "next_day_mean_ugm3": round(pred.pm25_next_day_mean, 1) if pred.pm25_next_day_mean is not None else None,
            "next_day_max_ugm3": round(pred.pm25_next_day_max, 1) if pred.pm25_next_day_max is not None else None,
            "model": pred.selected_model,
            "is_ml_model": pred.is_ml_model,
            "target_models": pred.target_models,
            "persistence_value_pm25_t0": round(pred.persistence_value_pm25_t0, 1) if pred.persistence_value_pm25_t0 is not None else None,
            "fallback_reason": pred.fallback_reason,
        })
    return {"regions": predictions}

response = _build_pm25_prediction_response(predictor, per_region, diagnostics, prediction_timestamp)
print('\nBuilt response:')
for r in response['regions']:
    print(f"  {r['region']}: mean={r['next_day_mean_ugm3']}, max={r['next_day_max_ugm3']}, model={r['model']}")