"""LTA DataMall Live API adapters for Bus Services, Routes, and Stops.

Adapter owns ALL per-source quirks (URL, auth, units, nulls) per architecture
proposal §4. API data is used for reference data and transit status display.

Endpoints:
- BusServices: https://datamall2.mytransport.sg/ltaodataservice/BusServices
- BusRoutes: https://datamall2.mytransport.sg/ltaodataservice/BusRoutes
- BusStops: https://datamall2.mytransport.sg/ltaodataservice/BusStops

Auth: AccountKey header
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import httpx

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
    routes: List[BusRoute]
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
    stops: List[BusStop]
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

    def fetch(self) -> BusServicesSnapshot:
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

    def fetch(self) -> BusRoutesSnapshot:
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

    def _normalize(self, records: List[dict]) -> List[BusRoute]:
        routes: List[BusRoute] = []
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

    def fetch(self) -> BusStopsSnapshot:
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

    def _normalize(self, records: List[dict]) -> List[BusStop]:
        stops: List[BusStop] = []
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