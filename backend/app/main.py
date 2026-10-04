"""FastAPI app for the UrbanOS Environment module.

Exposes:
    GET /health
    GET /kpi/live/pm25       ├óΓé¼ΓÇ¥ normalized PM2.5 KPI from NEA live API (or fixture)
    GET /kpi/live/weather    ├óΓé¼ΓÇ¥ normalized 24h weather forecast KPI from NEA live API (or fixture)
    GET /kpi/live/traffic    ├óΓé¼ΓÇ¥ normalized Traffic Speed Bands KPI from LTA live API (or fixture)

KPI endpoints return normalized JSON with values, timestamps and
freshness/source. API-provider logic (adapter quirks) NEVER reaches the
frontend; the frontend only sees normalized JSON.

ML/artifacts/agent-graph are NOT wired to HTTP here ├óΓé¼ΓÇ¥ the LangGraph
EnvironmentAgent is a separate offline orchestration invoked via CLI
(see backend/app/environment/run_agent.py). Live API data does NOT enter ML.
"""

from __future__ import annotations

import logging
import os
import time
import asyncio
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.app.environment.pm25.api import Pm25ApiClient, Pm25LiveSnapshot
from backend.app.environment.weather.api import WeatherApiClient, WeatherLiveSnapshot, AirTemperatureApiClient, AirTemperatureSnapshot
from backend.app.mobility.traffic.api import TrafficSpeedBandsV2ApiClient, TrafficSpeedBandsV2Snapshot, TrafficIncidentsApiClient, TrafficIncidentsSnapshot
from backend.app.environment.flood.api import FloodAlertsApiClient, FloodAlertsSnapshot
from backend.app.mobility.traffic.data import collect_traffic_once, get_collection_stats, TrafficCollector
from backend.app.mobility.traffic.prediction_service import get_traffic_prediction_service
from backend.app.environment.pm25.predictor import PM25Predictor, _IngestCache
from backend.app.environment.weather.data import collect_weather_once, get_weather_collection_stats, WeatherForecastCollector, WeatherForecastStore
from backend.app.environment.weather.scheduler import WeatherScheduler, run_weather_scheduler
from backend.app.environment.pm25.data import collect_pm25_once, get_pm25_collection_stats, Pm25Collector, Pm25ObservationStore
from backend.app.environment.pm25.live_service import get_pm25_live_service
from backend.app.environment.pm25.scheduler import Pm25Scheduler, run_pm25_scheduler
from backend.app.environment.selectors import load_selections
from backend.app.environment.result import RegionPrediction
from ml.pm25.config import RAW_PM25_CSV, RAW_WEATHER_DIR, RUNS_DIR
from backend.app.mobility.traffic.api import router as traffic_router
from backend.app.mobility.transit.api import router as transit_router
from backend.app.mobility.roads.api import router as roads_router
from backend.app.safety.fire.api import router as fire_router
from backend.app.overview.api import router as overview_router
from backend.app.mobility.transit.scheduler import TransitAlertsScheduler, SchedulerConfig

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))

# City report: single-flight lock + short TTL cache. A coordinator run costs
# ~60s of CPU; without this, every timed-out client leaves a full run grinding
# in the threadpool and requests stack on top of each other.
_city_report_lock = threading.Lock()
_city_report_cache: Dict[str, Any] = {"payload": None, "expires_at": 0.0}
_CITY_REPORT_CACHE_TTL_S = 120.0


