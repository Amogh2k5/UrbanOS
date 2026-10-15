"""Tests for the PM2.5 ML prediction endpoint."""

import os
import sys
import tempfile
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Force offline mode for tests
os.environ["URBANOS_API_OFFLINE"] = "1"

# IMPORTANT: Patch weather storage BEFORE importing main
# This ensures the app uses our temporary database
_temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_TEMP_DB_PATH = Path(_temp_db.name)
_temp_db.close()

import backend.app.environment.weather.data as ws
from backend.app.environment.weather.data import WeatherForecastStore, WeatherForecastCollector
_original_collector_init = WeatherForecastCollector.__init__

def _patched_collector_init(self, api_client=None, store=None):
    if store is None:
        store = WeatherForecastStore(_TEMP_DB_PATH)
    _original_collector_init(self, api_client=api_client, store=store)

WeatherForecastCollector.__init__ = _patched_collector_init

# Now import main (which will use our patched database path)
import backend.app.main
from backend.app.main import _build_app

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Model-selection ground truth
# ---------------------------------------------------------------------------
# These expectations used to hardcode the Phase 1 experiment selection
# (north/west -> persistence, south mean -> persistence). Production was
# upgraded in commit d5f524f so that every region/target selects catboost.
# Rather than re-hardcode the new values - which would go stale at the next
# retrain - the tests below are derived from the production registry that the
# endpoint is supposed to serve. If the endpoint ever stops reflecting
# selections.csv, these tests fail again.

_SELECTIONS_CSV = (
    Path(backend.app.main.__file__).resolve().parents[2]
    / "ml" / "pm25" / "models" / "production" / "selections.csv"
)


