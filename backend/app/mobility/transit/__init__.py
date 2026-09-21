"""Transit mobility module - First-class backend integration."""

from backend.app.mobility.transit.data import (
    # Models
    BusServiceResponse,
    BusRouteResponse,
    BusStopResponse,
    TrainAlertResponse,
    TransitStatusResponse,
    BusArrivalRequest,
    BusArrivalResponse,
    # Data classes
    StoredBusService,
    StoredBusRoute,
    StoredBusStop,
    StoredTrainAlert,
    # Collector
    TransitCollector,
    collect_transit_reference_once,
    collect_transit_alerts_once,
    collect_transit_all_once,
    get_transit_stats,
    TransitDataStore,
)
from backend.app.mobility.transit.scheduler import (
    TransitAlertsScheduler,
    TransitReferenceScheduler,
    run_alerts_scheduler,
    run_reference_scheduler,
)
from backend.app.mobility.transit.api import (
    BusServicesApiClient,
    BusRoutesApiClient,
    BusStopsApiClient,
    TrainServiceAlertsApiClient,
    TrafficSpeedBandsV2ApiClient,
    TrafficSpeedBandsV2Snapshot,
)

__all__ = [
    # Models
    "BusServiceResponse",
    "BusRouteResponse",
    "BusStopResponse",
    "TrainAlertResponse",
    "TransitStatusResponse",
    "BusArrivalRequest",
    "BusArrivalResponse",
    # Data classes
    "StoredBusService",
    "StoredBusRoute",
    "StoredBusStop",
    "StoredTrainAlert",
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
    # API clients
    "BusServicesApiClient",
    "BusRoutesApiClient",
    "BusStopsApiClient",
    "TrainServiceAlertsApiClient",
    "TrafficSpeedBandsV2ApiClient",
    "TrafficSpeedBandsV2Snapshot",
]