def _build_app() -> FastAPI:
    app = FastAPI(
        title="UrbanOS Environment Module",
        version="1.0",
        description=(
            "Environment domain: PM2.5 ML artifacts + NEA 24h weather + live KPI "
            "endpoints. Live API is for dashboard KPI display only; never enters ML."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Adapter singletons. offline mode = reads env var URBANOS_API_OFFLINE=1.
    offline = os.getenv("URBANOS_API_OFFLINE", "0") == "1"
    app.state.pm25_client = Pm25ApiClient(offline=offline)
    app.state.air_temperature_client = AirTemperatureApiClient(offline=offline)
    app.state.weather_client = WeatherApiClient(offline=offline, air_temperature_client=app.state.air_temperature_client)
    try:
        app.state.traffic_client = TrafficSpeedBandsV2ApiClient()
    except Exception:
        app.state.traffic_client = None
    app.state.traffic_incidents_client = TrafficIncidentsApiClient(offline=offline)
    app.state.flood_client = FloodAlertsApiClient(offline=offline)

    # Traffic Agent (LangGraph) - lazy loaded
    app.state.traffic_agent = None

    # Traffic live-prediction service: seeds rolling per-link history from the
    # latest 7 complete SQLite snapshots (indexed skip-scan, no full scans),
    # then refreshes the shared XGBoost PredictionBundle in a background thread
    # once per new snapshot. /api/mobility/traffic/predict and
    # /api/traffic/report both READ this bundle; they never compute their own.
    app.state.traffic_prediction_service = get_traffic_prediction_service()
    app.state.traffic_prediction_service.start()

    # Weather forecast store and collector
    app.state.weather_store = WeatherForecastStore()
    app.state.weather_collector = WeatherForecastCollector(
        api_client=app.state.weather_client,
        store=app.state.weather_store,
    )

    # PM2.5 observation store and collector
    app.state.pm25_store = Pm25ObservationStore()
    app.state.pm25_collector = Pm25Collector(
        api_client=app.state.pm25_client,
        store=app.state.pm25_store,
    )

    # Weather scheduler
    app.state.weather_scheduler = WeatherScheduler(
        collector=app.state.weather_collector,
    )

    # PM2.5 live snapshot service: seeds from the observation store, then
    # refreshes the shared latest snapshot from the live NEA API in the
    # background (hourly). /kpi/live/pm25 reads it; requests never hit the API.
    app.state.pm25_live_service = get_pm25_live_service()
    app.state.pm25_live_service.start()

    # PM2.5 scheduler
    app.state.pm25_scheduler = Pm25Scheduler(
        collector=app.state.pm25_collector,
    )

    # Transit alerts scheduler (runs every 5 minutes)
    app.state.transit_alerts_scheduler = TransitAlertsScheduler(
        config=SchedulerConfig(interval_seconds=300),
    )

    # ---------------------------------------------------------------- routes

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {"status": "ok", "time": datetime.now(SG_OFFSET).isoformat()}

    @app.get("/kpi/live/pm25")
    def kpi_live_pm25(date: Optional[str] = Query(None, description="YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS")) -> Dict[str, Any]:
        # Latest reading: serve the shared in-memory snapshot (refreshed hourly
        # by the background PM2.5 live service) instead of calling the NEA API
        # on every frontend request. Historical lookups (?date=...) still go
        # through the adapter directly.
        if date is None:
            snap = app.state.pm25_live_service.snapshot()
            if snap is not None:
                return snap.to_dict()
        client: Pm25ApiClient = app.state.pm25_client
        try:
            snap: Pm25LiveSnapshot = client.fetch(date=date)
        except Exception as e:
            log.exception("PM2.5 KPI fetch failed")
            raise HTTPException(status_code=502, detail=f"pm25 adapter error: {e}")
        return snap.to_dict()

    @app.get("/kpi/live/weather")
    def kpi_live_weather(date: Optional[str] = Query(None, description="YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS")) -> Dict[str, Any]:
        client: WeatherApiClient = app.state.weather_client
        try:
            snap: WeatherLiveSnapshot = client.fetch(date=date)
        except Exception as e:
            log.exception("Weather KPI fetch failed")
            raise HTTPException(status_code=502, detail=f"weather adapter error: {e}")
        return snap.to_dict()

    @app.get("/kpi/live/traffic")
    def kpi_live_traffic() -> Dict[str, Any]:
        client: TrafficSpeedBandsV2ApiClient = app.state.traffic_client
        if client is None:
            raise HTTPException(status_code=503, detail="Traffic client unavailable (LTA_API_KEY not configured)")
        try:
            snap: TrafficSpeedBandsV2Snapshot = client.fetch()
        except Exception as e:
            log.exception("Traffic Speed Bands KPI fetch failed")
            raise HTTPException(status_code=502, detail=f"traffic adapter error: {e}")
        return snap.to_dict()

    @app.get("/kpi/live/traffic-incidents")
    def kpi_live_traffic_incidents() -> Dict[str, Any]:
        client: TrafficIncidentsApiClient = app.state.traffic_incidents_client
        try:
            snap: TrafficIncidentsSnapshot = client.fetch()
        except Exception as e:
            log.exception("Traffic Incidents KPI fetch failed")
            raise HTTPException(status_code=502, detail=f"traffic incidents adapter error: {e}")
        return snap.to_dict()

    @app.get("/kpi/live/flood")
    def kpi_live_flood() -> Dict[str, Any]:
        client: FloodAlertsApiClient = app.state.flood_client
        try:
            snap: FloodAlertsSnapshot = client.fetch()
        except Exception as e:
            log.exception("Flood Alerts KPI fetch failed")
            raise HTTPException(status_code=502, detail=f"flood adapter error: {e}")
        return snap.to_dict()

    @app.get("/kpi/live/air-temperature")
    def kpi_live_air_temperature() -> Dict[str, Any]:
        client: AirTemperatureApiClient = app.state.air_temperature_client
        try:
            snap: AirTemperatureSnapshot = client.fetch()
        except Exception as e:
            log.exception("Air Temperature KPI fetch failed")
            raise HTTPException(status_code=502, detail=f"air temperature adapter error: {e}")
        return snap.to_dict()
    
    # PM2.5 ML Prediction endpoint
    def _get_pm25_predictor() -> PM25Predictor:
        """Initialize PM25Predictor with production model artifacts."""
        # Use production models directory with CatBoost models (benchmark winner)
        # The predictor will automatically load selections from ml/pm25/models/production/selections.csv
        return PM25Predictor(
            runs_dir=RUNS_DIR,
            run_id="phase1_v1",  # used for selections.csv fallback and weather data
            models_dir=Path("ml/pm25/models/production"),
        )
    
    def _build_pm25_prediction_response(
        predictor: PM25Predictor,
        per_region: Dict[str, RegionPrediction],
        diagnostics: Dict[str, object],
        prediction_timestamp: pd.Timestamp,
    ) -> Dict[str, Any]:
        """Build structured response for PM2.5 prediction endpoint."""
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
    
        return {
            "prediction_timestamp": prediction_timestamp.isoformat(),
            "prediction_horizon_hours": 24,
            "target_window": {
                "start": (prediction_timestamp + pd.Timedelta(hours=1)).isoformat(),
                "end": (prediction_timestamp + pd.Timedelta(hours=24)).isoformat(),
            },
            "regions": predictions,
            "model_metadata": {
                "run_id": "phase1_v1",
                "selected_regions_ml": [r for r in regions if per_region.get(r, RegionPrediction(region=r, selected_model="", is_ml_model=False, pm25_next_day_mean=None, pm25_next_day_max=None)).is_ml_model],
                "selected_regions_persist": [r for r in regions if not per_region.get(r, RegionPrediction(region=r, selected_model="", is_ml_model=False, pm25_next_day_mean=None, pm25_next_day_max=None)).is_ml_model and per_region.get(r).selected_model == "bl_persist"],
                "selection_policy": "Phase 1: candidate must beat persistence on both val MAE and RMSE; otherwise bl_persist",
            },
            "diagnostics": {
                "predictions_total": diagnostics.get("predictions_total", 0),
                "predictions_ml": diagnostics.get("predictions_ml", 0),
                "predictions_persist": diagnostics.get("predictions_persist", 0),
                "regions_missing_features": diagnostics.get("regions_missing_features", []),
                "feature_report_rows": diagnostics.get("feature_report_rows", 0),
            },
            "source": "UrbanOS PM2.5 ML (Phase 1 CatBoost / persistence baseline)",
        }
    
    def _default_t0_from_pm25(pm25_csv: Path, weather_dir: Path) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp | None]:
        """Replicate EnvironmentModule._default_t0_from_pm25 logic to determine t0 from latest data.
    
        Returns:
            (prediction_timestamp, max_pm25_obs, max_weather_issue or None if no weather data)
        """
        from backend.app.environment.pm25_predictor import _IngestCache
        from ml.pm25.ingest_pm25 import ingest_pm25
        from ml.pm25.ingest_weather import ingest_weather as _ingest_weather_raw
    
        # Ingest PM2.5 and weather to get the latest available data
        pm25_long, _ = ingest_pm25(str(pm25_csv), ("north", "south", "east", "west", "central"))
        nat, per, _ = _ingest_weather_raw(str(weather_dir))
    
        obs = pm25_long["observed_at"]
        if obs.dt.tz is None:
            obs = obs.dt.tz_localize("Asia/Singapore")
        else:
            obs = obs.dt.tz_convert("Asia/Singapore")
        max_obs = obs.max()
    
        # Try the calendar day of max_obs at 23:00
        t0_candidate = max_obs.normalize() + pd.Timedelta(hours=23)
        if t0_candidate > max_obs:
            t0_candidate = max_obs.normalize() - pd.Timedelta(days=1) + pd.Timedelta(hours=23)
            if t0_candidate > max_obs:
                t0_candidate = max_obs.floor("h")
    
        # Cap by latest weather issue if provided
        max_weather = None
        if nat is not None and not nat.empty:
            wts = nat["timestamp"]
            if wts.dt.tz is None:
                wts = wts.dt.tz_localize("Asia/Singapore")
            else:
                wts = wts.dt.tz_convert("Asia/Singapore")
            max_weather = wts.max()
            cap = max_weather.normalize() + pd.Timedelta(hours=23)
            if cap < t0_candidate:
                t0_candidate = cap if cap <= max_obs else max_obs.floor("h")
    
        return t0_candidate, max_obs, max_weather
    
    @app.get("/api/pollution/predict")
    def pollution_predict(
        t0: Optional[str] = Query(None, description="Issuance cutoff t0, ISO format (e.g., 2024-12-30T23:00:00+08:00). Defaults to latest available PM2.5 observation hour (D 23:00 Asia/Singapore)."),
    ) -> Dict[str, Any]:
        """Generate next-day PM2.5 predictions using Phase 1 trained models.
    
        Returns per-region next-day mean and max PM2.5 predictions with model provenance.
        Uses the same leakage-safe feature construction as the training pipeline.
    
        For current predictions (no explicit t0): uses collected live NEA weather forecast data.
        Returns 503 if no sufficiently recent weather forecast is available.
    
        For historical predictions (explicit t0): uses historical CSV data.
        """
        import pandas as pd
        from pathlib import Path
        from datetime import datetime, timezone, timedelta
    
        SG_OFFSET = timezone(timedelta(hours=8))
        now_sg = pd.Timestamp(datetime.now(SG_OFFSET))
        STALENESS_THRESHOLD_DAYS = 7
    
        # Parse prediction timestamp
        explicit_t0 = t0 is not None
        max_pm25_obs = None
        max_weather_issue = None
        weather_store = None
    
        if explicit_t0:
            # Historical prediction: use CSVs
            try:
                prediction_timestamp = pd.Timestamp(t0)
                if prediction_timestamp.tzinfo is None:
                    prediction_timestamp = prediction_timestamp.tz_localize("Asia/Singapore")
                else:
                    prediction_timestamp = prediction_timestamp.tz_convert("Asia/Singapore")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid t0 format: {e}")
            # For historical, also get max pm25/weather for response metadata
            from ml.pm25.ingest_pm25 import ingest_pm25
            from ml.pm25.config import REGIONS
            pm25_long, _ = ingest_pm25(str(RAW_PM25_CSV), REGIONS)
            obs = pm25_long["observed_at"]
            if obs.dt.tz is None:
                obs = obs.dt.tz_localize("Asia/Singapore")
            else:
                obs = obs.dt.tz_convert("Asia/Singapore")
            max_pm25_obs = obs.max()
    
            from ml.pm25.ingest_weather import ingest_weather as _ingest_weather_raw
            nat, per, _ = _ingest_weather_raw(str(RAW_WEATHER_DIR))
            if nat is not None and not nat.empty:
                wts = nat["timestamp"]
                if wts.dt.tz is None:
                    wts = wts.dt.tz_localize("Asia/Singapore")
                else:
                    wts = wts.dt.tz_convert("Asia/Singapore")
                max_weather_issue = wts.max()
        else:
            # Current prediction: use collected live weather data
            weather_store = app.state.weather_store
            pm25_store = app.state.pm25_store
            latest_forecast_ts = weather_store.get_latest_forecast_timestamp()
    
            if latest_forecast_ts is None:
                log.warning("PM2.5 prediction refused: no weather forecast data collected")
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "Prediction unavailable: no weather forecast data collected",
                        "message": "Run the weather collector first to populate the forecast database.",
                        "staleness_threshold_days": STALENESS_THRESHOLD_DAYS,
                        "current_time_sg": now_sg.isoformat(),
                    }
)
            
            latest_forecast = pd.Timestamp(latest_forecast_ts)
            weather_age_days = (now_sg - latest_forecast).total_seconds() / 86400
    
            if weather_age_days > STALENESS_THRESHOLD_DAYS:
                log.warning(
                    "PM2.5 prediction refused: collected weather data is stale (latest: %s, age: %.1f days > %d days)",
                    latest_forecast_ts, weather_age_days, STALENESS_THRESHOLD_DAYS
                )
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "Prediction unavailable: weather forecast data is stale",
                        "message": (
                            f"Latest collected weather forecast is {latest_forecast_ts} "
                            f"({weather_age_days:.1f} days old). Run the weather collector to fetch a current forecast."
                        ),
                        "latest_weather_forecast": latest_forecast_ts,
                        "staleness_threshold_days": STALENESS_THRESHOLD_DAYS,
                        "current_time_sg": now_sg.isoformat(),
                    }
                )
    
            # PM2.5 observation freshness check
            PM25_STALENESS_DAYS = 2
            latest_pm25_obs_ts = pm25_store.get_latest_observation_timestamp()
            if latest_pm25_obs_ts is None:
                log.warning("PM2.5 prediction refused: no PM2.5 observations collected")
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "Prediction unavailable: no PM2.5 observations collected",
                        "message": "Run the PM2.5 collector first to populate the observation database.",
                        "staleness_threshold_days": PM25_STALENESS_DAYS,
                        "current_time_sg": now_sg.isoformat(),
                    }
                )
            latest_pm25_obs = pd.Timestamp(latest_pm25_obs_ts)
            pm25_age_days = (now_sg - latest_pm25_obs).total_seconds() / 86400
            if pm25_age_days > PM25_STALENESS_DAYS:
                log.warning(
                    "PM2.5 prediction refused: collected PM2.5 data is stale (latest: %s, age: %.1f days > %d days)",
                    latest_pm25_obs_ts, pm25_age_days, PM25_STALENESS_DAYS
                )
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "Prediction unavailable: PM2.5 observation data is stale",
                        "message": (
                            f"Latest collected PM2.5 observation is {latest_pm25_obs_ts} "
                            f"({pm25_age_days:.1f} days old). Run the PM2.5 collector to fetch a current observation."
                        ),
                        "latest_pm25_observation": latest_pm25_obs_ts,
                        "staleness_threshold_days": PM25_STALENESS_DAYS,
                        "current_time_sg": now_sg.isoformat(),
                    }
                )

