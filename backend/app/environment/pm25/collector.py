"""PM2.5 data collection service for NEA PM2.5 real-time API.

Orchestrates the API client, normalization, and storage.
Provides a clean function for scheduled collection runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from backend.app.environment.pm25.api import Pm25ApiClient, Pm25LiveSnapshot
from backend.app.environment.pm25.storage import (
    Pm25ObservationStore,
    Pm25Observation,
    live_snapshot_to_observations,
)

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))


@dataclass
class Pm25CollectionResult:
    """Result of a single collection run."""
    timestamp: str
    records_received: int
    records_stored: int
    records_updated: int
    regions_received: List[str]
    api_failed: bool
    errors: List[str]


class Pm25Collector:
    """Service for collecting and storing NEA PM2.5 observations."""

    def __init__(
        self,
        api_client: Optional[Pm25ApiClient] = None,
        store: Optional[Pm25ObservationStore] = None,
    ) -> None:
        self.api_client = api_client or Pm25ApiClient()
        self.store = store or Pm25ObservationStore()

    def collect_once(self) -> Pm25CollectionResult:
        """Perform one collection run: fetch, normalize, store.

        Returns:
            Pm25CollectionResult with counts and any errors.
        """
        errors: List[str] = []
        timestamp = datetime.now(SG_OFFSET).isoformat()
        api_failed = False

        try:
            # Force live mode for production collection
            snapshot: Pm25LiveSnapshot = self.api_client.fetch()
        except Exception as e:
            error_msg = f"API fetch failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)
            api_failed = True
            return Pm25CollectionResult(
                timestamp=timestamp,
                records_received=0,
                records_stored=0,
                records_updated=0,
                regions_received=[],
                api_failed=True,
                errors=errors,
            )

        if not snapshot.is_live:
            error_msg = "API returned fixture data instead of live data; not storing fixture in production database"
            log.warning(error_msg)
            errors.append(error_msg)
            api_failed = True
            return Pm25CollectionResult(
                timestamp=timestamp,
                records_received=0,
                records_stored=0,
                records_updated=0,
                regions_received=[],
                api_failed=True,
                errors=errors,
            )

        # Validate we have all 5 regions
        regions = list(snapshot.regions.keys())
        expected_regions = {"north", "south", "east", "west", "central"}
        missing = expected_regions - set(regions)
        if missing:
            error_msg = f"Missing regions in API response: {missing}"
            log.error(error_msg)
            errors.append(error_msg)
            # Still store what we have, but flag it
            # Note: This is a data quality check, not a hard failure

        # Convert to storage objects
        created_at = timestamp
        observations = live_snapshot_to_observations(snapshot, created_at)
        records_received = len(observations)

        # Store observations
        records_stored = 0
        records_updated = 0
        try:
            inserted, updated = self.store.upsert_observations(observations)
            records_stored = inserted + updated
            records_updated = updated
        except Exception as e:
            error_msg = f"Storage upsert failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)
            return Pm25CollectionResult(
                timestamp=timestamp,
                records_received=records_received,
                records_stored=0,
                records_updated=0,
                regions_received=regions,
                api_failed=api_failed,
                errors=errors,
            )

        log.info(
            "PM2.5 collection complete: received=%d, stored=%d (inserted=%d, updated=%d), "
            "regions=%s, api_failed=%s",
            records_received, records_stored, records_stored - records_updated, records_updated,
            regions, api_failed
        )

        return Pm25CollectionResult(
            timestamp=timestamp,
            records_received=records_received,
            records_stored=records_stored,
            records_updated=records_updated,
            regions_received=regions,
            api_failed=api_failed,
            errors=errors,
        )


def collect_pm25_once(
    api_client: Optional[Pm25ApiClient] = None,
    store: Optional[Pm25ObservationStore] = None,
) -> Pm25CollectionResult:
    """Convenience function for scheduled collection runs.

    Can be called directly by a scheduler (APScheduler, cron, etc.).
    """
    collector = Pm25Collector(api_client=api_client, store=store)
    return collector.collect_once()


def get_pm25_collection_stats() -> Dict[str, Any]:
    """Get PM2.5 observation storage statistics."""
    store = Pm25ObservationStore()
    return store.get_stats()