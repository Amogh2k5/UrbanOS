"""Traffic data collection service for LTA Traffic Speed Bands v2.

Orchestrates the API client, zone mapping, and storage.
Provides a clean function for scheduled collection runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from backend.app.mobility.traffic.speed_bands_v2 import TrafficSpeedBandsV2ApiClient, TrafficSpeedBandsV2Snapshot
from backend.app.mobility.traffic.storage import TrafficObservationStore, TrafficObservation, snapshot_to_observations

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))


@dataclass
class CollectionResult:
    """Result of a single collection run."""
    timestamp: str
    records_received: int
    records_stored: int
    records_updated: int
    zones_mapped: int
    zones_unmapped: int
    errors: list[str]


class TrafficCollector:
    """Service for collecting and storing LTA Traffic Speed Bands v2 data."""

    def __init__(
        self,
        api_client: Optional[TrafficSpeedBandsV2ApiClient] = None,
        store: Optional[TrafficObservationStore] = None,
    ) -> None:
        self.api_client = api_client or TrafficSpeedBandsV2ApiClient()
        self.store = store or TrafficObservationStore()

    def collect_once(self) -> CollectionResult:
        """Perform one collection run: fetch, map zones, store.

        Returns:
            CollectionResult with counts and any errors.
        """
        errors: list[str] = []
        timestamp = datetime.now(SG_OFFSET).isoformat()

        try:
            snapshot: TrafficSpeedBandsV2Snapshot = self.api_client.fetch_all_pages()
        except Exception as e:
            error_msg = f"API fetch failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)
            return CollectionResult(
                timestamp=timestamp,
                records_received=0,
                records_stored=0,
                records_updated=0,
                zones_mapped=0,
                zones_unmapped=0,
                errors=errors,
            )

        records_received = len(snapshot.segments)

        # Convert to storage observations
        observations = snapshot_to_observations(snapshot)

        # Count zone mappings
        zones_mapped = sum(1 for o in observations if o.zone_id is not None)
        zones_unmapped = records_received - zones_mapped

        # Store observations
        try:
            inserted, updated = self.store.upsert_observations(observations)
            records_stored = inserted + updated
        except Exception as e:
            error_msg = f"Storage upsert failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)
            return CollectionResult(
                timestamp=timestamp,
                records_received=records_received,
                records_stored=0,
                records_updated=0,
                zones_mapped=zones_mapped,
                zones_unmapped=zones_unmapped,
                errors=errors,
            )

        log.info(
            "Collection complete: received=%d, stored=%d (inserted=%d, updated=%d), "
            "zones_mapped=%d, zones_unmapped=%d",
            records_received, records_stored, inserted, updated, zones_mapped, zones_unmapped
        )

        return CollectionResult(
            timestamp=timestamp,
            records_received=records_received,
            records_stored=records_stored,
            records_updated=updated,
            zones_mapped=zones_mapped,
            zones_unmapped=zones_unmapped,
            errors=errors,
        )


def collect_traffic_once() -> CollectionResult:
    """Convenience function for scheduled collection runs.

    Can be called directly by a scheduler (APScheduler, cron, etc.).
    """
    collector = TrafficCollector()
    return collector.collect_once()


def get_collection_stats() -> Dict[str, Any]:
    """Get storage statistics."""
    store = TrafficObservationStore()
    return store.get_stats()