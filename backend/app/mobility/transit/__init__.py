"""Transit mobility module - First-class backend integration."""

from backend.app.mobility.transit.models import (
    BusServiceResponse,
    BusRouteResponse,
    BusStopResponse,
    TrainAlertResponse,
    TransitStatusResponse,
)
from backend.app.mobility.transit.collector import (
    TransitCollector,
    collect_transit_reference_once,
    collect_transit_alerts_once,
    collect_transit_all_once,
    get_transit_stats,
)
from backend.app.mobility.transit.storage import TransitDataStore
from backend.app.mobility.transit.scheduler import (
    TransitAlertsScheduler,
    TransitReferenceScheduler,
    run_alerts_scheduler,
    run_reference_scheduler,
)

__all__ = [
    # Models
    "BusServiceResponse",
    "BusRouteResponse",
    "BusStopResponse",
    "TrainAlertResponse",
    "TransitStatusResponse",
    # Collector
    "TransitCollector",
    "collect_transit_reference_once",
    "collect_transit_alerts_once",
    "collect_transit_all_once",
    "get_transit_stats",
    # Storage
    "TransitDataStore",
    # Scheduler
    "TransitAlertsScheduler",
    "TransitReferenceScheduler",
    "run_alerts_scheduler",
    "run_reference_scheduler",
]