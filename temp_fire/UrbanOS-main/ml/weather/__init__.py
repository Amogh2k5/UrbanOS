"""UrbanOS Phase 1B Weather ML — next-day weather (forecast-emulation) prediction.

This package trains ML models that predict next-day weather classes/numerics from
historical NEA 24-hour forecast data already in the repo. No new datasets are
introduced, no observations are invented. The ML task is *forecast-emulation*
(predicting the next-day NEA forecast fields from past NEA forecasts + PM2.5
features), consistent with the project's Phase 1B audit decision.

Targets (regression unless noted):
    - temperature_high_next_day      (°C, NEA convention)
    - temperature_low_next_day       (°C)
    - relative_humidity_high_next_day (%)
    - relative_humidity_low_next_day  (%)
    - wind_speed_high_next_day        (km/h, NEA convention)
    - wind_speed_low_next_day         (km/h)
    - forecast_code_next_day          (multiclass classification on top-K codes)

Candidates and baselines are re-used from `ml.phase1_pm25.models` and
`.baselines` for consistency (no DL, GBT family per architecture §16).
"""
