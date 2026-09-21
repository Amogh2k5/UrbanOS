"""Traffic API router and LTA DataMall adapters."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.app.mobility.traffic.agent import run_traffic_agent
from backend.app.mobility.traffic.data import TrafficReport
from backend.app.mobility.traffic.geo_zones import get_zone

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))
_DEFAULT_BASE = "https://datamall2.mytransport.sg/ltaodataservice"
_INCIDENTS_ENDPOINT = "/TrafficIncidents"
_SPEED_BANDS_ENDPOINT = "/v4/TrafficSpeedBands"
_TIMEOUT = 15.0
_PAGE_SIZE = 10000

# ============================================================
# TRAFFIC INCIDENTS ADAPTER (from incidents.py)
# ============================================================

_FALLBACK_FIXTURE = {
    "odata.metadata": "https://datamall2.mytransport.sg/ltaodataservice/$metadata#IncidentSet",
    "value": [],
}

@dataclass
class TrafficIncident:
    incident_type: str
    latitude: Optional[float]
    longitude: Optional[float]
    message: str
    source: str
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None


@dataclass
class TrafficIncidentsSnapshot:
    snapshot_at: str
    source: str
    provider: str
    endpoint: str
    incidents: List[TrafficIncident]
    is_live: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "is_live": self.is_live,
            "count": len(self.incidents),
            "incidents": [
                {
                    "type": inc.incident_type,
                    "message": inc.message,
                    "coordinates": {
                        "lat": inc.latitude,
                        "lon": inc.longitude,
                    }
                    if inc.latitude is not None and inc.longitude is not None
                    else None,
                    "zone_id": inc.zone_id,
                    "zone_name": inc.zone_name,
                }
                for inc in self.incidents
            ],
        }


class TrafficIncidentsApiClient:
    """Adapter wrapping the LTA DataMall Traffic Incidents endpoint."""

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

    def fetch(self) -> TrafficIncidentsSnapshot:
        payload, is_live = self._get_payload()
        return self._normalize(payload, is_live=is_live)

    def _get_payload(self):
        if self.offline:
            log.info("Traffic Incidents adapter offline=True; using fallback fixture.")
            return _FALLBACK_FIXTURE, False

        if not self.account_key:
            log.warning("LTA_ACCOUNT_KEY not set; using fallback fixture.")
            if self.allow_fallback_fixture:
                return _FALLBACK_FIXTURE, False
            raise ValueError("LTA_ACCOUNT_KEY not configured")

        headers = {"AccountKey": self.account_key, "accept": "application/json"}
        url = f"{self.base_url}{_INCIDENTS_ENDPOINT}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                return resp.json(), True
        except httpx.TimeoutException as e:
            log.warning("Traffic Incidents live fetch timeout: %s", e)
        except httpx.HTTPStatusError as e:
            log.warning("Traffic Incidents HTTP error: %s", e)
        except httpx.RequestError as e:
            log.warning("Traffic Incidents connection error: %s", e)
        except ValueError as e:
            log.warning("Traffic Incidents malformed response: %s", e)

        if self.allow_fallback_fixture:
            log.warning("Traffic Incidents falling back to deterministic fixture (KPI only).")
            return _FALLBACK_FIXTURE, False
        raise

    def _normalize(self, payload: dict, is_live: bool) -> TrafficIncidentsSnapshot:
        value = payload.get("value") or payload.get("Value") or []
        if not isinstance(value, list):
            log.warning("Unexpected payload structure for Traffic Incidents")
            value = []

        incidents: List[TrafficIncident] = []
        for item in value:
            def _get(item: dict, *keys):
                for k in keys:
                    v = item.get(k)
                    if v is not None:
                        return v
                return None

            incident_type = _get(item, "Type", "type") or ""
            latitude = _get(item, "Latitude", "latitude")
            longitude = _get(item, "Longitude", "longitude")
            message = _get(item, "Message", "message") or ""

            def _to_float(v):
                try:
                    return float(v) if v is not None else None
                except (TypeError, ValueError):
                    return None

            lat_f = _to_float(latitude)
            lon_f = _to_float(longitude)

            # Look up zone for this incident
            zone_info = {"zone_id": None, "zone_name": "unknown"}
            if lat_f is not None and lon_f is not None:
                zone_info = get_zone(lat_f, lon_f)

            incidents.append(
                TrafficIncident(
                    incident_type=incident_type,
                    latitude=lat_f,
                    longitude=lon_f,
                    message=message,
                    source=("live_api:LTA_traffic_incidents" if is_live else "offline_fixture:LTA_traffic_incidents"),
                    zone_id=zone_info["zone_id"],
                    zone_name=zone_info["zone_name"],
                )
            )

        return TrafficIncidentsSnapshot(
            snapshot_at=_now_iso(),
            source=("live_api:LTA_traffic_incidents" if is_live else "offline_fixture:LTA_traffic_incidents"),
            provider="LTA DataMall",
            endpoint=f"{_DEFAULT_BASE}{_INCIDENTS_ENDPOINT}",
            incidents=incidents,
            is_live=is_live,
        )


# ============================================================
# TRAFFIC SPEED BANDS V2 ADAPTER (from speed_bands_v2.py)
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
    """Adapter for LTA DataMall Traffic Speed Bands v2 endpoint."""

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

    def fetch(self) -> TrafficSpeedBandsV2Snapshot:
        """Fetch latest Traffic Speed Bands v2 snapshot from live API."""
        headers = {"AccountKey": self.api_key, "accept": "application/json"}
        url = f"{self.base_url}{_SPEED_BANDS_ENDPOINT}"

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

    def fetch_all_pages(self) -> TrafficSpeedBandsV2Snapshot:
        """Fetch ALL Traffic Speed Bands pages (complete Singapore snapshot)."""
        headers = {"AccountKey": self.api_key, "accept": "application/json"}
        base_url = f"{self.base_url}{_SPEED_BANDS_ENDPOINT}"

        snapshot_at = _now_iso()
        all_segments: List[TrafficSpeedBandV2] = []
        page = 0

        # Reuse a single HTTP client for all pages
        with httpx.Client(timeout=self.timeout) as client:
            while True:
                skip = page * _PAGE_SIZE
                url = f"{base_url}?$top={_PAGE_SIZE}&$skip={skip}"

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
            endpoint=f"{_DEFAULT_BASE}{_SPEED_BANDS_ENDPOINT}",
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

            segments.append(
                TrafficSpeedBandV2(
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
                )
            )

        return segments

    def _normalize(self, payload: dict) -> TrafficSpeedBandsV2Snapshot:
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
            endpoint=f"{_DEFAULT_BASE}{_SPEED_BANDS_ENDPOINT}",
            segments=segments,
            is_live=True,
        )


# ============================================================
# FASTAPI ROUTER (from api.py)
# ============================================================

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from backend.app.mobility.traffic.agent import run_traffic_agent
from backend.app.mobility.traffic.data import TrafficReport

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mobility/traffic", tags=["mobility", "traffic"])


@router.get("/report", response_model=TrafficReport)
async def get_traffic_report(
    offline: bool = Query(False, description="Use offline mode (deterministic fixture)")
) -> TrafficReport:
    """Get combined traffic report with ML predictions and live incidents."""
    try:
        report = run_traffic_agent(offline=offline)
        return report
    except Exception as e:
        log.exception("Failed to generate traffic report")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/report/offline", response_model=TrafficReport)
async def get_traffic_report_offline() -> TrafficReport:
    """Get traffic report in offline mode (deterministic fixture)."""
    return await get_traffic_report(offline=True)


def _now_iso() -> str:
    return datetime.now(SG_OFFSET).isoformat()

# Re-export for backward compatibility
__all__ = [
    "router",
    "TrafficIncidentsApiClient",
    "TrafficIncidentsSnapshot",
    "TrafficSpeedBandsV2ApiClient",
    "TrafficSpeedBandsV2Snapshot",
    "run_traffic_agent",
]