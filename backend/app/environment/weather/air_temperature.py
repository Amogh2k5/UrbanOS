"""NEA Live API adapter for real-time air temperature observations.

Adapter owns ALL per-source quirks (URL, paging, auth, units, timezone,
nulls) per architecture proposal §4. API data is used **only for live
frontend KPI display** — never enters ML training/prediction, never touches
model artifacts.

Spec: NEA Air Temperature real-time API
Server: https://api-open.data.gov.sg/v2/real-time/api/air-temperature
Auth: optional x-api-key header
Units: deg C (dry bulb temperature). Timestamps: ISO with +08:00 offset.
Update frequency: 1 minute.
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
_DEFAULT_BASE = "https://api-open.data.gov.sg/v2/real-time/api"
_ENDPOINT = "/air-temperature"
_TIMEOUT = 8.0

# Deterministic fixture derived from the API structure.
# Used for offline/testing and as a graceful degradation fallback for the
# live KPI endpoint (NOTHING here enters ML).
# Timestamps are set dynamically when fixture is used.
_FALLBACK_STATIONS = [
    {"id": "S109", "deviceId": "S109", "name": "Ang Mo Kio Avenue 5", "location": {"latitude": 1.3793, "longitude": 103.85}},
    {"id": "S106", "deviceId": "S106", "name": "Pulau Ubin", "location": {"latitude": 1.4168, "longitude": 103.9673}},
    {"id": "S117", "deviceId": "S117", "name": "Banyan Road", "location": {"latitude": 1.2542, "longitude": 103.6741}},
    {"id": "S107", "deviceId": "S107", "name": "East Coast Parkway", "location": {"latitude": 1.3133, "longitude": 103.962}},
    {"id": "S104", "deviceId": "S104", "name": "Woodlands Avenue 9", "location": {"latitude": 1.4439, "longitude": 103.7854}},
]

_FALLBACK_READING_DATA = [
    {"stationId": "S109", "value": 28.5},
    {"stationId": "S106", "value": 29.2},
    {"stationId": "S117", "value": 28.8},
    {"stationId": "S107", "value": 29.0},
    {"stationId": "S104", "value": 28.2},
]

def _make_fallback_fixture():
    from datetime import datetime
    now = datetime.now(SG_OFFSET).isoformat()
    return {
        "code": 0,
        "errorMsg": "",
        "data": {
            "stations": _FALLBACK_STATIONS,
            "readings": [
                {
                    "timestamp": now,
                    "data": _FALLBACK_READING_DATA,
                }
            ],
            "readingType": "DBT 1M F",
            "readingUnit": "deg C",
        }
    }

_FALLBACK_FIXTURE = _make_fallback_fixture()


@dataclass
class AirTemperatureReading:
    """Single station air temperature reading."""
    station_id: str
    station_name: str
    latitude: float
    longitude: float
    value_c: float
    observed_at: str  # ISO +08:00
    source: str


@dataclass
class AirTemperatureSnapshot:
    """Snapshot of air temperature readings at a point in time."""
    snapshot_at: str
    source: str
    provider: str
    endpoint: str
    unit: str
    reading_type: str
    readings: Dict[str, AirTemperatureReading] = field(default_factory=dict)
    is_live: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "unit": self.unit,
            "reading_type": self.reading_type,
            "is_live": self.is_live,
            "count": len(self.readings),
            "readings": {
                k: {
                    "station_id": v.station_id,
                    "station_name": v.station_name,
                    "value_c": v.value_c,
                    "observed_at": v.observed_at,
                    "source": v.source,
                    "coordinates": {
                        "lat": v.latitude,
                        "lon": v.longitude,
                    },
                }
                for k, v in self.readings.items()
            },
        }


class AirTemperatureApiClient:
    """Adapter wrapping the NEA real-time air temperature endpoint.

    offline=True   -> return the deterministic fallback fixture (no network).
    offline=False  -> call the live endpoint; on failure, raise (or use fixture
                      if allow_fallback_fixture=True).
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE,
        api_key: Optional[str] = None,
        offline: bool = False,
        allow_fallback_fixture: bool = True,
        timeout: float = _TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.getenv("NEA_API_KEY")
        self.offline = offline
        self.allow_fallback_fixture = allow_fallback_fixture
        self.timeout = timeout

    def fetch(self) -> AirTemperatureSnapshot:
        """Fetch latest air temperature snapshot."""
        payload, is_live = self._get_payload()
        return self._normalize(payload, is_live=is_live)

    def _get_payload(self):
        if self.offline:
            log.info("Air Temperature adapter offline=True; using fallback fixture.")
            return _FALLBACK_FIXTURE, False

        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        url = f"{self.base_url}{_ENDPOINT}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                return resp.json(), True
        except Exception as e:
            log.warning("Air Temperature live fetch failed: %s", e)
            if self.allow_fallback_fixture:
                log.warning("Air Temperature falling back to deterministic fixture (KPI only).")
                return _FALLBACK_FIXTURE, False
            raise

    def _normalize(self, payload: dict, is_live: bool) -> AirTemperatureSnapshot:
        data = payload.get("data") or {}
        stations = data.get("stations") or []
        readings_list = data.get("readings") or []
        reading_type = data.get("readingType") or ""
        reading_unit = data.get("readingUnit") or ""

        if not readings_list:
            raise ValueError("Air Temperature payload missing data.readings")

        latest_reading = readings_list[0]  # Most recent reading
        reading_data = latest_reading.get("data") or []
        observed_at = latest_reading.get("timestamp") or _now_iso()

        # Build station metadata lookup
        station_lookup = {}
        for s in stations:
            station_lookup[s.get("id")] = {
                "name": s.get("name", s.get("id")),
                "lat": s.get("location", {}).get("latitude"),
                "lon": s.get("location", {}).get("longitude"),
            }

        readings: Dict[str, AirTemperatureReading] = {}
        for rd in reading_data:
            station_id = rd.get("stationId")
            value = rd.get("value")
            if station_id is None or value is None:
                continue
            meta = station_lookup.get(station_id, {})
            try:
                val = float(value)
            except (TypeError, ValueError):
                continue
            readings[station_id] = AirTemperatureReading(
                station_id=station_id,
                station_name=meta.get("name", station_id),
                latitude=meta.get("lat"),
                longitude=meta.get("lon"),
                value_c=val,
                observed_at=observed_at,
                source=("live_api:NEA_air_temperature" if is_live else "offline_fixture:NEA_air_temperature"),
            )

        return AirTemperatureSnapshot(
            snapshot_at=_now_iso(),
            source=("live_api:NEA_air_temperature" if is_live else "offline_fixture:NEA_air_temperature"),
            provider="NEA / data.gov.sg",
            endpoint=f"{self.base_url}{_ENDPOINT}",
            unit=reading_unit,
            reading_type=reading_type,
            readings=readings,
            is_live=is_live,
        )


