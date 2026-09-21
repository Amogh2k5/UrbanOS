"""Transit API router and LTA DataMall adapters."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.app.mobility.transit.data import (
    TransitCollector,
    collect_transit_reference_once,
    collect_transit_alerts_once,
    collect_transit_all_once,
    get_transit_stats,
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
_DEFAULT_BASE = "https://datamall2.mytransport.sg/ltaodataservice"
_TIMEOUT = 30.0
_PAGE_SIZE = 500

# ============================================================
# BUS SERVICES
# ============================================================

@dataclass
class BusService:
    """Bus service reference data."""
    service_no: str
    operator: str
    direction: int
    category: str
    origin_code: str
    destination_code: str
    am_peak_freq: Optional[str]
    am_offpeak_freq: Optional[str]
    pm_peak_freq: Optional[str]
    pm_offpeak_freq: Optional[str]
    loop_desc: Optional[str]
    source: str
    fetched_at: str


@dataclass
class BusServicesSnapshot:
    snapshot_at: str
    source: str
    provider: str
    endpoint: str
    services: List[BusService]
    is_live: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "is_live": self.is_live,
            "count": len(self.services),
            "services": [
                {
                    "service_no": s.service_no,
                    "operator": s.operator,
                    "direction": s.direction,
                    "category": s.category,
                    "origin_code": s.origin_code,
                    "destination_code": s.destination_code,
                    "am_peak_freq": s.am_peak_freq,
                    "am_offpeak_freq": s.am_offpeak_freq,
                    "pm_peak_freq": s.pm_peak_freq,
                    "pm_offpeak_freq": s.pm_offpeak_freq,
                    "loop_desc": s.loop_desc,
                }
                for s in self.services
            ],
        }


# ============================================================
# BUS ROUTES
# ============================================================

@dataclass
class BusRoute:
    """Bus route reference data (service + stop sequence)."""
    service_no: str
    operator: str
    direction: int
    stop_sequence: int
    bus_stop_code: str
    distance: Optional[float]
    wd_first_bus: Optional[str]
    wd_last_bus: Optional[str]
    sat_first_bus: Optional[str]
    sat_last_bus: Optional[str]
    sun_first_bus: Optional[str]
    sun_last_bus: Optional[str]
    source: str
    fetched_at: str


@dataclass
class BusRoutesSnapshot:
    snapshot_at: str
    source: str
    provider: str
    endpoint: str
    routes: List["BusRoute"]
    is_live: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "is_live": self.is_live,
            "count": len(self.routes),
            "routes": [
                {
                    "service_no": r.service_no,
                    "operator": r.operator,
                    "direction": r.direction,
                    "stop_sequence": r.stop_sequence,
                    "bus_stop_code": r.bus_stop_code,
                    "distance": r.distance,
                    "wd_first_bus": r.wd_first_bus,
                    "wd_last_bus": r.wd_last_bus,
                    "sat_first_bus": r.sat_first_bus,
                    "sat_last_bus": r.sat_last_bus,
                    "sun_first_bus": r.sun_first_bus,
                    "sun_last_bus": r.sun_last_bus,
                }
                for r in self.routes
            ],
        }


# ============================================================
# BUS STOPS
# ============================================================

@dataclass
class BusStop:
    """Bus stop reference data with location."""
    bus_stop_code: str
    road_name: str
    description: str
    latitude: float
    longitude: float
    source: str
    fetched_at: str


@dataclass
class BusStopsSnapshot:
    snapshot_at: str
    source: str
    provider: str
    endpoint: str
    stops: List["BusStop"]
    is_live: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "is_live": self.is_live,
            "count": len(self.stops),
            "stops": [
                {
                    "bus_stop_code": s.bus_stop_code,
                    "road_name": s.road_name,
                    "description": s.description,
                    "latitude": s.latitude,
                    "longitude": s.longitude,
                }
                for s in self.stops
            ],
        }


# ============================================================
# TRAIN SERVICE ALERTS
# ============================================================

@dataclass
class TrainServiceAlert:
    """Train service alert from LTA."""
    line: str
    direction: Optional[str]
    station: Optional[str]
    message: str
    status: Optional[str]
    source: str
    fetched_at: str


@dataclass
class TrainServiceAlertsSnapshot:
    snapshot_at: str
    source: str
    provider: str
    endpoint: str
    alerts: List["TrainServiceAlert"]
    is_live: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "is_live": self.is_live,
            "count": len(self.alerts),
            "alerts": [
                {
                    "line": a.line,
                    "direction": a.direction,
                    "station": a.station,
                    "message": a.message,
                    "status": a.status,
                }
                for a in self.alerts
            ],
        }


# ============================================================
# BASE CLIENT CLASS
# ============================================================

class _BaseLTAClient:
    """Base client for LTA DataMall APIs with pagination support."""

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE,
        api_key: Optional[str] = None,
        timeout: float = _TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.getenv("LTA_ACCOUNT_KEY")
        self.timeout = timeout

        if not self.api_key:
            raise ValueError("LTA_ACCOUNT_KEY not configured. Set the LTA_ACCOUNT_KEY environment variable.")

    def _fetch_all_pages(self, endpoint: str) -> List[dict]:
        """Fetch all pages from a paginated LTA endpoint."""
        headers = {"AccountKey": self.api_key, "accept": "application/json"}
        url = f"{self.base_url}{endpoint}"

        all_records: List[dict] = []
        skip = 0

        with httpx.Client(timeout=self.timeout) as client:
            while True:
                page_url = f"{url}?$skip={skip}&$top={_PAGE_SIZE}"
                log.debug("Fetching %s (skip=%d)", endpoint, skip)

                try:
                    with httpx.Client(timeout=self.timeout) as client:
                        resp = client.get(page_url, headers=headers)
                        resp.raise_for_status()
                        payload = resp.json()
                except httpx.TimeoutException as e:
                    log.error("%s fetch timeout: %s", endpoint, e)
                    raise
                except httpx.HTTPStatusError as e:
                    log.error("%s HTTP error: %s", endpoint, e)
                    raise
                except httpx.RequestError as e:
                    log.error("%s connection error: %s", endpoint, e)
                    raise
                except ValueError as e:
                    log.error("%s malformed response: %s", endpoint, e)
                    raise

                value = payload.get("value") or payload.get("Value") or []
                if not isinstance(value, list):
                    log.warning("Unexpected payload structure for %s", endpoint)
                    value = []

                all_records.extend(value)
                log.debug("Page skip=%d: %d records (total: %d)", skip, len(value), len(all_records))

                if len(value) < _PAGE_SIZE:
                    log.info("Final page reached for %s, total records: %d", endpoint, len(all_records))
                    break

                skip += _PAGE_SIZE

        return all_records

    def _now_iso(self) -> str:
        return datetime.now(SG_OFFSET).isoformat()


# ============================================================
# BUS SERVICES CLIENT
# ============================================================

class BusServicesApiClient(_BaseLTAClient):
    """Adapter for LTA BusServices endpoint."""

    _ENDPOINT = "/BusServices"

    def fetch(self) -> "BusServicesSnapshot":
        """Fetch all bus services (paginated)."""
        records = self._fetch_all_pages(self._ENDPOINT)
        services = self._normalize(records)
        return BusServicesSnapshot(
            snapshot_at=self._now_iso(),
            source="live_api:LTA_bus_services",
            provider="LTA DataMall",
            endpoint=f"{_DEFAULT_BASE}{self._ENDPOINT}",
            services=services,
            is_live=True,
        )

    def _normalize(self, records: List[dict]) -> List[BusService]:
        services: List[BusService] = []
        fetched_at = self._now_iso()

        for item in records:
            def _get(*keys):
                for k in keys:
                    v = item.get(k)
                    if v is not None:
                        return v
                return None

            services.append(BusService(
                service_no=str(_get("ServiceNo", "service_no") or ""),
                operator=_get("Operator", "operator") or "",
                direction=int(_get("Direction", "direction") or 0),
                category=_get("Category", "category") or "",
                origin_code=_get("OriginCode", "origin_code") or "",
                destination_code=_get("DestinationCode", "destination_code") or "",
                am_peak_freq=_get("AM_Peak_Freq", "am_peak_freq"),
                am_offpeak_freq=_get("AM_Offpeak_Freq", "am_offpeak_freq"),
                pm_peak_freq=_get("PM_Peak_Freq", "pm_peak_freq"),
                pm_offpeak_freq=_get("PM_Offpeak_Freq", "pm_offpeak_freq"),
                loop_desc=_get("LoopDesc", "loop_desc"),
                source="live_api:LTA_bus_services",
                fetched_at=fetched_at,
            ))

        return services


# ============================================================
# BUS ROUTES CLIENT
# ============================================================

class BusRoutesApiClient(_BaseLTAClient):
    """Adapter for LTA BusRoutes endpoint."""

    _ENDPOINT = "/BusRoutes"

    def fetch(self) -> "BusRoutesSnapshot":
        """Fetch all bus routes (paginated)."""
        records = self._fetch_all_pages(self._ENDPOINT)
        routes = self._normalize(records)
        return BusRoutesSnapshot(
            snapshot_at=self._now_iso(),
            source="live_api:LTA_bus_routes",
            provider="LTA DataMall",
            endpoint=f"{_DEFAULT_BASE}{self._ENDPOINT}",
            routes=routes,
            is_live=True,
        )

    def _normalize(self, records: List[dict]) -> List["BusRoute"]:
        routes: List["BusRoute"] = []
        fetched_at = self._now_iso()

        for item in records:
            def _get(*keys):
                for k in keys:
                    v = item.get(k)
                    if v is not None:
                        return v
                return None

            def _to_float(v):
                try:
                    return float(v) if v is not None else None
                except (TypeError, ValueError):
                    return None

            routes.append(BusRoute(
                service_no=str(_get("ServiceNo", "service_no") or ""),
                operator=_get("Operator", "operator") or "",
                direction=int(_get("Direction", "direction") or 0),
                stop_sequence=int(_get("StopSequence", "stop_sequence") or 0),
                bus_stop_code=str(_get("BusStopCode", "bus_stop_code") or ""),
                distance=_to_float(_get("Distance", "distance")),
                wd_first_bus=_get("WD_FirstBus", "wd_first_bus"),
                wd_last_bus=_get("WD_LastBus", "wd_last_bus"),
                sat_first_bus=_get("SAT_FirstBus", "sat_first_bus"),
                sat_last_bus=_get("SAT_LastBus", "sat_last_bus"),
                sun_first_bus=_get("SUN_FirstBus", "sun_first_bus"),
                sun_last_bus=_get("SUN_LastBus", "sun_last_bus"),
                source="live_api:LTA_bus_routes",
                fetched_at=fetched_at,
            ))

        return routes


# ============================================================
# BUS STOPS CLIENT
# ============================================================

class BusStopsApiClient(_BaseLTAClient):
    """Adapter for LTA BusStops endpoint."""

    _ENDPOINT = "/BusStops"

    def fetch(self) -> "BusStopsSnapshot":
        """Fetch all bus stops (paginated)."""
        records = self._fetch_all_pages(self._ENDPOINT)
        stops = self._normalize(records)
        return BusStopsSnapshot(
            snapshot_at=self._now_iso(),
            source="live_api:LTA_bus_stops",
            provider="LTA DataMall",
            endpoint=f"{_DEFAULT_BASE}{self._ENDPOINT}",
            stops=stops,
            is_live=True,
        )

    def _normalize(self, records: List[dict]) -> List["BusStop"]:
        stops: List["BusStop"] = []
        fetched_at = self._now_iso()

        for item in records:
            def _get(*keys):
                for k in keys:
                    v = item.get(k)
                    if v is not None:
                        return v
                return None

            def _to_float(v):
                try:
                    return float(v) if v is not None else None
                except (TypeError, ValueError):
                    return None

            lat = _to_float(_get("Latitude", "latitude"))
            lon = _to_float(_get("Longitude", "longitude"))

            # Skip stops without valid coordinates
            if lat is None or lon is None:
                continue

            stops.append(BusStop(
                bus_stop_code=str(_get("BusStopCode", "bus_stop_code") or ""),
                road_name=_get("RoadName", "road_name") or "",
                description=_get("Description", "description") or "",
                latitude=lat,
                longitude=lon,
                source="live_api:LTA_bus_stops",
                fetched_at=fetched_at,
            ))

        return stops


# ============================================================
# TRAIN SERVICE ALERTS CLIENT
# ============================================================

def _classify_alert_category(line: str, message: str, station: Optional[str]) -> str:
    """Classify alert as bus, metro, or rail based on content."""
    text = " ".join(filter(None, [line, message, station])).lower()
    text = "".join(c for c in text if c.isalnum() or c.isspace())

    # Bus-related keywords
    bus_keywords = [
        "busservice", "busroute", "busstop", "busdiversion",
        "bus service", "bus route", "bus stop", "bus diversion",
        "sbstransit", "smrtbus", "goahead", "towertransit"
    ]
    if any(kw in text for kw in bus_keywords):
        return "bus"

    # MRT/Metro line codes and names
    mrt_codes = ["nsl", "ewl", "nel", "ccl", "dtl", "tel"]
    mrt_names = [
        "northsouth", "eastwest", "northeast", "circleline", "downtownline",
        "thomsoneastcoast", "north-south", "east-west", "north-east",
        "circle", "downtown", "thomson-east coast"
    ]
    if any(code in text for code in mrt_codes) or any(name in text for name in mrt_names):
        return "metro"
    if "mrt" in text or "metro" in text:
        return "metro"

    # LRT/Rail
    lrt_codes = ["bplrt", "sklrt", "pglrt"]
    lrt_names = ["bukitpanjang", "sengkang", "punggol"]
    if any(code in text for code in lrt_codes) or any(name in text for name in lrt_names):
        return "rail"
    if "lrt" in text or "light rail" in text:
        return "rail"

    return "rail"


@dataclass
class TrainServiceAlert:
    """Train service alert from LTA."""
    line: str
    direction: Optional[str]
    station: Optional[str]
    message: str
    status: Optional[str]
    source: str
    fetched_at: str
    category: str = "rail"  # bus, metro, rail


@dataclass
class TrainServiceAlertsSnapshot:
    snapshot_at: str
    source: str
    provider: str
    endpoint: str
    alerts: List["TrainServiceAlert"]
    is_live: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "is_live": self.is_live,
            "count": len(self.alerts),
            "alerts": [
                {
                    "line": a.line,
                    "direction": a.direction,
                    "station": a.station,
                    "message": a.message,
                    "status": a.status,
                }
                for a in self.alerts
            ],
        }


class TrainServiceAlertsApiClient:
    """Adapter for LTA TrainServiceAlerts endpoint."""

    _ENDPOINT = "/TrainServiceAlerts"

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE,
        account_key: Optional[str] = None,
        offline: bool = False,
        allow_fallback_fixture: bool = True,
        timeout: float = _TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.account_key = account_key or os.getenv("LTA_ACCOUNT_KEY")
        self.offline = offline
        self.allow_fallback_fixture = allow_fallback_fixture
        self.timeout = timeout

    def fetch(self) -> "TrainServiceAlertsSnapshot":
        """Fetch latest train service alerts."""
        payload, is_live = self._get_payload()
        return self._normalize(payload, is_live=is_live)

    def _get_payload(self):
        if self.offline:
            log.info("Train Service Alerts adapter offline=True; using fallback fixture.")
            return {"value": []}, False

        if not self.account_key:
            log.warning("LTA_ACCOUNT_KEY not set; using fallback fixture.")
            if self.allow_fallback_fixture:
                return {"value": []}, False
            raise ValueError("LTA_ACCOUNT_KEY not configured")

        headers = {"AccountKey": self.account_key, "accept": "application/json"}
        url = f"{self.base_url}{self._ENDPOINT}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                return resp.json(), True
        except httpx.TimeoutException as e:
            log.warning("Train Service Alerts live fetch timeout: %s", e)
        except httpx.HTTPStatusError as e:
            log.warning("Train Service Alerts HTTP error: %s", e)
        except httpx.RequestError as e:
            log.warning("Train Service Alerts connection error: %s", e)
        except ValueError as e:
            log.warning("Train Service Alerts malformed response: %s", e)

        if self.allow_fallback_fixture:
            log.warning("Train Service Alerts falling back to deterministic fixture.")
            return {"value": []}, False
        raise

    def _normalize(self, payload: dict, is_live: bool) -> "TrainServiceAlertsSnapshot":
        value = payload.get("value") or payload.get("Value") or []
        alerts: List["TrainServiceAlert"] = []
        fetched_at = self._now_iso()

        # Handle two possible payload structures:
        # 1. value is a list of alert objects (legacy expectation)
        # 2. value is a dict with keys: Status, AffectedSegments, Message (current LTA format)
        if isinstance(value, list):
            items = value
        elif isinstance(value, dict):
            # Current LTA format: value = {Status, AffectedSegments, Message: [...]}
            messages = value.get("Message") or value.get("message") or []
            if isinstance(messages, list):
                items = messages
            else:
                log.warning("Unexpected Train Service Alerts payload: 'Message' not a list")
                items = []
            # Optionally capture top-level status
            top_status = value.get("Status") or value.get("status")
        else:
            log.warning("Unexpected payload structure for Train Service Alerts")
            items = []

        alerts: List["TrainServiceAlert"] = []
        fetched_at = self._now_iso()

        for item in items:
            def _get(*keys):
                for k in keys:
                    v = item.get(k)
                    if v is not None:
                        return v
                return None

            # In current format, each message has Content and CreatedDate
            content = _get("Content", "content", "Message", "message") or ""
            created = _get("CreatedDate", "created_date", "Created", "created")

            line = _get("Line", "line") or "UNKNOWN"
            direction = _get("Direction", "direction")
            station = _get("Station", "station")
            message = content
            status = _get("Status", "status") or top_status if 'top_status' in locals() else _get("Status", "status")

            # Classify alert category based on content
            category = _classify_alert_category(line, message, station)

            alerts.append(TrainServiceAlert(
                line=line,
                direction=direction,
                station=station,
                message=message,
                status=status,
                source=("live_api:LTA_train_alerts" if is_live else "offline_fixture:LTA_train_alerts"),
                fetched_at=fetched_at,
                category=category,
            ))

        return TrainServiceAlertsSnapshot(
            snapshot_at=self._now_iso(),
            source=("live_api:LTA_train_alerts" if is_live else "offline_fixture:LTA_train_alerts"),
            provider="LTA DataMall",
            endpoint=f"{_DEFAULT_BASE}{self._ENDPOINT}",
            alerts=alerts,
            is_live=is_live,
        )

    def _now_iso(self) -> str:
        return datetime.now(SG_OFFSET).isoformat()


# ============================================================
# TRAFFIC SPEED BANDS V2 (for reference data)
# ============================================================

@dataclass
class TrafficSpeedBandV2:
    """Single traffic speed band observation from LTA v2 API."""
    link_id: str
    road_name: str
    road_category: str
    speed_band: int
    minimum_speed: Optional[float]
    maximum_speed: Optional[float]
    start_latitude: Optional[float]
    start_longitude: Optional[float]
    end_latitude: Optional[float]
    end_longitude: Optional[float]
    speed_midpoint: float
    zone_id: Optional[str]
    zone_name: Optional[str]
    observed_at: str
    source: str = "live_api:LTA_traffic_speed_bands_v2"


@dataclass
class TrafficSpeedBandsV2Snapshot:
    """Complete snapshot of traffic speed bands at a point in time."""
    snapshot_at: str
    source: str
    provider: str
    endpoint: str
    segments: List[TrafficSpeedBandV2]
    is_live: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "is_live": self.is_live,
            "count": len(self.segments),
            "segments": [
                {
                    "link_id": s.link_id,
                    "road_name": s.road_name,
                    "road_category": s.road_category,
                    "speed_band": s.speed_band,
                    "minimum_speed": s.minimum_speed,
                    "maximum_speed": s.maximum_speed,
                    "speed_midpoint": s.speed_midpoint,
                    "coordinates": {
                        "start": {"lat": s.start_latitude, "lon": s.start_longitude}
                        if s.start_latitude is not None and s.start_longitude is not None
                        else None,
                        "end": {"lat": s.end_latitude, "lon": s.end_longitude}
                        if s.end_latitude is not None and s.end_longitude is not None
                        else None,
                    },
                    "zone_id": s.zone_id,
                    "zone_name": s.zone_name,
                    "observed_at": s.observed_at,
                }
                for s in self.segments
            ],
        }


class TrafficSpeedBandsV2ApiClient:
    """Adapter for LTA DataMall Traffic Speed Bands v2 endpoint.

    This client is designed for historical data ingestion (polling every ~5 min).
    It does NOT fall back to fixtures - it requires a valid LTA_API_KEY.
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE,
        api_key: Optional[str] = None,
        timeout: float = _TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.getenv("LTA_API_KEY")
        self.timeout = timeout

        if not self.api_key:
            raise ValueError(
                "LTA_API_KEY not configured. Set the LTA_API_KEY environment variable."
            )

    def fetch(self) -> "TrafficSpeedBandsV2Snapshot":
        """Fetch latest Traffic Speed Bands v2 snapshot from live API."""
        headers = {"AccountKey": self.api_key, "accept": "application/json"}
        url = f"{self.base_url}{_ENDPOINT}"

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.TimeoutException as e:
            log.error("Traffic Speed Bands v2 fetch timeout: %s", e)
            raise
        except httpx.HTTPStatusError as e:
            log.error("Traffic Speed Bands v2 HTTP error: %s", e)
            raise
        except httpx.RequestError as e:
            log.error("Traffic Speed Bands v2 connection error: %s", e)
            raise
        except ValueError as e:
            log.error("Traffic Speed Bands v2 malformed response: %s", e)
            raise

        return self._normalize(payload)

    def fetch_all_pages(self) -> "TrafficSpeedBandsV2Snapshot":
        """Fetch ALL Traffic Speed Bands pages (complete Singapore snapshot).

        Uses $top=500 and $skip pagination until a page returns < 500 records.
        All segments share the same snapshot timestamp.

        Returns:
            TrafficSpeedBandsV2Snapshot with all segments from all pages.

        Raises:
            httpx.TimeoutException: If any page request times out.
            httpx.HTTPStatusError: If any page returns an HTTP error.
            httpx.RequestError: If any page has a connection error.
            ValueError: If any page has a malformed response.
        """
        headers = {"AccountKey": self.api_key, "accept": "application/json"}
        url = f"{self.base_url}{_ENDPOINT}"

        snapshot_at = _now_iso()
        all_segments: List[TrafficSpeedBandV2] = []
        page = 0

        # Reuse a single HTTP client for all pages
        with httpx.Client(timeout=self.timeout) as client:
            while True:
                skip = page * _PAGE_SIZE
                url = f"{base_url}?$top={_PAGE_SIZE}&$skip={skip}"

                log.debug("Fetching page %d (skip=%d)", page, skip)

                try:
                    resp = client.get(url, headers=headers)
                    resp.raise_for_status()
                    payload = resp.json()
                except httpx.TimeoutException as e:
                    log.error("Traffic Speed Bands v2 page %d timeout: %s", page, e)
                    raise
                except httpx.HTTPStatusError as e:
                    log.error("Traffic Speed Bands v2 page %d HTTP error: %s", page, e)
                    raise
                except httpx.RequestError as e:
                    log.error("Traffic Speed Bands v2 page %d connection error: %s", page, e)
                    raise
                except ValueError as e:
                    log.error("Traffic Speed Bands v2 page %d malformed response: %s", page, e)
                    raise

                # Extract segments from this page
                value = payload.get("value") or payload.get("Value") or []
                if not isinstance(value, list):
                    log.warning("Unexpected payload structure on page %d", page)
                    value = []

                page_segments = self._normalize_page(value, snapshot_at)
                all_segments.extend(page_segments)

                log.debug("Page %d: %d segments (total: %d)", page, len(page_segments), len(all_segments))

                # Stop if this page has fewer than PAGE_SIZE records (last page)
                if len(value) < _PAGE_SIZE:
                    log.info("Final page %d reached (%d records), total segments: %d", page, len(value), len(all_segments))
                    break

                page += 1

        return TrafficSpeedBandsV2Snapshot(
            snapshot_at=snapshot_at,
            source="live_api:LTA_traffic_speed_bands_v2",
            provider="LTA DataMall",
            endpoint=f"{_DEFAULT_BASE}{_ENDPOINT}",
            segments=all_segments,
            is_live=True,
        )

    def _normalize_page(self, value: list, snapshot_at: str) -> List[TrafficSpeedBandV2]:
        """Normalize a single page of raw API items to TrafficSpeedBandV2 segments."""
        from backend.app.mobility.traffic.geo_zones import get_zone

        segments: List[TrafficSpeedBandV2] = []

        for item in value:
            def _get(item: dict, *keys):
                for k in keys:
                    v = item.get(k)
                    if v is not None:
                        return v
                return None

            link_id = str(_get(item, "LinkID", "link_id") or "")
            road_name = _get(item, "RoadName", "road_name") or ""
            road_category = _get(item, "RoadCategory", "road_category") or ""
            speed_band = _get(item, "SpeedBand", "speed_band")
            minimum_speed = _get(item, "MinimumSpeed", "minimum_speed")
            maximum_speed = _get(item, "MaximumSpeed", "maximum_speed")
            # v4 uses StartLon/StartLat/EndLon/EndLat (Lon/Lat order)
            start_lon = _get(item, "StartLon", "start_lon", "StartLongitude", "start_longitude")
            start_lat = _get(item, "StartLat", "start_lat", "StartLatitude", "start_latitude")
            end_lon = _get(item, "EndLon", "end_lon", "EndLongitude", "end_longitude")
            end_lat = _get(item, "EndLat", "end_lat", "EndLatitude", "end_latitude")

            try:
                speed_band = int(speed_band) if speed_band is not None else 0
            except (TypeError, ValueError):
                speed_band = 0

            def _to_float(v):
                try:
                    return float(v) if v is not None else None
                except (TypeError, ValueError):
                    return None

            min_speed = _to_float(minimum_speed)
            max_speed = _to_float(maximum_speed)
            start_lat_f = _to_float(start_lat)
            start_lon_f = _to_float(start_lon)
            end_lat_f = _to_float(end_lat)
            end_lon_f = _to_float(end_lon)

            # Calculate speed midpoint
            speed_midpoint = 0.0
            if min_speed is not None and max_speed is not None:
                speed_midpoint = (min_speed + max_speed) / 2.0

            # Zone mapping via midpoint
            zone_id = None
            zone_name = None
            if all(v is not None for v in [start_lat_f, start_lon_f, end_lat_f, end_lon_f]):
                mid_lat = (start_lat_f + end_lat_f) / 2.0
                mid_lon = (start_lon_f + end_lon_f) / 2.0
                zone_result = get_zone(mid_lat, mid_lon)
                zone_id = zone_result.get("zone_id")
                zone_name = zone_result.get("zone_name")

            segments.append(TrafficSpeedBandV2(
                link_id=link_id,
                road_name=road_name,
                road_category=road_category,
                speed_band=speed_band,
                minimum_speed=min_speed,
                maximum_speed=max_speed,
                start_latitude=start_lat_f,
                start_longitude=start_lon_f,
                end_latitude=end_lat_f,
                end_longitude=end_lon_f,
                speed_midpoint=speed_midpoint,
                zone_id=zone_id,
                zone_name=zone_name,
                observed_at=snapshot_at,
            ))

        return segments

    def _normalize(self, payload: dict) -> "TrafficSpeedBandsV2Snapshot":
        value = payload.get("value") or payload.get("Value") or []
        if not isinstance(value, list):
            log.warning("Unexpected payload structure for Traffic Speed Bands v2")
            value = []

        snapshot_at = _now_iso()
        segments = self._normalize_page(value, snapshot_at)

        return TrafficSpeedBandsV2Snapshot(
            snapshot_at=snapshot_at,
            source="live_api:LTA_traffic_speed_bands_v2",
            provider="LTA DataMall",
            endpoint=f"{_DEFAULT_BASE}{_ENDPOINT}",
            segments=segments,
            is_live=True,
        )


