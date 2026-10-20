"""FastAPI routes for Singapore Housing Intelligence."""
from __future__ import annotations
import logging
import threading
import time
from fastapi import APIRouter, HTTPException, Query
from .agent import run_housing_agent
from .models import HousingReport, HousingForecast, ForecastPoint
from .forecasting import generate_forecast, load_model_metadata

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/planning/housing", tags=["planning-housing"])
_lock = threading.Lock()
_cache: dict = {"report": None, "expires_at": 0.0}
_forecast_cache: dict = {"forecast": None, "expires_at": 0.0}

def get_housing_report(refresh: bool = False) -> HousingReport:
    now = time.time()
    with _lock:
        report = _cache["report"]
        if report is not None and not refresh and now < _cache["expires_at"]:
            return report
        try:
            report = run_housing_agent()
        except Exception as exc:
            log.exception("Housing report generation failed")
            raise HTTPException(status_code=502, detail=f"Housing data unavailable: {exc}") from exc
        _cache["report"] = report
        # Annual/quarterly sources don't need aggressive polling. Retry sooner for partial reports.
        _cache["expires_at"] = now + (300 if report.status == "UNAVAILABLE" else 1800)
        return report

def _to_housing_forecast(report) -> HousingForecast:
    """Convert ForecastReport dataclass to HousingForecast Pydantic model."""
    return HousingForecast(
        generated_at=report.generated_at,
        domain=report.domain if hasattr(report, 'domain') else "planning",
        subdomain=report.subdomain if hasattr(report, 'subdomain') else "housing",
        target_period=report.target_quarter,
        forecast_horizon="1_quarter",
        forecasts=[
            ForecastPoint(
                town=fp.town,
                flat_type=fp.flat_type,
                forecast_period=fp.forecast_period,
                predicted_price=fp.predicted_price,
                unit=fp.unit,
                method=fp.method,
                baseline_comparison=fp.baseline_comparison,
            )
            for fp in report.forecasts
        ],
        method=report.method_used,
        evaluation=report.evaluation,
        model_version=report.model_version,
        data_freshness=report.data_freshness,
        limitations=report.limitations,
        is_ml_prediction=False,
    )


def get_housing_forecast(refresh: bool = False, target_period: str | None = None) -> HousingForecast:
    """Get or generate housing resale price forecast."""
    now = time.time()
    with _lock:
        if _forecast_cache["forecast"] is not None and not refresh and now < _forecast_cache["expires_at"]:
            # Check if target period matches
            if target_period is None or _forecast_cache["forecast"].target_period == target_period:
                return _forecast_cache["forecast"]
        try:
            forecast_report = generate_forecast(target_period)
        except Exception as exc:
            log.exception("Housing forecast generation failed")
            raise HTTPException(status_code=502, detail=f"Housing forecast unavailable: {exc}") from exc
        forecast = _to_housing_forecast(forecast_report)
        _forecast_cache["forecast"] = forecast
        _forecast_cache["expires_at"] = now + 1800  # 30 min TTL
        return forecast

@router.get("/report")
def housing_report(refresh: bool = Query(False)):
    return get_housing_report(refresh).model_dump(mode="json")

@router.get("/forecast")
def housing_forecast(
    refresh: bool = Query(False),
    target_period: str | None = Query(None, description="Target quarter in format YYYY-QN, e.g., 2026-Q3"),
):
    """Get next-quarter HDB resale price forecast by town and flat type.

    Returns median resale price forecasts (SGD) for each town/flat-type combination
    with sufficient historical data. Uses statistical baseline (persistence/seasonal)
    with walk-forward evaluation metrics.
    """
    forecast = get_housing_forecast(refresh, target_period)
    return forecast.model_dump(mode="json")

@router.get("/sources")
def housing_sources(refresh: bool = Query(False)):
    report = get_housing_report(refresh)
    return {"generated_at": report.generated_at, "sources": [s.model_dump(mode="json") for s in report.sources],
            "errors": report.errors, "warnings": report.warnings, "limitations": report.limitations}

@router.get("/model")
def housing_model():
    """Get forecasting model metadata and evaluation results."""
    try:
        metadata = load_model_metadata()
        return metadata
    except Exception as exc:
        log.exception("Failed to load model metadata")
        raise HTTPException(status_code=500, detail=f"Model metadata unavailable: {exc}") from exc


def start_housing_warmup() -> None:
    """Trigger one housing report build in a background thread at startup.

    Annual/quarterly housing sources are slow enough that a warm cache avoids
    the first dashboard request paying the full fetch latency. Fails silently;
    the accessor re-runs on demand.
    """
    def _run():
        try:
            get_housing_report(refresh=True)
        except Exception as exc:
            log.warning("Housing warmup failed (non-fatal): %s", exc)
    threading.Thread(target=_run, daemon=True, name="housing-warmup").start()
