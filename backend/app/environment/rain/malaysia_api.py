"""Malaysia Meteorological Department (MetMalaysia) Rainfall API Adapter.

Adapter owns ALL per-source quirks per architecture proposal §4.
API data is used ONLY for live flood risk assessment — never enters ML.

Spec: MetMalaysia Open Data API (requires access token registration)
Server: https://api.met.gov.my
Auth: OAuth2 / API Key (requires registration at https://api.met.gov.my)
Units: mm. Timestamps: ISO 8601 (typically UTC, convert to Asia/Singapore +08:00).

Focus: Johor / Southern Malaysia stations relevant to Singapore flood risk.

For MVP: If credentials unavailable, return explicit UNAVAILABLE state.
Do NOT fabricate live data.
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
_DEFAULT_BASE = "https://api.met.gov.my"
_TIMEOUT = 15.0

# Known Johor stations relevant to Singapore flood risk
# (Station IDs from MetMalaysia public station list - may need adjustment)
JOHOR_STATIONS = {
    "johor_bahru": {"name": "Johor Bahru", "lat": 1.4927, "lon": 103.7414},
    "kota_tinggi": {"name": "Kota Tinggi", "lat": 1.7339, "lon": 103.9001},
    "mersing": {"name": "Mersing", "lat": 2.4305, "lon": 103.8414},
    "batu_pahat": {"name": "Batu Pahat", "lat": 1.8507, "lon": 102.9328},
    "kluang": {"name": "Kluang", "lat": 2.0312, "lon": 103.3156},
    "segamat": {"name": "Segamat", "lat": 2.5143, "lon": 102.8105},
    "pontian": {"name": "Pontian", "lat": 1.4824, "lon": 103.3856},
}

# Deterministic fallback fixture structure for offline/testing
_FALLBACK_FIXTURE = {
    "stations": [
        {"id": "johor_bahru", "name": "Johor Bahru", "lat": 1.4927, "lon": 103.7414, "rainfall_mm": 0.0, "timestamp": "2024-12-01T14:30:00+08:00"},
        {"id": "kota_tinggi", "name": "Kota Tinggi", "lat": 1.7339, "lon": 103.9001, "rainfall_mm": 0.0, "timestamp": "2024-12-01T14:30:00+08:00"},
    ],
    "source": "offline_fixture:MetMalaysia_rainfall",
    "is_live": False,
}


@dataclass
class MalaysiaRainfallReading:
    """Single station rainfall reading from MetMalaysia."""
    station_id: str
    station_name: str
    latitude: float
    longitude: float
    rainfall_mm: float
    timestamp: str  # ISO +08:00
    source: str


@dataclass
class MalaysiaRainfallSnapshot:
    """Snapshot of Malaysia/Johor rainfall at a point in time."""
    snapshot_at: str
    source: str
    provider: str
    endpoint: str
    unit: str
    readings: Dict[str, MalaysiaRainfallReading] = field(default_factory=dict)
    is_live: bool = False
    credentials_configured: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "unit": self.unit,
            "is_live": self.is_live,
            "credentials_configured": self.credentials_configured,
            "error": self.error,
            "count": len(self.readings),
            "readings": {
                k: {
                    "station_id": v.station_id,
                    "station_name": v.station_name,
                    "latitude": v.latitude,
                    "longitude": v.longitude,
                    "rainfall_mm": v.rainfall_mm,
                    "timestamp": v.timestamp,
                    "source": v.source,
                }
                for k, v in self.readings.items()
            },
        }


class MalaysiaRainfallApiClient:
    """Adapter wrapping the MetMalaysia rainfall endpoint.

    offline=True   -> return deterministic fallback fixture (no network).
    offline=False  -> attempt live fetch; if credentials missing or fetch fails,
                      return UNAVAILABLE state with error (never fabricate data).
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE,
        api_key: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        offline: bool = False,
        timeout: float = _TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.getenv("METMALAYSIA_API_KEY")
        self.client_id = client_id or os.getenv("METMALAYSIA_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("METMALAYSIA_CLIENT_SECRET")
        self.offline = offline
        self.timeout = timeout
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None

    def fetch(self) -> MalaysiaRainfallSnapshot:
        """Fetch latest rainfall snapshot for Johor stations."""
        if self.offline:
            log.info("Malaysia rainfall adapter offline=True; using fallback fixture.")
            return self._normalize(_FALLBACK_FIXTURE, is_live=False)

        if not self._credentials_available():
            error_msg = "MetMalaysia API credentials not configured (need API_KEY or CLIENT_ID/CLIENT_SECRET)"
            log.warning(error_msg)
            return MalaysiaRainfallSnapshot(
                snapshot_at=_now_iso(),
                source="unavailable:MetMalaysia_rainfall",
                provider="MetMalaysia / data.gov.my",
                endpoint=f"{self.base_url}/v2/rainfall",
                unit="mm",
                is_live=False,
                credentials_configured=False,
                error=error_msg,
            )

        try:
            payload = self._fetch_live()
            return self._normalize(payload, is_live=True)
        except Exception as e:
            error_msg = f"MetMalaysia live fetch failed: {e}"
            log.warning(error_msg)
            return MalaysiaRainfallSnapshot(
                snapshot_at=_now_iso(),
                source="error:MetMalaysia_rainfall",
                provider="MetMalaysia / data.gov.my",
                endpoint=f"{self.base_url}/v2/rainfall",
                unit="mm",
                is_live=False,
                credentials_configured=True,
                error=error_msg,
            )

    def _credentials_available(self) -> bool:
        return bool(self.api_key or (self.client_id and self.client_secret))

    def _fetch_live(self) -> Dict[str, Any]:
        """Fetch live data from MetMalaysia API."""
        # Note: Actual endpoint structure depends on MetMalaysia API spec
        # This is a template - adjust based on actual API documentation
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif self.client_id and self.client_secret:
            # OAuth2 client credentials flow
            token = self._get_access_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"

        url = f"{self.base_url}/v2/rainfall"
        params = {"states": "johor"}  # Filter to Johor if API supports
        
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp.json()

    def _get_access_token(self) -> Optional[str]:
        """Get OAuth2 access token using client credentials."""
        if self._access_token and self._token_expiry and datetime.now(timezone.utc) < self._token_expiry:
            return self._access_token
        
        if not (self.client_id and self.client_secret):
            return None
        
        try:
            token_url = f"{self.base_url}/oauth/token"
            data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(token_url, data=data)
                resp.raise_for_status()
                token_data = resp.json()
                self._access_token = token_data.get("access_token")
                expires_in = token_data.get("expires_in", 3600)
                self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
                return self._access_token
        except Exception as e:
            log.warning(f"Failed to get MetMalaysia access token: {e}")
            return None
        return None

    def _normalize(self, payload: Dict[str, Any], is_live: bool) -> MalaysiaRainfallSnapshot:
        """Normalize MetMalaysia payload to standard format."""
        readings: Dict[str, MalaysiaRainfallReading] = {}
        
        stations_data = payload.get("stations") or payload.get("data") or []
        for station in stations_data:
            station_id = station.get("id") or station.get("station_id")
            if not station_id:
                continue
            
            # Only include Johor stations we track
            if station_id not in JOHOR_STATIONS:
                continue
            
            meta = JOHOR_STATIONS[station_id]
            rainfall = station.get("rainfall_mm") or station.get("value") or station.get("reading")
            try:
                rainfall_mm = float(rainfall) if rainfall is not None else 0.0
            except (TypeError, ValueError):
                rainfall_mm = 0.0
            
            ts = station.get("timestamp") or station.get("time")
            timestamp = _to_iso_sg(ts) if ts else _now_iso()
            
            readings[station_id] = MalaysiaRainfallReading(
                station_id=station_id,
                station_name=meta["name"],
                latitude=meta["lat"],
                longitude=meta["lon"],
                rainfall_mm=rainfall_mm,
                timestamp=timestamp,
                source=("live_api:MetMalaysia_rainfall" if is_live else "offline_fixture:MetMalaysia_rainfall"),
            )
        
        return MalaysiaRainfallSnapshot(
            snapshot_at=_now_iso(),
            source=("live_api:MetMalaysia_rainfall" if is_live else "offline_fixture:MetMalaysia_rainfall"),
            provider="MetMalaysia / data.gov.my",
            endpoint=f"{self.base_url}/v2/rainfall",
            unit="mm",
            readings=readings,
            is_live=is_live,
            credentials_configured=self._credentials_available(),
        )


def _to_iso_sg(ts_str: str) -> str:
    """Convert timestamp to ISO +08:00."""
    try:
        if ts_str.endswith("Z"):
            dt = datetime.fromisoformat(ts_str[:-1]).replace(tzinfo=timezone.utc)
        elif "+" in ts_str or ts_str.count("-") > 2:
            dt = datetime.fromisoformat(ts_str)
        else:
            dt = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
        return dt.astimezone(SG_OFFSET).isoformat()
    except Exception:
        return _now_iso()


def _now_iso() -> str:
    return datetime.now(SG_OFFSET).isoformat()


# ============================================================
# Convenience function for Flood Agent
# ============================================================

def get_malaysia_rainfall_evidence(client: MalaysiaRainfallApiClient) -> Dict[str, Any]:
    """Extract rainfall evidence from Malaysia snapshot for Flood Agent.
    
    Returns dict with:
    - available: bool (True if live data available)
    - stations: dict of station readings
    - max_1h: float (max 1h rainfall across stations - proxy from current reading)
    - max_24h: float (not available from single reading)
    - weather_systems: list (e.g., "monsoon_surge", "sumatra_squall")
    - source: str
    - error: str or None
    """
    snapshot = client.fetch()
    
    if not snapshot.is_live or snapshot.error:
        return {
            "available": False,
            "source": snapshot.source,
            "error": snapshot.error or "No live data",
            "stations": {},
            "max_1h_mm": 0.0,
            "max_24h_mm": 0.0,
            "weather_systems": [],
            "wind_direction": None,
        }
    
    max_1h = max((r.rainfall_mm for r in snapshot.readings.values()), default=0.0)
    
    # Detect weather systems from rainfall patterns (simplified)
    weather_systems = []
    if max_1h > 50:
        weather_systems.append("heavy_rainfall_johor")
    
    return {
        "available": True,
        "source": snapshot.source,
        "stations": {k: {"rainfall_mm": v.rainfall_mm, "timestamp": v.timestamp} for k, v in snapshot.readings.items()},
        "max_1h_mm": max_1h,
        "max_24h_mm": 0.0,  # Not available from single reading
        "weather_systems": weather_systems,
        "wind_direction": None,
    }