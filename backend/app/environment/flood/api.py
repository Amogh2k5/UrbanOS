"""PUB Flood Alerts API adapter.

Adapter owns ALL per-source quirks (URL, auth, units, nulls) per architecture
proposal §4. API data is used **only for live frontend KPI display** — never
enters ML training/prediction, never touches model artifacts.

Spec: PUB Flood Alerts / data.gov.sg Flood API
Server: https://api.data.gov.sg/v1/environment/flood-alerts (requires auth)
Alternative: PUB Telegram channel / PUB website scraping

For MVP, we use offline mode with deterministic fixtures.
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
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backend.app.mobility.traffic.geo_zones import get_zone

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))
_DEFAULT_BASE = "https://api.data.gov.sg/v1/environment"
_ENDPOINT = "/flood-alerts"
_TIMEOUT = 15.0

# Deterministic fallback fixture based on typical flood alert structure.
# Used only when offline=True OR when network fetch fails AND allow_fallback_fixture=True.
_FALLBACK_FIXTURE = {
    "items": [
        {
            "timestamp": "2024-12-01T14:30:00+08:00",
            "alerts": [
                {
                    "id": "FLD_20241201_001",
                    "location": "Orchard Road / Stamford Canal",
                    "latitude": 1.3033,
                    "longitude": 103.8317,
                    "type": "Flash Flood",
                    "severity": "High",
                    "message": "Heavy rain causing flash floods at Orchard Road. Avoid the area.",
                },
                {
                    "id": "FLD_20241201_002",
                    "location": "Bukit Timah / Dunearn Road",
                    "latitude": 1.3275,
                    "longitude": 103.7961,
                    "type": "Flash Flood",
                    "severity": "Moderate",
                    "message": "Flash flood reported at Bukit Timah Road. Water level rising.",
                },
            ]
        }
    ],
    "api_info": {"status": "healthy"}
}


@dataclass
class FloodAlert:
    """Normalized flood alert."""
    alert_id: str
    location: str
    latitude: Optional[float]
    longitude: Optional[float]
    alert_type: str
    severity: str
    message: str
    issued_at: datetime
    source: str
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None


@dataclass
class FloodAlertsSnapshot:
    """Snapshot of flood alerts at a point in time."""
    snapshot_at: str
    source: str
    provider: str
    endpoint: str
    alerts: List[FloodAlert]
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
                    "alert_id": alert.alert_id,
                    "location": alert.location,
                    "type": alert.alert_type,
                    "severity": alert.severity,
                    "message": alert.message,
                    "issued_at": alert.issued_at.isoformat(),
                    "coordinates": {
                        "lat": alert.latitude,
                        "lon": alert.longitude,
                    }
                    if alert.latitude is not None and alert.longitude is not None
                    else None,
                    "zone_id": alert.zone_id,
                    "zone_name": alert.zone_name,
                }
                for alert in self.alerts
            ],
        }


class FloodAlertsApiClient:
    """Adapter wrapping the PUB Flood Alerts endpoint.

    offline=True   -> return the deterministic fallback fixture (no network).
    offline=False  -> call the live endpoint; on failure, raise (or use fixture
                      if allow_fallback_fixture=True).
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE,
        account_key: Optional[str] = None,
        offline: bool = True,  # Default to offline for MVP
        allow_fallback_fixture: bool = True,
        timeout: float = _TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.account_key = account_key or os.getenv("DATA_GOV_SG_API_KEY")
        self.offline = offline
        self.allow_fallback_fixture = allow_fallback_fixture
        self.timeout = timeout

    def fetch(self) -> FloodAlertsSnapshot:
        """Fetch latest Flood Alerts snapshot."""
        payload, is_live = self._get_payload()
        return self._normalize(payload, is_live=is_live)

    # ---------------------------------------------------------------- internals

    def _get_payload(self):
        if self.offline:
            log.info("Flood Alerts adapter offline=True; using fallback fixture.")
            return _FALLBACK_FIXTURE, False

        if not self.account_key:
            log.warning("DATA_GOV_SG_API_KEY not set; using fallback fixture.")
            if self.allow_fallback_fixture:
                return _FALLBACK_FIXTURE, False
            raise ValueError("DATA_GOV_SG_API_KEY not configured")

        headers = {"Authorization": f"Bearer {self.account_key}", "accept": "application/json"}
        url = f"{self.base_url}{_ENDPOINT}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                return resp.json(), True
        except httpx.TimeoutException as e:
            log.warning("Flood Alerts live fetch timeout: %s", e)
        except httpx.HTTPStatusError as e:
            log.warning("Flood Alerts HTTP error: %s", e)
        except httpx.RequestError as e:
            log.warning("Flood Alerts connection error: %s", e)
        except ValueError as e:
            log.warning("Flood Alerts malformed response: %s", e)

        if self.allow_fallback_fixture:
            log.warning("Flood Alerts falling back to deterministic fixture (KPI only).")
            return _FALLBACK_FIXTURE, False
        raise

    def _normalize(self, payload: dict, is_live: bool) -> FloodAlertsSnapshot:
        items = payload.get("items") or payload.get("value") or []
        if not isinstance(items, list):
            log.warning("Unexpected payload structure for Flood Alerts")
            items = []

        alerts: List[FloodAlert] = []
        for item in items:
            item_timestamp = item.get("timestamp")
            alerts_list = item.get("alerts") or item.get("value") or []

            for alert_item in alerts_list:
                def _get(item: dict, *keys):
                    for k in keys:
                        v = item.get(k)
                        if v is not None:
                            return v
                    return None

                alert_id = _get(alert_item, "id", "alert_id", "alertId") or ""
                location = _get(alert_item, "location", "area", "name") or ""
                latitude = _get(alert_item, "latitude", "lat")
                longitude = _get(alert_item, "longitude", "lon", "lng")
                alert_type = _get(alert_item, "type", "alert_type", "category") or "Flash Flood"
                severity = _get(alert_item, "severity", "level", "risk_level") or "Moderate"
                message = _get(alert_item, "message", "description", "details") or ""

                def _to_float(v):
                    try:
                        return float(v) if v is not None else None
                    except (TypeError, ValueError):
                        return None

                def _parse_ts(v):
                    if v is None:
                        return datetime.now(SG_OFFSET)
                    try:
                        return datetime.fromisoformat(v.replace('Z', '+00:00'))
                    except (ValueError, AttributeError):
                        return datetime.now(SG_OFFSET)

                lat_f = _to_float(latitude)
                lon_f = _to_float(longitude)
                issued_at = _parse_ts(item_timestamp)

                # Look up zone for this alert
                zone_info = {"zone_id": None, "zone_name": "unknown"}
                if lat_f is not None and lon_f is not None:
                    zone_info = get_zone(lat_f, lon_f)

                alerts.append(
                    FloodAlert(
                        alert_id=alert_id,
                        location=location,
                        latitude=lat_f,
                        longitude=lon_f,
                        alert_type=alert_type,
                        severity=severity,
                        message=message,
                        issued_at=issued_at,
                        source=("live_api:PUB_flood_alerts" if is_live else "offline_fixture:PUB_flood_alerts"),
                        zone_id=zone_info["zone_id"],
                        zone_name=zone_info["zone_name"],
                    )
                )

        return FloodAlertsSnapshot(
            snapshot_at=_now_iso(),
            source=("live_api:PUB_flood_alerts" if is_live else "offline_fixture:PUB_flood_alerts"),
            provider="PUB / data.gov.sg",
            endpoint=f"{_DEFAULT_BASE}{_ENDPOINT}",
            alerts=alerts,
            is_live=is_live,
        )


def _now_iso() -> str:
    return datetime.now(SG_OFFSET).isoformat()