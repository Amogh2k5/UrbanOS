"""Weather forecast data collection service for NEA 24-hour Weather Forecast.

Orchestrates the API client, normalization, and storage.
Provides a clean function for scheduled collection runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from backend.app.environment.weather.api import WeatherApiClient, WeatherLiveSnapshot
from backend.app.environment.weather.storage import (
    WeatherForecastStore,
    WeatherNationalForecast,
    WeatherPeriodForecast,
    live_snapshot_to_national_forecasts,
    live_snapshot_to_period_forecasts,
)

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))


@dataclass
class WeatherCollectionResult:
    """Result of a single collection run."""
    timestamp: str
    national_forecasts_received: int
    national_forecasts_stored: int
    national_forecasts_updated: int
    period_forecasts_received: int
    period_forecasts_stored: int
    period_forecasts_updated: int
    errors: List[str]


class WeatherForecastCollector:
    """Service for collecting and storing NEA 24h weather forecasts."""

    def __init__(
        self,
        api_client: Optional[WeatherApiClient] = None,
        store: Optional[WeatherForecastStore] = None,
    ) -> None:
        self.api_client = api_client or WeatherApiClient()
        self.store = store or WeatherForecastStore()

    def collect_once(self) -> WeatherCollectionResult:
        """Perform one collection run: fetch, normalize, store.

        Returns:
            WeatherCollectionResult with counts and any errors.
        """
        errors: List[str] = []
        timestamp = datetime.now(SG_OFFSET).isoformat()

        try:
            snapshot: WeatherLiveSnapshot = self.api_client.fetch()
        except Exception as e:
            error_msg = f"API fetch failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)
            return WeatherCollectionResult(
                timestamp=timestamp,
                national_forecasts_received=0,
                national_forecasts_stored=0,
                national_forecasts_updated=0,
                period_forecasts_received=0,
                period_forecasts_stored=0,
                period_forecasts_updated=0,
                errors=errors,
            )

        # Convert to storage objects
        created_at = timestamp
        national_fcs = live_snapshot_to_national_forecasts(snapshot, created_at)
        period_fcs = live_snapshot_to_period_forecasts(snapshot, created_at)

        national_received = len(national_fcs)
        period_received = len(period_fcs)

        # Store national forecasts
        national_stored = 0
        national_updated = 0
        try:
            inserted, updated = self.store.upsert_national_forecasts(national_fcs)
            national_stored = inserted + updated
            national_updated = updated
        except Exception as e:
            error_msg = f"National forecast storage upsert failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)

        # Store period forecasts
        period_stored = 0
        period_updated = 0
        try:
            inserted, updated = self.store.upsert_period_forecasts(period_fcs)
            period_stored = inserted + updated
            period_updated = updated
        except Exception as e:
            error_msg = f"Period forecast storage upsert failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)

        log.info(
            "Weather collection complete: national received=%d, stored=%d (inserted=%d, updated=%d), "
            "period received=%d, stored=%d (inserted=%d, updated=%d)",
            national_received, national_stored, national_stored - national_updated, national_updated,
            period_received, period_stored, period_stored - period_updated, period_updated
        )

        return WeatherCollectionResult(
            timestamp=timestamp,
            national_forecasts_received=national_received,
            national_forecasts_stored=national_stored,
            national_forecasts_updated=national_updated,
            period_forecasts_received=period_received,
            period_forecasts_stored=period_stored,
            period_forecasts_updated=period_updated,
            errors=errors,
        )


def collect_weather_once() -> WeatherCollectionResult:
    """Convenience function for scheduled collection runs.

    Can be called directly by a scheduler (APScheduler, cron, etc.).
    """
    collector = WeatherForecastCollector()
    return collector.collect_once()


def get_weather_collection_stats() -> Dict[str, Any]:
    """Get weather forecast storage statistics."""
    store = WeatherForecastStore()
    return store.get_stats()