# Determine t0 from latest PM2.5 observation (capped by latest weather forecast)
            from ml.pm25.config import REGIONS

            # Use live PM2.5 observations from store for current predictions
            pm25_store = app.state.pm25_store
            pm25_long = pm25_store.to_long_dataframe(REGIONS)
            obs = pm25_long["observed_at"]
            if obs.dt.tz is None:
                obs = obs.dt.tz_localize("Asia/Singapore")
            else:
                obs = obs.dt.tz_convert("Asia/Singapore")
            max_obs = obs.max()

            # Try the calendar day of max_obs at 23:00
            t0_candidate = max_obs.normalize() + pd.Timedelta(hours=23)
            if t0_candidate > max_obs:
                t0_candidate = max_obs.normalize() - pd.Timedelta(days=1) + pd.Timedelta(hours=23)
                if t0_candidate > max_obs:
                    t0_candidate = max_obs.floor("h")

            # Cap by latest weather forecast issue
            cap = latest_forecast.normalize() + pd.Timedelta(hours=23)
            if cap < t0_candidate:
                t0_candidate = cap if cap <= max_obs else max_obs.floor("h")

            prediction_timestamp = t0_candidate
            max_pm25_obs = max_obs
            max_weather_issue = latest_forecast

            try:
                predictor = _get_pm25_predictor()
                pm25_store = app.state.pm25_store

                # Run prediction (uses weather_store and pm25_store if provided for current predictions)
                features_df, per_region, diagnostics = predictor.predict_all_regions(
                    prediction_timestamp=prediction_timestamp,
                    pm25_csv=RAW_PM25_CSV,
                    weather_dir=RAW_WEATHER_DIR,
                    weather_store=weather_store,
                    pm25_store=pm25_store,
                )

                response = _build_pm25_prediction_response(predictor, per_region, diagnostics, prediction_timestamp)
                # Add data source info
                response["data_source"] = {
                    "pm25": "historical_csv" if explicit_t0 else "collected_live_observations",
                    "weather": "historical_csv" if explicit_t0 else "collected_live_forecast",
                    "weather_forecast_timestamp": max_weather_issue.isoformat() if max_weather_issue is not None else None,
                    "pm25_observation_timestamp": pm25_store.get_latest_observation_timestamp() if hasattr(pm25_store, 'get_latest_observation_timestamp') else None,
                }
                return response

            except FileNotFoundError as e:
                log.error("PM2.5 model artifact missing: %s", e)
                raise HTTPException(status_code=503, detail=f"Model artifact unavailable: {e}")
            except ValueError as e:
                log.error("PM2.5 prediction failed: %s", e)
                raise HTTPException(status_code=503, detail=f"Insufficient data for prediction: {e}")
            except Exception as e:
                log.exception("PM2.5 prediction failed")
                raise HTTPException(status_code=500, detail=f"Prediction error: {e}")
    
    @app.get("/api/traffic/predict")
    @app.get("/api/mobility/traffic/predict")
    async def traffic_predict() -> Dict[str, Any]:
        """Generate real-time per-link traffic speed predictions using production XGBoost.

        Returns:
            - prediction_timestamp
            - target_timestamp (t+5min)
            - model info
            - list of link predictions with current/predicted speed
            - division aggregation (8 zones)
        """
        try:
            import asyncio

            # Read the shared PredictionBundle computed once per new snapshot by
            # the background TrafficPredictionService (rolling 7-obs-per-link
            # history + existing TrafficPredictor, unchanged). Single-flight:
            # concurrent cold-start requests coalesce onto ONE computation; a
            # stale bundle is served with its real observed_at; when nothing has
            # ever been computed, raise the same no-data error as before.
            service = get_traffic_prediction_service()
            bundle = await asyncio.to_thread(service.get_bundle)
            if bundle is None or not bundle.link_preds:
                raise ValueError("No traffic observations available")
            link_preds = bundle.link_preds
            diagnostics = bundle.diagnostics

            # Compatibility mapping from legacy LTA zone IDs to official 5 regions
            LEGACY_TO_REGION = {
                "SG_CENTRAL_NORTH": "Central",
                "SG_CENTRAL_SOUTH": "Central",
                "SG_EAST": "East",
                "SG_NORTH": "North",
                "SG_NORTH_EAST": "North-East",
                "SG_WEST_NORTH": "West",
                "SG_WEST_SOUTH": "West",
                "SG_SENTOSA": "Central",
            }
            
            # Define the 5 official Singapore regions in required order
            region_order = ["Central", "East", "North", "North-East", "West"]
            
            # Aggregate by official region using legacy-to-region mapping
            divisions = {}
            unrecognized = set()
            for lp in link_preds:
                legacy = lp.zone_id or "UNKNOWN"
                region = LEGACY_TO_REGION.get(legacy)
                if region is None:
                    unrecognized.add(legacy)
                    region = "UNKNOWN"
                divisions.setdefault(region, {"current": [], "predicted": [], "count": 0})
                divisions[region]["current"].append(lp.current_speed)
                divisions[region]["predicted"].append(lp.predicted_speed)
                divisions[region]["count"] += 1
            
            if unrecognized:
                import logging
                logging.getLogger(__name__).warning(
                    "Unrecognized legacy zone IDs encountered: %s", sorted(unrecognized)
                )
            
            division_list = []
            for region_name in region_order:
                vals = divisions.get(region_name)
                if vals:
                    current_vals = vals["current"]
                    predicted_vals = vals["predicted"]
                    total_count = vals["count"]
                else:
                    current_vals = []
                    predicted_vals = []
                    total_count = 0
                
                cur_avg = sum(current_vals) / len(current_vals) if current_vals else None
                pred_avg = sum(predicted_vals) / len(predicted_vals) if predicted_vals else None
                
                speed_for_congestion = pred_avg if pred_avg is not None else cur_avg
                
                if speed_for_congestion is not None:
                    if speed_for_congestion >= 70:
                        congestion = "free_flow"
                    elif speed_for_congestion >= 50:
                        congestion = "moderate"
                    elif speed_for_congestion >= 30:
                        congestion = "heavy"
                    else:
                        congestion = "severe"
                else:
                    congestion = "unknown"
                
                division_list.append({
                    "division": region_name,
                    "current_avg_speed": round(cur_avg, 1) if cur_avg is not None else None,
                    "predicted_avg_speed": round(pred_avg, 1) if pred_avg is not None else None,
                    "speed_change": round((pred_avg - cur_avg), 1) if (cur_avg is not None and pred_avg is not None) else None,
                    "speed_change_percent": round((pred_avg - cur_avg) / cur_avg * 100, 1) if (cur_avg is not None and cur_avg != 0 and pred_avg is not None) else None,
                    "congestion_level": congestion,
                    "segment_count": total_count,
                })
            # No need to sort; region_order already defines order
            
            # Use first link's timestamps
            pred_ts = link_preds[0].prediction_timestamp if link_preds else None
            target_ts = link_preds[0].target_timestamp if link_preds else None
            
            return {
                "prediction_timestamp": pred_ts,
                "target_timestamp": target_ts,
                "prediction_horizon_minutes": 5,
                "model": "xgboost",
                "is_ml_model": True,
                "source": "live_lta_observations",
                "diagnostics": diagnostics,
                "link_predictions": [
                    {
                        "link_id": lp.link_id,
                        "road_name": lp.road_name,
                        "road_category": lp.road_category,
                        "zone_id": lp.zone_id,
                        "zone_name": lp.zone_name,
                        "current_speed": lp.current_speed,
                        "predicted_speed": lp.predicted_speed,
                        "speed_change": lp.speed_change,
                    }
                    for lp in link_preds
                ],
                "divisions": division_list,
            }
        except Exception as e:
            log.exception("Traffic prediction failed")
            raise HTTPException(status_code=500, detail=f"traffic prediction error: {e}")
    
    @app.get("/api/traffic/report")
    def traffic_report(offline: bool = Query(False, description="Use offline mode for live incidents")) -> Dict[str, Any]:
        """Generate full Traffic Report via LangGraph Traffic Agent.
    
        Combines:
        - XGBoost segment-level predictions (aggregated to zones)
        - Live LTA Traffic Incidents (with zone assignment)
        - 8 geographic traffic zones
    
        Returns structured TrafficReport.
        """
        try:
            from backend.app.mobility.traffic.agent import run_traffic_agent
    
            report = run_traffic_agent(offline=offline)
            return report.model_dump()
        except Exception as e:
            log.exception("Traffic report generation failed")
            raise HTTPException(status_code=500, detail=f"traffic agent error: {e}")
    
    @app.get("/api/flood/report")
    def flood_report(offline: bool = Query(False, description="Use offline mode for live alerts")) -> Dict[str, Any]:
        """Generate full Flood Report V3 via LangGraph Flood Agent.
    
        Live Evidence (determines current risk):
        - Singapore rainfall (NEA 5-min API) ├óΓé¼ΓÇ¥ PRIMARY signal
        - Malaysia/Johor rainfall (MetMalaysia API) ├óΓé¼ΓÇ¥ SUPPORTING
        - Sumatra rainfall (BMKG API) ├óΓé¼ΓÇ¥ SUPPORTING
        - Regional weather systems (NEA 24h forecast) ├óΓé¼ΓÇ¥ SUPPORTING
        - PUB Flood Alerts ├óΓé¼ΓÇ¥ CONFIRMATION
    
        Reference Only:
        - Past flood events catalogue (78 events)
    
        Returns structured FloodReport V3 with:
        - risk_level (LOW/MODERATE/HIGH/CRITICAL/UNKNOWN)
        - risk_score (0.0-2.0)
        - active_alert_count / active_alerts
        - affected_zones
        - primary_risk_factors
        - singapore_rainfall / malaysia_rainfall / sumatra_rainfall evidence
        - regional_weather status
        - past_flood_events (REFERENCE ONLY)
        - recommendations / confidence / limitations
        - is_ml_prediction = false
        """
        try:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from backend.app.environment.flood.agent import run_flood_agent_v3
    
            report = run_flood_agent_v3(offline=offline)
            return report.model_dump()
        except Exception as e:
            log.exception("Flood report V3 generation failed")
            raise HTTPException(status_code=500, detail=f"flood agent v3 error: {e}")
    
    @app.get("/api/city/report")
    def city_report() -> Dict[str, Any]:
        """Generate City Situation Report via LangGraph City Coordinator.

        Orchestrates:
        - Environment Agent (PM2.5 ML + Weather)
        - Traffic Agent (XGBoost + Live Incidents)
        - Flood Agent (Historical Catalogue + Live Alerts)

        Returns structured CitySituationReport with:
        - overall_city_status / overall_risk_level
        - domain_status (environment, traffic, flood)
        - priority_incidents
        - cross_domain_impacts (flood+traffic, weather+flood, air_quality+weather, multi-domain)
        - city_level_recommendations
        - affected_zones
        - evidence / confidence / limitations
        - source_reports
        - is_ml_prediction = false
        """
        try:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from coordinator.city_agent import run_city_coordinator

            # The coordinator run costs ~60s of CPU. Without protection, every
            # client request (and every timed-out retry) spawns another full
            # run; the aborted ones keep grinding in the threadpool and stack
            # up until nothing completes within a useful time. Coalesce
            # concurrent requests onto a single run, and serve a short-lived
            # cache so bursts/refreshes don't each re-run the whole graph.
            now = time.time()
            cached = _city_report_cache["payload"]
            if cached is not None and now < _city_report_cache["expires_at"]:
                return cached

            with _city_report_lock:
                # Re-check after acquiring the lock: the request that held it
                # may already have produced a fresh report we can share.
                now = time.time()
                cached = _city_report_cache["payload"]
                if cached is not None and now < _city_report_cache["expires_at"]:
                    return cached

                started = time.time()
                report = run_city_coordinator()
                payload = report.model_dump()
                _city_report_cache["payload"] = payload
                _city_report_cache["expires_at"] = time.time() + _CITY_REPORT_CACHE_TTL_S
                log.info("City coordinator run completed in %.1fs", time.time() - started)
                return payload
        except Exception as e:
            log.exception("City report generation failed")
            raise HTTPException(status_code=500, detail=f"city coordinator error: {e}")
    
    # ---------------------------------------------------------------- internal traffic collection
    
    @app.post("/internal/traffic/collect")
    def internal_traffic_collect() -> Dict[str, Any]:
        """Trigger one LTA Traffic Speed Bands v2 collection run.
    
        Internal endpoint for manual/scheduled data ingestion.
        Fetches live data, maps to zones, stores observations.
    
        Returns:
            - timestamp: collection time
            - records_received: number of segments from API
            - records_stored: number of observations upserted
            - records_updated: number of existing records updated
            - zones_mapped: number of segments mapped to a zone
            - zones_unmapped: number of segments outside all zones
            - errors: list of any errors encountered
        """
        try:
            result = collect_traffic_once()
            return {
                "timestamp": result.timestamp,
                "records_received": result.records_received,
                "records_stored": result.records_stored,
                "records_updated": result.records_updated,
                "zones_mapped": result.zones_mapped,
                "zones_unmapped": result.zones_unmapped,
                "errors": result.errors,
            }
        except ValueError as e:
            # Configuration error (e.g., missing API key)
            log.error("Traffic collection configuration error: %s", e)
            raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            log.exception("Traffic collection failed")
            raise HTTPException(status_code=502, detail=f"traffic collection error: {e}")
    
    @app.get("/internal/traffic/stats")
    def internal_traffic_stats() -> Dict[str, Any]:
        """Get traffic observation storage statistics."""
        try:
            return get_collection_stats()
        except Exception as e:
            log.exception("Traffic stats failed")
            raise HTTPException(status_code=500, detail=f"traffic stats error: {e}")

    @app.get("/internal/traffic/predictions/status")
    def internal_traffic_prediction_status() -> Dict[str, Any]:
        """Status of the shared traffic PredictionBundle service."""
        return app.state.traffic_prediction_service.status()
    
    # ---------------------------------------------------------------- internal weather collection
    
    @app.post("/internal/weather/collect")
    def internal_weather_collect() -> Dict[str, Any]:
        """Trigger one NEA 24h Weather Forecast collection run.
    
        Internal endpoint for manual/scheduled data ingestion.
        Fetches live forecast, normalizes, stores in forecast database.
    
        Returns:
            - timestamp: collection time
            - national_forecasts_received: number of national forecasts from API
            - national_forecasts_stored: number of national forecasts upserted
            - national_forecasts_updated: number of existing national forecasts updated
            - period_forecasts_received: number of period forecasts from API
            - period_forecasts_stored: number of period forecasts upserted
            - period_forecasts_updated: number of existing period forecasts updated
            - errors: list of any errors encountered
        """
        try:
            result = collect_weather_once()
            return {
                "timestamp": result.timestamp,
                "national_forecasts_received": result.national_forecasts_received,
                "national_forecasts_stored": result.national_forecasts_stored,
                "national_forecasts_updated": result.national_forecasts_updated,
                "period_forecasts_received": result.period_forecasts_received,
                "period_forecasts_stored": result.period_forecasts_stored,
                "period_forecasts_updated": result.period_forecasts_updated,
                "errors": result.errors,
            }
        except ValueError as e:
            log.error("Weather collection configuration error: %s", e)
            raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            log.exception("Weather collection failed")
            raise HTTPException(status_code=502, detail=f"weather collection error: {e}")
    
    @app.get("/internal/weather/stats")
    def internal_weather_stats() -> Dict[str, Any]:
        """Get weather forecast storage statistics."""
        try:
            return get_weather_collection_stats()
        except Exception as e:
            log.exception("Weather stats failed")
            raise HTTPException(status_code=500, detail=f"weather stats error: {e}")
    
    # ---------------------------------------------------------------- internal PM2.5 collection
    
    @app.post("/internal/pm25/collect")
    def internal_pm25_collect() -> Dict[str, Any]:
        """Trigger one NEA PM2.5 observation collection run.
    
        Internal endpoint for manual/scheduled data ingestion.
        Fetches live PM2.5 observations, normalizes, stores in observation database.
    
        Returns:
            - timestamp: collection time
            - records_received: number of observations from API
            - records_stored: number of observations upserted
            - records_updated: number of existing observations updated
            - regions_received: list of regions present in response
            - api_failed: whether the API call failed
            - errors: list of any errors encountered
        """
        try:
            collector = app.state.pm25_collector
            result = collector.collect_once()
            return {
                "timestamp": result.timestamp,
                "records_received": result.records_received,
                "records_stored": result.records_stored,
                "records_updated": result.records_updated,
                "regions_received": result.regions_received,
                "api_failed": result.api_failed,
                "errors": result.errors,
            }
        except ValueError as e:
            log.error("PM2.5 collection configuration error: %s", e)
            raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            log.exception("PM2.5 collection failed")
            raise HTTPException(status_code=502, detail=f"pm25 collection error: {e}")
    
    @app.get("/internal/pm25/stats")
    def internal_pm25_stats() -> Dict[str, Any]:
        """Get PM2.5 observation storage statistics."""
        try:
            return get_pm25_collection_stats()
        except Exception as e:
            log.exception("PM2.5 stats failed")
            raise HTTPException(status_code=500, detail=f"pm25 stats error: {e}")
    
    # ---------------------------------------------------------------- internal Weather/PM2.5 schedulers
    
    @app.post("/internal/weather/scheduler/run")
    def internal_weather_scheduler_run() -> Dict[str, Any]:
        """Run one weather collection cycle manually.
    
        Returns:
            - timestamp: collection time
            - national_forecasts_received/stored/updated
            - period_forecasts_received/stored/updated
            - errors: list of any errors
        """
        try:
            scheduler = app.state.weather_scheduler
            scheduler._run_collection_cycle(time.time())
            result = scheduler.get_last_result()
            return {
                "timestamp": result.timestamp,
                "national_forecasts_received": result.national_forecasts_received,
                "national_forecasts_stored": result.national_forecasts_stored,
                "national_forecasts_updated": result.national_forecasts_updated,
                "period_forecasts_received": result.period_forecasts_received,
                "period_forecasts_stored": result.period_forecasts_stored,
                "period_forecasts_updated": result.period_forecasts_updated,
                "errors": result.errors,
            }
        except Exception as e:
            log.exception("Weather scheduler manual run failed")
            raise HTTPException(status_code=502, detail=f"weather scheduler error: {e}")
    
    @app.get("/internal/weather/scheduler/status")
    def internal_weather_scheduler_status() -> Dict[str, Any]:
        """Get weather scheduler status."""
        scheduler = app.state.weather_scheduler
        return {
            "running": scheduler.is_running(),
            "run_count": scheduler._run_count,
            "last_result": scheduler.get_last_result().__dict__ if scheduler.get_last_result() else None,
        }
    
    @app.post("/internal/pm25/scheduler/run")
    def internal_pm25_scheduler_run() -> Dict[str, Any]:
        """Run one PM2.5 collection cycle manually.
    
        Returns:
            - timestamp: collection time
            - records_received/stored/updated
            - regions_received
            - api_failed
            - errors
        """
        try:
            scheduler = app.state.pm25_scheduler
            scheduler._run_collection_cycle(time.time())
            result = scheduler.get_last_result()
            return {
                "timestamp": result.timestamp,
                "records_received": result.records_received,
                "records_stored": result.records_stored,
                "records_updated": result.records_updated,
                "regions_received": result.regions_received,
                "api_failed": result.api_failed,
                "errors": result.errors,
            }
        except Exception as e:
            log.exception("PM2.5 scheduler manual run failed")
            raise HTTPException(status_code=502, detail=f"pm25 scheduler error: {e}")
    
    @app.get("/internal/pm25/scheduler/status")
    def internal_pm25_scheduler_status() -> Dict[str, Any]:
        """Get PM2.5 scheduler status."""
        scheduler = app.state.pm25_scheduler
        return {
            "running": scheduler.is_running(),
            "run_count": scheduler._run_count,
            "last_result": scheduler.get_last_result().__dict__ if scheduler.get_last_result() else None,
        }

    @app.get("/internal/environment/pm25/status")
    def internal_environment_pm25_status() -> Dict[str, Any]:
        """Status of the shared PM2.5 live snapshot service."""
        return app.state.pm25_live_service.status()    
    # Register mobility traffic router
    app.include_router(traffic_router)
    # Register mobility transit router
    app.include_router(transit_router)
    # Register mobility roads router
    app.include_router(roads_router)
    # Register safety fire router
    app.include_router(fire_router)
    app.include_router(overview_router)

    # Start transit alerts scheduler in background thread
    import threading
    def _run_transit_alerts_scheduler():
        app.state.transit_alerts_scheduler.run()
    threading.Thread(target=_run_transit_alerts_scheduler, daemon=True, name="transit-alerts-scheduler").start()

    # Start weather forecast scheduler in background thread (NEA 24h forecast,
    # 4h interval by default; collects immediately at boot). The PM2.5 CatBoost
    # models genuinely require fresh wf_* forecast features; without this the
    # forecast store goes stale and /api/pollution/predict correctly refuses.
    def _run_weather_scheduler():
        app.state.weather_scheduler.run()
    threading.Thread(target=_run_weather_scheduler, daemon=True, name="weather-forecast-scheduler").start()

    return app


app = _build_app()
