"""UrbanOS Environment domain module.

Produces the *environment* domain agent envelope (architecture proposal §2):
    PM2.5 ML artifacts + NEA 24h Weather Forecast -> Environment Situation Report.

Reuses the completed Phase 1 PM2.5 ML artifacts at
    ml/datasets/processed/phase1_pm25/runs/phase1_v1/
and the leakage-safe feature builders + ingesters from `ml.phase1_pm25.*`.
No ML training happens here. Persistence is a fallback baseline, not an ML model.
"""
from dotenv import load_dotenv
load_dotenv()

from backend.app.environment.environment_module import EnvironmentModule
from backend.app.environment.result import EnvironmentReport
from backend.app.environment.agent import EnvironmentAgent, build_agent
from backend.app.environment.weather.predictor import WeatherPredictor, WeatherPrediction
from backend.app.environment.pm25.api import Pm25ApiClient, Pm25LiveSnapshot
from backend.app.environment.weather.api import WeatherApiClient, WeatherLiveSnapshot

__all__ = [
    "EnvironmentModule",
    "EnvironmentReport",
    "EnvironmentAgent",
    "build_agent",
    "WeatherPredictor",
    "WeatherPrediction",
    "Pm25ApiClient",
    "Pm25LiveSnapshot",
    "WeatherApiClient",
    "WeatherLiveSnapshot",
]