def _now_iso() -> str:
    return datetime.now(SG_OFFSET).isoformat()


# ============================================================
# FASTAPI ROUTER
# ============================================================

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from backend.app.mobility.transit.data import (
    TransitCollector,
    collect_transit_reference_once,
    collect_transit_alerts_once,
    collect_transit_all_once,
    get_transit_stats,
    TransitDataStore,
)
from backend.app.mobility.transit.data import (
    BusServiceResponse,
    BusRouteResponse,
    BusStopResponse,
    TrainAlertResponse,
    TransitStatusResponse,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mobility/transit", tags=["mobility", "transit"])


@router.get("/status", response_model=TransitStatusResponse)
async def get_transit_status(
    limit_alerts: int = Query(20, ge=1, le=100, description="Max train alerts to return")
) -> TransitStatusResponse:
    """Get overall transit system status with recent train alerts (metro/rail only)."""
    try:
        store = TransitDataStore()
        stats = store.get_stats()
        all_alerts = store.get_latest_train_alerts(limit=limit_alerts * 3)  # fetch more to filter
        # Filter to only metro/rail for train alerts (exclude bus)
        train_alerts = [a for a in all_alerts if a.category in ("metro", "rail")]
        train_alerts = train_alerts[:limit_alerts]
        # Count only metro/rail for active_train_alerts
        active_train_count = sum(1 for a in all_alerts if a.category in ("metro", "rail"))

        return TransitStatusResponse(
            generated_at=datetime.now(),
            bus_services_count=stats["bus_services"],
            bus_routes_count=stats["bus_routes"],
            bus_stops_count=stats["bus_stops"],
            active_train_alerts=active_train_count,
            train_alerts=[
                TrainAlertResponse(
                    line=a.line,
                    direction=a.direction,
                    station=a.station,
                    message=a.message,
                    status=a.status,
                    category=a.category,
                )
                for a in train_alerts
            ],
            limitations=[
                "Bus arrival predictions (BusArrivalv2) not available with current LTA account",
                "Taxi availability not available with current LTA account",
                "Reference data (services/routes/stops) updated daily",
                "Train alerts collected every 5 minutes",
            ],
        )
    except Exception as e:
        log.exception("Failed to get transit status")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bus-services", response_model=List[BusServiceResponse])
async def get_bus_services(
    limit: int = Query(100, ge=1, le=1000),
    service_no: Optional[str] = Query(None, description="Filter by service number"),
    operator: Optional[str] = Query(None, description="Filter by operator (SBST, SMRT, etc.)"),
) -> List[BusServiceResponse]:
    """Get bus services reference data."""
    try:
        store = TransitDataStore()
        if service_no and operator:
            svc = store.get_bus_service(service_no, operator, 1)
            if svc:
                return [_stored_to_response(svc)]
            return []
        elif service_no:
            # Search all directions
            results = []
            for direction in [1, 2]:
                for op in ["SBST", "SMRT", "TTS", "GAS"]:
                    svc = store.get_bus_service(service_no, op, direction)
                    if svc:
                        results.append(_stored_to_response(svc))
            return results[:limit]
        else:
            services = store.get_bus_services(limit=limit)
            if operator:
                services = [s for s in services if s.operator == operator]
            return [_stored_to_response(s) for s in services[:limit]]
    except Exception as e:
        log.exception("Failed to get bus services")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bus-routes", response_model=List[BusRouteResponse])
async def get_bus_routes(
    service_no: str = Query(..., description="Bus service number"),
    operator: str = Query(..., description="Operator (SBST, SMRT, etc.)"),
    direction: int = Query(..., ge=1, le=2, description="Direction (1 or 2)"),
) -> List[BusRouteResponse]:
    """Get bus route (stop sequence) for a specific service."""
    try:
        store = TransitDataStore()
        routes = store.get_bus_routes_for_service(service_no, operator, direction)
        return [
            BusRouteResponse(
                service_no=r.service_no,
                operator=r.operator,
                direction=r.direction,
                stop_sequence=r.stop_sequence,
                bus_stop_code=r.bus_stop_code,
                distance=r.distance,
                wd_first_bus=r.wd_first_bus,
                wd_last_bus=r.wd_last_bus,
                sat_first_bus=r.sat_first_bus,
                sat_last_bus=r.sat_last_bus,
                sun_first_bus=r.sun_first_bus,
                sun_last_bus=r.sun_last_bus,
            )
            for r in routes
        ]
    except Exception as e:
        log.exception("Failed to get bus routes")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bus-stops", response_model=List[BusStopResponse])
async def get_bus_stops(
    bus_stop_code: Optional[str] = Query(None, description="Specific bus stop code"),
    lat: Optional[float] = Query(None, description="Latitude for nearby search"),
    lon: Optional[float] = Query(None, description="Longitude for nearby search"),
    radius_km: float = Query(1.0, ge=0.1, le=10.0, description="Search radius in km"),
    limit: int = Query(50, ge=1, le=5000),
    all_stops: bool = Query(False, description="Return all bus stops (ignores lat/lon/radius)"),
) -> List[BusStopResponse]:
    """Get bus stop information."""
    try:
        store = TransitDataStore()

        if bus_stop_code:
            stop = store.get_bus_stop(bus_stop_code)
            if stop:
                return [_stored_stop_to_response(stop)]
            return []

        if all_stops:
            stops = store.get_all_bus_stops(limit=limit)
            return [_stored_stop_to_response(s) for s in stops]

        if lat is not None and lon is not None:
            stops = store.get_bus_stops_near(lat, lon, radius_km=radius_km, limit=limit)
            return [_stored_stop_to_response(s) for s in stops]

        raise HTTPException(status_code=400, detail="Provide either bus_stop_code, lat/lon, or all_stops=true")
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Failed to get bus stops")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/train-alerts", response_model=List[TrainAlertResponse])
async def get_train_alerts(
    line: Optional[str] = Query(None, description="Filter by MRT line (NSL, EWL, CCL, DTL, TEL, etc.)"),
    category: Optional[str] = Query(None, description="Filter by category: bus, metro, rail"),
    limit: int = Query(20, ge=1, le=100),
) -> List[TrainAlertResponse]:
    """Get train service alerts."""
    try:
        store = TransitDataStore()
        if line:
            alerts = store.get_train_alerts_for_line(line, limit=limit)
        else:
            alerts = store.get_latest_train_alerts(limit=limit)

        if category:
            alerts = [a for a in alerts if a.category == category]

        return [
            TrainAlertResponse(
                line=a.line,
                direction=a.direction,
                station=a.station,
                message=a.message,
                status=a.status,
                category=a.category,
            )
            for a in alerts
        ]
    except Exception as e:
        log.exception("Failed to get train alerts")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/collect/reference")
