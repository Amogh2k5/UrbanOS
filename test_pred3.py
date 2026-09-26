import pandas as pd
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
sys.path.insert(0, 'C:/projects/UrbanOS')

from backend.app.environment.pm25.predictor import PM25Predictor
from backend.app.environment.weather.data import WeatherForecastStore
from backend.app.environment.pm25.data import Pm25ObservationStore
from ml.pm25.config import RAW_PM25_CSV, RAW_WEATHER_DIR, REGIONS

# Simulate what the endpoint does
SG_OFFSET = timezone(timedelta(hours=8))
now_sg = pd.Timestamp(datetime.now(SG_OFFSET))
STALENESS_THRESHOLD_DAYS = 7

weather_store = WeatherForecastStore()
pm25_store = Pm25ObservationStore()
latest_forecast_ts = weather_store.get_latest_forecast_timestamp()

if latest_forecast_ts is None:
    print("No weather forecast")
    sys.exit(1)

latest_forecast = pd.Timestamp(latest_forecast_ts)
weather_age_days = (now_sg - latest_forecast).total_seconds() / 86400

if weather_age_days > STALENESS_THRESHOLD_DAYS:
    print("Weather stale")
    sys.exit(1)

PM25_STALENESS_DAYS = 2
latest_pm25_obs_ts = pm25_store.get_latest_observation_timestamp()
if latest_pm25_obs_ts is None:
    print("No PM2.5 observations")
    sys.exit(1)

latest_pm25_obs = pd.Timestamp(latest_pm25_obs_ts)
pm25_age_days = (now_sg - latest_pm25_obs).total_seconds() / 86400

if pm25_age_days > PM25_STALENESS_DAYS:
    print("PM2.5 stale")
    sys.exit(1)

# Determine t0
pm25_long = pm25_store.to_long_dataframe(REGIONS)
obs = pm25_long["observed_at"]
if obs.dt.tz is None:
    obs = obs.dt.tz_localize("Asia/Singapore")
else:
    obs = obs.dt.tz_convert("Asia/Singapore")
max_obs = obs.max()

t0_candidate = max_obs.normalize() + pd.Timedelta(hours=23)
if t0_candidate > max_obs:
    t0_candidate = max_obs.normalize() - pd.Timedelta(days=1) + pd.Timedelta(hours=23)
    if t0_candidate > max_obs:
        t0_candidate = max_obs.floor("h")

cap = latest_forecast.normalize() + pd.Timedelta(hours=23)
if cap < t0_candidate:
    t0_candidate = cap if cap <= max_obs else max_obs.floor("h")

prediction_timestamp = t0_candidate

predictor = PM25Predictor(
    runs_dir=Path("ml/pm25/runs"),
    run_id="phase1_v1",
    models_dir=Path("ml/pm25/models/production"),
)

features_df, per_region, diagnostics = predictor.predict_all_regions(
    prediction_timestamp=prediction_timestamp,
    pm25_csv=RAW_PM25_CSV,
    weather_dir=RAW_WEATHER_DIR,
    weather_store=weather_store,
    pm25_store=pm25_store,
)

print("Predictions from predictor:")
for region, pred in per_region.items():
    print(f"  {region}: mean={pred.pm25_next_day_mean}, max={pred.pm25_next_day_max}")

# Check what the endpoint's _get_pm25_predictor returns
from backend.app.main import _get_pm25_predictor
predictor2 = _get_pm25_predictor()
print(f"\nPredictor from endpoint: {type(predictor2)}")
print(f"Models dir: {predictor2.models_dir}")
print(f"Runs dir: {predictor2.runs_dir}")
print(f"Run ID: {predictor2.run_id}")

features_df2, per_region2, diagnostics2 = predictor2.predict_all_regions(
    prediction_timestamp=prediction_timestamp,
    pm25_csv=RAW_PM25_CSV,
    weather_dir=RAW_WEATHER_DIR,
    weather_store=weather_store,
    pm25_store=pm25_store,
)

print("\nPredictions from endpoint predictor:")
for region, pred in per_region2.items():
    print(f"  {region}: mean={pred.pm25_next_day_mean}, max={pred.pm25_next_day_max}")