def _expected_selection():
    """{(region, target): selected_model} from the production registry."""
    import csv
    out = {}
    with open(_SELECTIONS_CSV, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[(row["region"], row["target"])] = row["selected_model"]
    return out


SELECTION = _expected_selection()


def test_production_selection_registry_is_readable():
    """Guard: 5 regions x 2 targets, and every entry must be a known model."""
    assert len(SELECTION) == 10, sorted(SELECTION)
    assert set(SELECTION.values()) <= {"catboost", "bl_persist"}


@pytest.fixture
def client():
    # Ensure clean weather DB before each test
    store = WeatherForecastStore(_TEMP_DB_PATH)
    with store._conn() as conn:
        conn.execute("DELETE FROM weather_national_forecast")
        conn.execute("DELETE FROM weather_period_forecast")
        conn.commit()
    app = _build_app()
    yield TestClient(app)
    
    # Clean up: clear the database between tests
    store = WeatherForecastStore(_TEMP_DB_PATH)
    with store._conn() as conn:
        conn.execute("DELETE FROM weather_national_forecast")
        conn.execute("DELETE FROM weather_period_forecast")
        conn.commit()

# Final cleanup
def pytest_sessionfinish(session, exitstatus):
    try:
        os.unlink(_TEMP_DB_PATH)
    except:
        pass


def test_pm25_prediction_endpoint_exists(client):
    """Test that the PM2.5 prediction endpoint exists and returns 200 for valid historical t0."""
    # Use a known date from the historical data (within weather coverage)
    response = client.get("/api/pollution/predict", params={"t0": "2024-12-30T23:00:00+08:00"})
    assert response.status_code == 200


def test_pm25_prediction_auto_t0_returns_503_on_no_collected_weather(client):
    """Test that auto-determination of t0 returns 503 when no weather data has been collected."""
    # Ensure the app's weather store reports no forecast
    client.app.state.weather_store.get_latest_forecast_timestamp = lambda: None
    response = client.get("/api/pollution/predict")
    assert response.status_code == 503
    data = response.json()
    assert "detail" in data
    assert data["detail"]["error"] == "Prediction unavailable: no weather forecast data collected"
    assert "staleness_threshold_days" in data["detail"]
    assert data["detail"]["staleness_threshold_days"] == 7


def test_pm25_prediction_structure(client):
    """Test that the prediction response has the correct structure."""
    # Use a known date from the historical data (within weather coverage)
    response = client.get("/api/pollution/predict", params={"t0": "2024-12-30T23:00:00+08:00"})
    data = response.json()
    
    # Top-level fields
    assert "prediction_timestamp" in data
    assert "prediction_horizon_hours" in data
    assert "target_window" in data
    assert "regions" in data
    assert "model_metadata" in data
    assert "diagnostics" in data
    assert "source" in data
    
    # Prediction horizon
    assert data["prediction_horizon_hours"] == 24
    
    # Target window
    assert "start" in data["target_window"]
    assert "end" in data["target_window"]
    
    # Model metadata
    assert data["model_metadata"]["run_id"] == "phase1_v1"
    assert "selected_regions_ml" in data["model_metadata"]
    assert "selected_regions_persist" in data["model_metadata"]
    assert "selection_policy" in data["model_metadata"]
    
    # Source
    assert "UrbanOS PM2.5 ML" in data["source"]


def test_pm25_prediction_regions(client):
    """Test that all 5 regions are present with correct fields."""
    response = client.get("/api/pollution/predict", params={"t0": "2024-12-30T23:00:00+08:00"})
    data = response.json()
    
    regions = data["regions"]
    assert len(regions) == 5
    
    expected_regions = {"north", "south", "east", "west", "central"}
    actual_regions = {r["region"] for r in regions}
    assert actual_regions == expected_regions
    
    for region in regions:
        # Required fields per region
        assert "region" in region
        assert "available" in region
        assert "unavailable_reason" in region
        assert "next_day_mean_ugm3" in region
        assert "next_day_max_ugm3" in region
        assert "model" in region
        assert "is_ml_model" in region
        assert "target_models" in region
        assert "persistence_value_pm25_t0" in region
        assert "fallback_reason" in region
        
        # Model should be either catboost or bl_persist
        assert region["model"] in ("catboost", "bl_persist")
        
        # Target models should have both keys
        assert "pm25_next_day_mean" in region["target_models"]
        assert "pm25_next_day_max" in region["target_models"]


def test_pm25_prediction_ml_regions(client):
    """Test that east and central use CatBoost (ML) for both targets, south uses catboost for max only."""
    response = client.get("/api/pollution/predict", params={"t0": "2024-12-30T23:00:00+08:00"})
    data = response.json()
    
    regions = {r["region"]: r for r in data["regions"]}

    # Every region must reflect the production selections.csv exactly.
    assert set(regions) == {region for region, _ in SELECTION}
    for region_name, r in regions.items():
        for target in ("pm25_next_day_mean", "pm25_next_day_max"):
            assert r["target_models"][target] == SELECTION[(region_name, target)], \
                f"{region_name}/{target}"

        # is_ml_model / model are driven by the primary target (mean).
        primary = SELECTION[(region_name, "pm25_next_day_mean")]
        assert r["model"] == primary, region_name
        assert r["is_ml_model"] is (primary != "bl_persist"), region_name

        # A persistence fallback must carry its persistence input.
        if primary == "bl_persist":
            assert r["persistence_value_pm25_t0"] is not None, region_name


def test_pm25_prediction_with_explicit_t0(client):
    """Test that the endpoint accepts an explicit t0 parameter."""
    # Use a known date from the historical data
    response = client.get("/api/pollution/predict", params={"t0": "2024-12-30T23:00:00+08:00"})
    assert response.status_code == 200
    data = response.json()
    assert "prediction_timestamp" in data
    assert len(data["regions"]) == 5


def test_pm25_prediction_invalid_t0(client):
    """Test that invalid t0 format returns 400."""
    response = client.get("/api/pollution/predict", params={"t0": "invalid-date"})
    assert response.status_code == 400
    assert "Invalid t0 format" in response.json()["detail"]


def test_pm25_prediction_diagnostics(client):
    """Test that diagnostics are included."""
    response = client.get("/api/pollution/predict", params={"t0": "2024-12-30T23:00:00+08:00"})
    data = response.json()
    
    diag = data["diagnostics"]
    assert "predictions_total" in diag
    assert "predictions_ml" in diag
    assert "predictions_persist" in diag
    assert "regions_missing_features" in diag
    assert "feature_report_rows" in diag
    
    # Counts must match the production registry rather than a hardcoded split.
    assert diag["predictions_total"] == len(SELECTION)
    expected_ml = sum(1 for m in SELECTION.values() if m != "bl_persist")
    assert diag["predictions_ml"] == expected_ml
    assert diag["predictions_persist"] == len(SELECTION) - expected_ml


def test_pm25_prediction_no_internal_paths(client):
    """Test that response doesn't expose internal file paths or secrets."""
    response = client.get("/api/pollution/predict", params={"t0": "2024-12-30T23:00:00+08:00"})
    data = response.json()
    
    # Convert to string and check for sensitive paths
    response_str = str(data).lower()
    
    # Should not contain internal paths
    assert "c:\\" not in response_str
    assert "/ml/datasets/processed" not in response_str
    assert "phase1_v1" in response_str  # run_id is OK
    
    # Should not contain API keys
    assert "lta_api_key" not in response_str
    assert "nea_api_key" not in response_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])