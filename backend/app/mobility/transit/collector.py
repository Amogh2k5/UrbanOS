"""Transit data collection service for LTA Bus Services, Routes, Stops, and Train Alerts.

Orchestrates the API clients and storage.
Provides a clean function for scheduled collection runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from backend.app.mobility.transit.api_bus import (
    BusServicesApiClient,
    BusRoutesApiClient,
    BusStopsApiClient,
    BusServicesSnapshot,
    BusRoutesSnapshot,
    BusStopsSnapshot,
)
from backend.app.mobility.transit.api_train import (
    TrainServiceAlertsApiClient,
    TrainServiceAlertsSnapshot,
)
from backend.app.mobility.transit.storage import (
    TransitDataStore,
    StoredBusService,
    StoredBusRoute,
    StoredBusStop,
    StoredTrainAlert,
    bus_services_snapshot_to_stored,
    bus_routes_snapshot_to_stored,
    bus_stops_snapshot_to_stored,
    train_alerts_snapshot_to_stored,
)

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))


@dataclass
class TransitCollectionResult:
    """Result of a single transit collection run."""
    timestamp: str
    bus_services_received: int
    bus_services_stored: int
    bus_routes_received: int
    bus_routes_stored: int
    bus_stops_received: int
    bus_stops_stored: int
    train_alerts_received: int
    train_alerts_stored: int
    errors: list[str]


class TransitCollector:
    """Service for collecting and storing LTA transit data."""

    def __init__(
        self,
        bus_services_client: Optional[BusServicesApiClient] = None,
        bus_routes_client: Optional[BusRoutesApiClient] = None,
        bus_stops_client: Optional[BusStopsApiClient] = None,
        train_alerts_client: Optional[TrainServiceAlertsApiClient] = None,
        store: Optional[TransitDataStore] = None,
    ) -> None:
        self.bus_services_client = bus_services_client or BusServicesApiClient()
        self.bus_routes_client = bus_routes_client or BusRoutesApiClient()
        self.bus_stops_client = bus_stops_client or BusStopsApiClient()
        self.train_alerts_client = train_alerts_client or TrainServiceAlertsApiClient()
        self.store = store or TransitDataStore()

    def collect_reference_data(self) -> TransitCollectionResult:
        """Collect static reference data (bus services, routes, stops)."""
        errors: list[str] = []
        timestamp = datetime.now(SG_OFFSET).isoformat()

        # Bus Services
        bus_services_received = 0
        bus_services_stored = 0
        try:
            snapshot: BusServicesSnapshot = self.bus_services_client.fetch()
            bus_services_received = len(snapshot.services)
            stored = bus_services_snapshot_to_stored(snapshot)
            inserted, updated = self.store.upsert_bus_services(stored)
            bus_services_stored = inserted + updated
        except Exception as e:
            error_msg = f"Bus Services collection failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)

        # Bus Routes
        bus_routes_received = 0
        bus_routes_stored = 0
        try:
            snapshot: BusRoutesSnapshot = self.bus_routes_client.fetch()
            bus_routes_received = len(snapshot.routes)
            stored = bus_routes_snapshot_to_stored(snapshot)
            inserted, updated = self.store.upsert_bus_routes(stored)
            bus_routes_stored = inserted + updated
        except Exception as e:
            error_msg = f"Bus Routes collection failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)

        # Bus Stops
        bus_stops_received = 0
        bus_stops_stored = 0
        try:
            snapshot: BusStopsSnapshot = self.bus_stops_client.fetch()
            bus_stops_received = len(snapshot.stops)
            stored = bus_stops_snapshot_to_stored(snapshot)
            inserted, updated = self.store.upsert_bus_stops(stored)
            bus_stops_stored = inserted + updated
        except Exception as e:
            error_msg = f"Bus Stops collection failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)

        log.info(
            "Reference collection complete: services=%d, routes=%d, stops=%d",
            bus_services_stored, bus_routes_stored, bus_stops_stored
        )

        return TransitCollectionResult(
            timestamp=timestamp,
            bus_services_received=bus_services_received,
            bus_services_stored=bus_services_stored,
            bus_routes_received=bus_routes_received,
            bus_routes_stored=bus_routes_stored,
            bus_stops_received=bus_stops_received,
            bus_stops_stored=bus_stops_stored,
            train_alerts_received=0,
            train_alerts_stored=0,
            errors=errors,
        )

    def collect_train_alerts(self) -> TransitCollectionResult:
        """Collect train service alerts (real-time)."""
        errors: list[str] = []
        timestamp = datetime.now(SG_OFFSET).isoformat()

        train_alerts_received = 0
        train_alerts_stored = 0
        try:
            snapshot: TrainServiceAlertsSnapshot = self.train_alerts_client.fetch()
            train_alerts_received = len(snapshot.alerts)
            if train_alerts_received > 0:
                stored = train_alerts_snapshot_to_stored(snapshot)
                inserted = self.store.insert_train_alerts(stored)
                train_alerts_stored = inserted
        except Exception as e:
            error_msg = f"Train Alerts collection failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)

        log.info(
            "Train alerts collection complete: received=%d, stored=%d",
            train_alerts_received, train_alerts_stored
        )

        return TransitCollectionResult(
            timestamp=timestamp,
            bus_services_received=0,
            bus_services_stored=0,
            bus_routes_received=0,
            bus_routes_stored=0,
            bus_stops_received=0,
            bus_stops_stored=0,
            train_alerts_received=train_alerts_received,
            train_alerts_stored=train_alerts_stored,
            errors=errors,
        )

    def collect_all(self) -> TransitCollectionResult:
        """Collect all transit data (reference + alerts)."""
        ref_result = self.collect_reference_data()
        alert_result = self.collect_train_alerts()

        # Combine results
        return TransitCollectionResult(
            timestamp=ref_result.timestamp,
            bus_services_received=ref_result.bus_services_received,
            bus_services_stored=ref_result.bus_services_stored,
            bus_routes_received=ref_result.bus_routes_received,
            bus_routes_stored=ref_result.bus_routes_stored,
            bus_stops_received=ref_result.bus_stops_received,
            bus_stops_stored=ref_result.bus_stops_stored,
            train_alerts_received=alert_result.train_alerts_received,
            train_alerts_stored=alert_result.train_alerts_stored,
            errors=ref_result.errors + alert_result.errors,
        )


def collect_transit_reference_once() -> TransitCollectionResult:
    """Convenience function for scheduled reference data collection."""
    collector = TransitCollector()
    return collector.collect_reference_data()


def collect_transit_alerts_once() -> TransitCollectionResult:
    """Convenience function for scheduled train alerts collection."""
    collector = TransitCollector()
    return collector.collect_train_alerts()


def collect_transit_all_once() -> TransitCollectionResult:
    """Convenience function for full collection."""
    collector = TransitCollector()
    return collector.collect_all()


def get_transit_stats() -> Dict[str, Any]:
    """Get storage statistics."""
    store = TransitDataStore()
    return store.get_stats()