async def collect_reference_data() -> dict:
    """Trigger bus reference data collection (services, routes, stops)."""
    try:
        result = collect_transit_reference_once()
        return {
            "timestamp": result.timestamp,
            "bus_services_received": result.bus_services_received,
            "bus_services_stored": result.bus_services_stored,
            "bus_routes_received": result.bus_routes_received,
            "bus_routes_stored": result.bus_routes_stored,
            "bus_stops_received": result.bus_stops_received,
            "bus_stops_stored": result.bus_stops_stored,
            "errors": result.errors,
        }
    except Exception as e:
        log.exception("Transit reference collection failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/collect/alerts")
async def collect_train_alerts() -> dict:
    """Trigger train service alerts collection."""
    try:
        result = collect_transit_alerts_once()
        return {
            "timestamp": result.timestamp,
            "train_alerts_received": result.train_alerts_received,
            "train_alerts_stored": result.train_alerts_stored,
            "errors": result.errors,
        }
    except Exception as e:
        log.exception("Train alerts collection failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/collect/all")
async def collect_all_transit() -> dict:
    """Trigger full transit data collection."""
    try:
        result = collect_transit_all_once()
        return {
            "timestamp": result.timestamp,
            "bus_services_received": result.bus_services_received,
            "bus_services_stored": result.bus_services_stored,
            "bus_routes_received": result.bus_routes_received,
            "bus_routes_stored": result.bus_routes_stored,
            "bus_stops_received": result.bus_stops_received,
            "bus_stops_stored": result.bus_stops_stored,
            "train_alerts_received": result.train_alerts_received,
            "train_alerts_stored": result.train_alerts_stored,
            "errors": result.errors,
        }
    except Exception as e:
        log.exception("Transit collection failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_stats() -> dict:
    """Get transit storage statistics."""
    try:
        return get_transit_stats()
    except Exception as e:
        log.exception("Transit stats failed")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _stored_to_response(svc) -> BusServiceResponse:
    return BusServiceResponse(
        service_no=svc.service_no,
        operator=svc.operator,
        direction=svc.direction,
        category=svc.category,
        origin_code=svc.origin_code,
        destination_code=svc.destination_code,
        am_peak_freq=svc.am_peak_freq,
        am_offpeak_freq=svc.am_offpeak_freq,
        pm_peak_freq=svc.pm_peak_freq,
        pm_offpeak_freq=svc.pm_offpeak_freq,
        loop_desc=svc.loop_desc,
    )


def _stored_stop_to_response(stop) -> BusStopResponse:
    return BusStopResponse(
        bus_stop_code=stop.bus_stop_code,
        road_name=stop.road_name,
        description=stop.description,
        latitude=stop.latitude,
        longitude=stop.longitude,
    )


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "router",
    # Models
    "BusServiceResponse",
    "BusRouteResponse",
    "BusStopResponse",
    "TrainAlertResponse",
    "TransitStatusResponse",
    "BusArrivalRequest",
    "BusArrivalResponse",
    # API clients
    "BusServicesApiClient",
    "BusRoutesApiClient",
    "BusStopsApiClient",
    "TrainServiceAlertsApiClient",
    "TrafficSpeedBandsV2ApiClient",
    # Snapshots
    "BusServicesSnapshot",
    "BusRoutesSnapshot",
    "BusStopsSnapshot",
    "TrainServiceAlertsSnapshot",
    "TrafficSpeedBandsV2Snapshot",
    # Data classes
    "StoredBusService",
    "StoredBusRoute",
    "StoredBusStop",
    "StoredTrainAlert",
    "TransitDataStore",
    "TransitCollector",
    "TransitCollectionResult",
    # Functions
    "collect_transit_reference_once",
    "collect_transit_alerts_once",
    "collect_transit_all_once",
    "get_transit_stats",
    "run_alerts_scheduler",
    "run_reference_scheduler",
    # Router
    "router",
    "TrafficSpeedBandsV2ApiClient",
    "TrafficSpeedBandsV2Snapshot",
]