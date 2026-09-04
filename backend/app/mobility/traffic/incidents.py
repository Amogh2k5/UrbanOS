"""LTA DataMall Live API adapter for Traffic Incidents.

Adapter owns ALL per-source quirks (URL, auth, units, nulls) per architecture
proposal §4. API data is used **only for live frontend KPI display** — never
enters ML training/prediction, never touches model artifacts.

Spec: LTA DataMall Traffic Incidents
Server: https://datamall2.mytransport.sg/ltaodataservice/TrafficIncidents
Auth: AccountKey header
Coordinates: WGS84 lat/lon
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

# Local zone lookup
from backend.app.mobility.traffic.geo_zones import get_zone

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))
_DEFAULT_BASE = "https://datamall2.mytransport.sg/ltaodataservice"
_ENDPOINT = "/TrafficIncidents"
_TIMEOUT = 15.0

# Deterministic fallback fixture based on LTA API documentation example values.
# Used only when offline=True OR when network fetch fails AND allow_fallback_fixture=True.
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
    """Adapter wrapping the LTA DataMall Traffic Incidents endpoint.

    offline=True   -> return the deterministic fallback fixture (no network).
    offline=False  -> call the live endpoint; on failure, raise (or use fixture
                      if allow_fallback_fixture=True).
    """

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
        """Fetch latest Traffic Incidents snapshot."""
        payload, is_live = self._get_payload()
        return self._normalize(payload, is_live=is_live)

    # ---------------------------------------------------------------- internals

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
        url = f"{self.base_url}{_ENDPOINT}"
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
            endpoint=f"{_DEFAULT_BASE}{_ENDPOINT}",
            incidents=incidents,
            is_live=is_live,
        )


def _now_iso() -> str:
    return datetime.now(SG_OFFSET).isoformat()