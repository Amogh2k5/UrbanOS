"""NEA Live API adapter for 24-hour weather forecast.

Adapter owns ALL per-source quirks (URL, paging, auth, units, timezone,
nulls) per architecture proposal §4. API data is used **only for live
frontend KPI display** — never enters ML training/prediction, never touches
model artifacts.

Spec: docs/api/24hourWeatherForecast.json (openapi 3.0.3)
Server: https://api-open.data.gov.sg/v2/real-time/api/twenty-four-hr-forecast
Auth: optional x-api-key header
Units: temperature °C, relative humidity %, wind speed km/h.
Timestamps: NEA strings are Z (= UTC); convert to Asia/Singapore (+08:00).
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
_ENDPOINT = "/twenty-four-hr-forecast"
_AIR_TEMP_ENDPOINT = "/air-temperature"
_TIMEOUT = 8.0
_AIR_TEMP_TIMEOUT = 8.0

# Fallback fixture derived from the spec's example values
# (24hourWeatherForecast.json lines 102-229). Used for offline/testing and as a
# graceful degradation fallback for the live KPI endpoint (NOTHing here enters ML).
_FALLBACK_FIXTURE = {
    "code": 0,
    "errorMsg": "",
    "data": {
        "area_metadata": [
            {"name": "Ang Mo Kio", "label_location": {"latitude": 1.375, "longitude": 103.839}},
        ],
        "records": [
            {
                "date": "2024-07-15T00:00:00.000Z",
                "updatedTimestamp": "2024-07-15T15:04:00.000Z",
                "timestamp": "2024-07-15T15:04:00.000Z",
                "general": {
                    "validPeriod": {
                        "start": "2024-07-16T16:30:00.000Z",
                        "end": "2024-07-16T18:30:00.000Z",
                        "text": "12.30 am to 2.30 am",
                    },
                    "temperature": {"low": 26, "high": 36, "unit": "Degrees Celsius"},
                    "relativeHumidity": {"low": 55, "high": 90, "unit": "Percentage"},
                    "forecast": {"code": "DR", "text": "Fair and Warm"},
                    "wind": {
                        "speed": {"low": 15, "high": 30},
                        "direction": "SSE",
                    },
                },
                "periods": [
                    {
                        "timePeriod": {
                            "start": "2024-07-16T16:30:00.000Z",
                            "end": "2024-07-16T18:30:00.000Z",
                            "text": "12.30 am to 2.30 am",
                        },
                        "regions": {
                            "west": {"code": "FW", "text": "Fair and Warm"},
                            "east": {"code": "FW", "text": "Fair and Warm"},
                            "central": {"code": "FW", "text": "Fair and Warm"},
                            "north": {"code": "FW", "text": "Fair and Warm"},
                            "south": {"code": "FW", "text": "Fair and Warm"},
                        },
                    }
                ],
            }
        ],
    },
}


# ============================================================
# AIR TEMPERATURE ADAPTER
# ============================================================

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

_AIR_TEMP_FALLBACK_FIXTURE = _make_fallback_fixture()


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
        timeout: float = _AIR_TEMP_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.getenv("NEA_API_KEY")
        self.offline = offline
        self.allow_fallback_fixture = allow_fallback_fixture
        self.timeout = timeout

    def fetch(self) -> "AirTemperatureSnapshot":
        """Fetch latest air temperature snapshot."""
        payload, is_live = self._get_payload()
        return self._normalize(payload, is_live=is_live)

    def _get_payload(self):
        if self.offline:
            log.info("Air Temperature adapter offline=True; using fallback fixture.")
            return _AIR_TEMP_FALLBACK_FIXTURE, False

        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        url = f"{self.base_url}{_AIR_TEMP_ENDPOINT}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                return resp.json(), True
        except Exception as e:
            log.warning("Air Temperature live fetch failed: %s", e)
            if self.allow_fallback_fixture:
                log.warning("Air Temperature falling back to deterministic fixture (KPI only).")
                return _AIR_TEMP_FALLBACK_FIXTURE, False
            raise

    def _normalize(self, payload: dict, is_live: bool) -> "AirTemperatureSnapshot":
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
            endpoint=f"{_DEFAULT_BASE}{_AIR_TEMP_ENDPOINT}",
            unit=reading_unit,
            reading_type=reading_type,
            readings=readings,
            is_live=is_live,
        )


# ============================================================
# CITY-LEVEL TEMPERATURE AGGREGATION
# ============================================================

def aggregate_city_temperature(snapshot: "AirTemperatureSnapshot", max_age_minutes: int = 10) -> Dict[str, Any]:
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


def aggregate_regional_temperatures(snapshot: "AirTemperatureSnapshot", max_age_minutes: int = 10) -> Dict[str, Dict[str, Any]]:
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


@dataclass
class WeatherGeneral:
    forecast_code: Optional[str]
    forecast_text: Optional[str]
    temperature_high_c: Optional[float]
    temperature_low_c: Optional[float]
    temperature_c: Optional[float]
    relative_humidity_high_pct: Optional[float]
    relative_humidity_low_pct: Optional[float]
    relative_humidity_pct: Optional[float]
    wind_speed_high_kmh: Optional[float]
    wind_speed_low_kmh: Optional[float]
    wind_speed_kmh: Optional[float]
    wind_direction: Optional[str]
    valid_period_start: Optional[str]
    valid_period_end: Optional[str]


@dataclass
class WeatherRegion:
    region: str
    forecast_code: Optional[str]
    forecast_text: str
    current_temperature: Optional[Dict[str, Any]] = None


@dataclass
class WeatherPeriod:
    """A single forecast sub-period with regional forecasts."""
    time_period_start: str
    time_period_end: str
    time_period_text: str
    regions: Dict[str, WeatherRegion]


@dataclass
class WeatherLiveSnapshot:
    snapshot_at: str
    source: str
    issue_timestamp: Optional[str]
    updated_timestamp: Optional[str]
    general: WeatherGeneral
    regions: Dict[str, WeatherRegion] = field(default_factory=dict)  # Last period's regions (for backward compat)
    periods: List[WeatherPeriod] = field(default_factory=list)       # All periods
    is_live: bool = False
    # Current observed temperature (from NEA air-temperature API)
    current_temperature: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        base = {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": "NEA / data.gov.sg",
            "endpoint": f"{_DEFAULT_BASE}{_ENDPOINT}",
            "units": {
                "temperature": "°C",
                "relative_humidity": "%",
                "wind_speed": "km/h",
            },
            "issue_timestamp": self.issue_timestamp,
            "updated_timestamp": self.updated_timestamp,
            "general": {
                "forecast_code": self.general.forecast_code,
                "forecast_text": self.general.forecast_text,
                "temperature_high_c": self.general.temperature_high_c,
                "temperature_low_c": self.general.temperature_low_c,
                "temperature_c": self.general.temperature_c,
                "relative_humidity_high_pct": self.general.relative_humidity_high_pct,
                "relative_humidity_low_pct": self.general.relative_humidity_low_pct,
                "relative_humidity_pct": self.general.relative_humidity_pct,
                "wind_speed_high_kmh": self.general.wind_speed_high_kmh,
                "wind_speed_low_kmh": self.general.wind_speed_low_kmh,
                "wind_speed_kmh": self.general.wind_speed_kmh,
                "wind_direction": self.general.wind_direction,
                "valid_period_start": self.general.valid_period_start,
                "valid_period_end": self.general.valid_period_end,
            },
            "regions": {
                r: {
                    "region": v.region, 
                    "forecast_code": v.forecast_code, 
                    "forecast_text": v.forecast_text,
                    "current_temperature": v.current_temperature,
                }
                for r, v in self.regions.items()
            },
            "periods": [
                {
                    "time_period_start": p.time_period_start,
                    "time_period_end": p.time_period_end,
                    "time_period_text": p.time_period_text,
                    "regions": {
                        r: {
                            "region": v.region,
                            "forecast_code": v.forecast_code,
                            "forecast_text": v.forecast_text,
                        }
                        for r, v in p.regions.items()
                    },
                }
                for p in self.periods
            ],
            "is_live": self.is_live,
        }
        # Add current temperature if available
        if self.current_temperature:
            base["current_temperature"] = self.current_temperature
        return base


class WeatherApiClient:
    """Adapter wrapping the NEA 24h-forecast real-time endpoint."""

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE,
        api_key: Optional[str] = None,
        offline: bool = False,
        allow_fallback_fixture: bool = True,
        timeout: float = _TIMEOUT,
        air_temperature_client: Optional[AirTemperatureApiClient] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.getenv("NEA_API_KEY")
        self.offline = offline
        self.allow_fallback_fixture = allow_fallback_fixture
        self.timeout = timeout
        self.air_temperature_client = air_temperature_client

    def fetch(self, date: Optional[str] = None) -> WeatherLiveSnapshot:
        payload, is_live = self._get_payload(date)
        snapshot = self._normalize(payload, is_live=is_live)
        
        # Fetch current temperature if client available
        if self.air_temperature_client:
            try:
                air_snap = self.air_temperature_client.fetch()
                snapshot.current_temperature = aggregate_city_temperature(air_snap, max_age_minutes=30)
                regional_temps = aggregate_regional_temperatures(air_snap, max_age_minutes=30)
                for r, temp_dict in regional_temps.items():
                    if r in snapshot.regions:
                        snapshot.regions[r].current_temperature = temp_dict
            except Exception as e:
                log.warning("Failed to fetch current temperature: %s", e)
                snapshot.current_temperature = {
                    "available": False,
                    "unavailable_reason": f"Air temperature fetch failed: {e}",
                }
        
        return snapshot

    # ---------------------------------------------------------------- internals

    def _get_payload(self, date: Optional[str]):
        if self.offline:
            log.info("Weather adapter offline=True; using fallback fixture.")
            return _FALLBACK_FIXTURE, False
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        params = {}
        if date:
            params["date"] = date
        url = f"{self.base_url}{_ENDPOINT}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                return resp.json(), True
        except Exception as e:
            log.warning("Weather live fetch failed: %s", e)
            if self.allow_fallback_fixture:
                log.warning("Weather falling back to deterministic fixture (KPI only).")
                return _FALLBACK_FIXTURE, False
            raise

    def _normalize(self, payload: dict, is_live: bool) -> WeatherLiveSnapshot:
        data = payload.get("data") or {}
        records = data.get("records") or []
        if not records:
            raise ValueError("Weather payload missing data.records")
        latest = records[-1]  # most recent issue

        general_raw = latest.get("general") or {}
        vp = general_raw.get("validPeriod") or {}
        temp = general_raw.get("temperature") or {}
        rh = general_raw.get("relativeHumidity") or {}
        fc = general_raw.get("forecast") or {}
        wind = general_raw.get("wind") or {}
        wsp = wind.get("speed") or {}

        temp_high = _num(temp.get("high"))
        temp_low = _num(temp.get("low"))
        rh_high = _num(rh.get("high"))
        rh_low = _num(rh.get("low"))
        wind_high = _num(wsp.get("high"))
        wind_low = _num(wsp.get("low"))

        general = WeatherGeneral(
            forecast_code=fc.get("code"),
            forecast_text=fc.get("text"),
            temperature_high_c=temp_high,
            temperature_low_c=temp_low,
            temperature_c=round((temp_high + temp_low) / 2, 1) if temp_high is not None and temp_low is not None else None,
            relative_humidity_high_pct=rh_high,
            relative_humidity_low_pct=rh_low,
            relative_humidity_pct=round((rh_high + rh_low) / 2, 1) if rh_high is not None and rh_low is not None else None,
            wind_speed_high_kmh=wind_high,
            wind_speed_low_kmh=wind_low,
            wind_speed_kmh=round((wind_high + wind_low) / 2, 1) if wind_high is not None and wind_low is not None else None,
            wind_direction=wind.get("direction"),
            valid_period_start=_z_to_iso(vp.get("start")),
            valid_period_end=_z_to_iso(vp.get("end")),
        )

        regions: Dict[str, WeatherRegion] = {}
        periods: List[WeatherPeriod] = []
        latest_periods = latest.get("periods") or []
        
        # Extract ALL periods for storage
        for period_raw in latest_periods:
            tp = period_raw.get("timePeriod") or {}
            regs_raw = period_raw.get("regions") or {}
            period_regions = {}
            for rname, body in regs_raw.items():
                r = rname.lower()
                period_regions[r] = WeatherRegion(
                    region=r,
                    forecast_code=body.get("code"),
                    forecast_text=(body.get("text") or ""),
                )
            periods.append(WeatherPeriod(
                time_period_start=_z_to_iso(tp.get("start")),
                time_period_end=_z_to_iso(tp.get("end")),
                time_period_text=tp.get("text", ""),
                regions=period_regions,
            ))
        
        # Use the LAST sub-period for the snapshot.regions (backward compat for KPI display)
        if latest_periods:
            last_period = latest_periods[-1]
            regs_raw = last_period.get("regions") or {}
            for rname, body in regs_raw.items():
                regions[rname.lower()] = WeatherRegion(
                    region=rname.lower(),
                    forecast_code=body.get("code"),
                    forecast_text=(body.get("text") or ""),
                )

        return WeatherLiveSnapshot(
            snapshot_at=_now_iso(),
            source=("live_api:NEA_24h_weather" if is_live else "offline_fixture:NEA_24h_weather"),
            issue_timestamp=_z_to_iso(latest.get("timestamp")),
            updated_timestamp=_z_to_iso(latest.get("updatedTimestamp")),
            general=general,
            regions=regions,
            periods=periods,
            is_live=is_live,
        )


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _z_to_iso(s: Optional[str]) -> Optional[str]:
    """Convert a NEA Z-suffixed UTC timestamp to ISO +08:00."""
    if not s:
        return None
    s2 = s.strip()
    try:
        if s2.endswith("Z"):
            dt = datetime.fromisoformat(s2[:-1]).replace(tzinfo=timezone.utc)
        elif "+" in s2[10:] or s2[10:].count("-") > 0:
            dt = datetime.fromisoformat(s2)
        else:
            dt = datetime.fromisoformat(s2).replace(tzinfo=SG_OFFSET)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=SG_OFFSET)
        return dt.astimezone(SG_OFFSET).isoformat()
    except Exception:
        return s2


def _now_iso() -> str:
    return datetime.now(SG_OFFSET).isoformat()