def _now_iso() -> str:
    return datetime.now(SG_OFFSET).isoformat()


# ============================================================
# City-level temperature aggregation
# ============================================================

def aggregate_city_temperature(snapshot: AirTemperatureSnapshot, max_age_minutes: int = 10) -> Dict[str, Any]:
    """Aggregate station-level observations into a city-level temperature.

    Args:
        snapshot: AirTemperatureSnapshot with station readings
        max_age_minutes: Maximum age of observations to include (default 10 min)

    Returns:
        Dict with:
        - value_c: mean temperature across valid stations
        - min_c: minimum station temperature
        - max_c: maximum station temperature
        - stations_used: count of valid stations
        - observed_at: latest observation timestamp
        - aggregation: description of method
        - stations: list of {station_id, station_name, value_c, observed_at}
        - freshness_minutes: age of latest observation
        - unavailable_reason: if no valid data
    """
    if not snapshot or not snapshot.readings:
        return {
            "available": False,
            "unavailable_reason": "No station readings in snapshot",
            "value_c": None,
            "min_c": None,
            "max_c": None,
            "stations_used": 0,
            "observed_at": None,
            "aggregation": "mean_of_recent_valid_stations",
            "stations": [],
            "freshness_minutes": None,
        }

    # Filter by freshness
    now = datetime.now(SG_OFFSET)
    valid_readings = []
    stale_readings = []

    for reading in snapshot.readings.values():
        try:
            obs_time = datetime.fromisoformat(reading.observed_at)
            age_minutes = (now - obs_time).total_seconds() / 60.0
            if age_minutes <= max_age_minutes:
                valid_readings.append((reading, age_minutes))
            else:
                stale_readings.append((reading, age_minutes))
        except Exception:
            continue

    if not valid_readings:
        return {
            "available": False,
            "unavailable_reason": f"No observations within {max_age_minutes} min freshness window",
            "value_c": None,
            "min_c": None,
            "max_c": None,
            "stations_used": 0,
            "observed_at": None,
            "aggregation": "mean_of_recent_valid_stations",
            "stations": [],
            "freshness_minutes": min((age for _, age in stale_readings), default=None),
        }

    # Filter out None values
    valid_values = [(r, a) for r, a in valid_readings if r.value_c is not None]
    if not valid_values:
        return {
            "available": False,
            "unavailable_reason": "All readings have None values",
            "value_c": None,
            "min_c": None,
            "max_c": None,
            "stations_used": 0,
            "observed_at": None,
            "aggregation": "mean_of_recent_valid_stations",
            "stations": [],
            "freshness_minutes": max((age for _, age in valid_readings), default=None),
        }
    
    values = [r.value_c for r, _ in valid_values]
    mean_temp = sum(values) / len(values)
    min_temp = min(values)
    max_temp = max(values)
    latest_obs = max(r.observed_at for r, _ in valid_values)
    max_age = max(age for _, age in valid_values)

    return {
        "available": True,
        "value_c": round(mean_temp, 1),
        "min_c": round(min_temp, 1),
        "max_c": round(max_temp, 1),
        "stations_used": len(valid_values),
        "observed_at": latest_obs,
        "aggregation": "mean_of_recent_valid_stations",
        "stations": [
            {
                "station_id": r.station_id,
                "station_name": r.station_name,
                "value_c": r.value_c,
                "observed_at": r.observed_at,
            }
            for r, _ in valid_values
        ],
        "freshness_minutes": round(max_age, 1),
    }

def aggregate_regional_temperatures(snapshot: AirTemperatureSnapshot, max_age_minutes: int = 10) -> Dict[str, Dict[str, Any]]:
    """Group valid station readings by region (north, south, east, west, central) and compute averages."""
    if not snapshot or not snapshot.readings:
        return {}

    now = datetime.now(SG_OFFSET)
    regions: Dict[str, List[float]] = {
        "north": [], "south": [], "east": [], "west": [], "central": []
    }

    for reading in snapshot.readings.values():
        if reading.value_c is None:
            continue
        try:
            obs_time = datetime.fromisoformat(reading.observed_at)
            age_minutes = (now - obs_time).total_seconds() / 60.0
            if age_minutes > max_age_minutes:
                continue
        except Exception:
            continue
            
        lat, lon = reading.latitude, reading.longitude
        if lat is None or lon is None:
            continue
            
        # Simple heuristic mapping for Singapore coordinates
        if lat > 1.41:
            r = "north"
        elif lat < 1.30:
            r = "south"
        elif lon > 103.89:
            r = "east"
        elif lon < 103.75:
            r = "west"
        else:
            r = "central"
            
        regions[r].append(reading.value_c)
        
    result = {}
    for r, values in regions.items():
        if values:
            mean_temp = sum(values) / len(values)
            result[r] = {
                "available": True,
                "value_c": round(mean_temp, 1),
                "stations_used": len(values)
            }
    return result