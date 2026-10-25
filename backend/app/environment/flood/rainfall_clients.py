"""Rainfall API clients for Flood module.

Contains NEA Singapore 5-min rainfall and BMKG Sumatra forecast clients.
Used internally by Flood Agent.
"""
from __future__ import annotations

import logging
import os
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import httpx
from backend.app.upstream import SingleFlightTTLCache, retry_429_delay

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))

# Retry configuration for rate-limited requests
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 30.0
_RAINFALL_CACHE = SingleFlightTTLCache()
_RAINFALL_CACHE_TTL_S = 30.0
_RAINFALL_FAILURE_TTL_S = 30.0
_SUMATRA_CACHE = SingleFlightTTLCache()
_SUMATRA_CACHE_TTL_S = 300.0
_SUMATRA_FAILURE_TTL_S = 30.0
_SUMATRA_MAX_WORKERS = 4


# ---------- NEA Singapore 5-min rainfall ----------
_DEFAULT_NEA_BASE = "https://api-open.data.gov.sg/v2/real-time/api"
_NEA_ENDPOINT = "/rainfall"
_NEA_TIMEOUT = 10.0

_FALLBACK_FIXTURE = {
    "code": 0,
    "errorMsg": "",
    "data": {
        "stations": [
            {"id": "S90", "deviceId": "S90", "name": "Bukit Timah Road", "location": {"latitude": 1.3191, "longitude": 103.8191}},
            {"id": "S61", "deviceId": "S61", "name": "Chai Chee Street", "location": {"latitude": 1.3230, "longitude": 103.9217}},
            {"id": "S40", "deviceId": "S40", "name": "Mandai Lake Road", "location": {"latitude": 1.4044, "longitude": 103.7896}},
            {"id": "S109", "deviceId": "S109", "name": "Ang Mo Kio Avenue 5", "location": {"latitude": 1.3764, "longitude": 103.8492}},
            {"id": "S33", "deviceId": "S33", "name": "Jurong Pier Road", "location": {"latitude": 1.3081, "longitude": 103.7100}},
        ],
        "readings": [
            {
                "timestamp": "2024-12-01T14:30:00+08:00",
                "data": [
                    {"stationId": "S90", "value": 0.0},
                    {"stationId": "S61", "value": 0.0},
                    {"stationId": "S40", "value": 0.0},
                    {"stationId": "S109", "value": 0.0},
                    {"stationId": "S33", "value": 0.0},
                ],
            }
        ],
        "readingType": "TB1 Rainfall 5 Minute Total F",
        "readingUnit": "mm",
    },
}


@dataclass
class RainfallReading:
    station_id: str
    station_name: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    value_mm: float
    unit: str
    observed_at: str
    source: str


@dataclass
class RainfallSnapshot:
    snapshot_at: str
    source: str
    provider: str
    endpoint: str
    unit: str
    readings: Dict[str, RainfallReading] = field(default_factory=dict)
    is_live: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "unit": self.unit,
            "is_live": self.is_live,
            "count": len(self.readings),
            "readings": {
                r: {
                    "station_id": v.station_id,
                    "station_name": v.station_name,
                    "value_mm": v.value_mm,
                    "unit": v.unit,
                    "observed_at": v.observed_at,
                    "source": v.source,
                    "coordinates": {
                        "lat": v.latitude,
                        "lon": v.longitude,
                    }
                    if v.latitude is not None and v.longitude is not None
                    else None,
                }
                for r, v in self.readings.items()
            },
        }


class RainfallApiClient:
    def __init__(
        self,
        base_url: str = _DEFAULT_NEA_BASE,
        api_key: Optional[str] = None,
        offline: bool = False,
        allow_fallback_fixture: bool = True,
        timeout: float = _NEA_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.getenv("DATA_GOV_SG_API_KEY")
        self.offline = offline
        self.allow_fallback_fixture = allow_fallback_fixture
        self.timeout = timeout

    def fetch(self, date: Optional[str] = None) -> RainfallSnapshot:
        api_key_fingerprint = hashlib.sha256((self.api_key or "").encode()).hexdigest()[:16]
        key = (self.base_url, date, api_key_fingerprint, self.offline)
        return _RAINFALL_CACHE.get_or_fetch(
            key,
            lambda: self._fetch_uncached(date),
            ttl_seconds=_RAINFALL_CACHE_TTL_S,
            error_ttl_seconds=_RAINFALL_FAILURE_TTL_S,
            cache_result=lambda snapshot: snapshot.is_live or self.offline,
        )

    def _fetch_uncached(self, date: Optional[str]) -> RainfallSnapshot:
        payload, is_live = self._get_payload(date)
        return self._normalize(payload, is_live=is_live)

    def _get_payload(self, date: Optional[str]):
        if self.offline:
            log.info("Rainfall adapter offline=True; using fallback fixture.")
            return _FALLBACK_FIXTURE, False

        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        params = {}
        if date:
            params["date"] = date
        url = f"{self.base_url}{_NEA_ENDPOINT}"
        
        last_exception = None
        for attempt in range(MAX_RETRIES):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.get(url, headers=headers, params=params)
                    resp.raise_for_status()
                    return resp.json(), True
            except httpx.HTTPStatusError as e:
                last_exception = e
                if e.response.status_code == 429 and attempt < MAX_RETRIES - 1:
                    backoff = retry_429_delay(
                        e, attempt, base_seconds=BASE_BACKOFF_SECONDS,
                        max_seconds=MAX_BACKOFF_SECONDS,
                    )
                    backoff = backoff if backoff is not None else 0.0
                    log.warning("Rate limited (HTTP 429) on attempt %d/%d, backing off %.1fs",
                               attempt + 1, MAX_RETRIES, backoff)
                    time.sleep(backoff)
                    continue
                log.warning("Rainfall live fetch failed: %s", e)
                # 403 and other permanent HTTP errors are not transient; do
                # not send the same rejected request again in this retry loop.
                if e.response.status_code != 429:
                    break
            except Exception as e:
                last_exception = e
                if attempt < MAX_RETRIES - 1:
                    backoff = min(BASE_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)
                    log.warning("Rainfall fetch failed on attempt %d/%d: %s, backing off %.1fs",
                               attempt + 1, MAX_RETRIES, e, backoff)
                    time.sleep(backoff)
                    continue
                log.warning("Rainfall live fetch failed: %s", e)
        
        if self.allow_fallback_fixture and self.offline:
            log.warning("Rainfall falling back to deterministic fixture (KPI only).")
            return _FALLBACK_FIXTURE, False
        raise last_exception

    def _normalize(self, payload: dict, is_live: bool) -> RainfallSnapshot:
        data = payload.get("data") or {}
        stations = data.get("stations") or []
        readings_list = data.get("readings") or []

        if not readings_list:
            raise ValueError("Rainfall payload missing data.readings")

        latest_reading = readings_list[0] if readings_list else {}
        readings_raw = latest_reading.get("data") or []
        raw_issue = latest_reading.get("timestamp")

        meta_lookup = {}
        for s in stations:
            meta_lookup[s.get("id")] = {
                "name": s.get("name", s.get("id")),
                "lat": s.get("location", {}).get("latitude"),
                "lon": s.get("location", {}).get("longitude"),
            }

        observed_at = _nea_to_iso(raw_issue)

        readings: Dict[str, RainfallReading] = {}
        for reading_data in readings_raw:
            station_id = reading_data.get("stationId")
            value = reading_data.get("value")
            if station_id is None or value is None:
                continue
            meta = meta_lookup.get(station_id, {})
            try:
                val = float(value) if value is not None else 0.0
            except (TypeError, ValueError):
                val = 0.0

            readings[station_id] = RainfallReading(
                station_id=station_id,
                station_name=meta.get("name", station_id),
                latitude=meta.get("lat"),
                longitude=meta.get("lon"),
                value_mm=val,
                unit="mm",
                observed_at=observed_at,
                source=("live_api:NEA_rainfall_5min" if is_live else "offline_fixture:NEA_rainfall_5min"),
            )

        return RainfallSnapshot(
            snapshot_at=_now_iso(),
            source=("live_api:NEA_rainfall_5min" if is_live else "offline_fixture:NEA_rainfall_5min"),
            provider="NEA / data.gov.sg",
            endpoint=f"{self.base_url}{_NEA_ENDPOINT}",
            unit="mm",
            readings=readings,
            is_live=is_live,
        )


# ---------- BMKG Sumatra forecast ----------
_BMKG_BASE_URL = "https://api.bmkg.go.id/publik/prakiraan-cuaca"
_BMKG_TIMEOUT = 15.0

BMKG_LOCATIONS = {
    "batam": [
        {"adm4": "21.71.02.1001", "name": "Batu Ampar", "lat": 1.1167, "lon": 104.0167},
        {"adm4": "21.71.03.1001", "name": "Belakang Padang", "lat": 1.0833, "lon": 104.0833},
        {"adm4": "21.71.04.1001", "name": "Bulang", "lat": 0.9667, "lon": 104.2500},
        {"adm4": "21.71.05.1001", "name": "Galang", "lat": 0.8333, "lon": 104.2500},
        {"adm4": "21.71.06.1001", "name": "Nongsa", "lat": 1.1833, "lon": 104.1500},
        {"adm4": "21.71.07.1001", "name": "Sagulung", "lat": 1.1000, "lon": 104.0500},
        {"adm4": "21.71.08.1001", "name": "Sei Beduk", "lat": 1.1500, "lon": 104.0000},
        {"adm4": "21.71.09.1001", "name": "Sekupang", "lat": 1.1333, "lon": 103.9833},
        {"adm4": "21.71.10.1001", "name": "Batu Aji", "lat": 1.0833, "lon": 104.0167},
        {"adm4": "21.71.11.1001", "name": "Lubuk Baja", "lat": 1.0500, "lon": 104.0167},
        {"adm4": "21.71.12.1001", "name": "Bengkong", "lat": 1.0167, "lon": 103.9833},
    ],
    "tanjung_pinang": [
        {"adm4": "21.72.01.1001", "name": "Tanjung Pinang Barat", "lat": 0.9167, "lon": 104.4500},
        {"adm4": "21.72.02.1001", "name": "Tanjung Pinang Timur", "lat": 0.9333, "lon": 104.4833},
        {"adm4": "21.72.03.1001", "name": "Tanjung Pinang Kota", "lat": 0.9167, "lon": 104.4500},
        {"adm4": "21.72.04.1001", "name": "Bukit Bestari", "lat": 0.9333, "lon": 104.4667},
    ],
    "karimun": [
        {"adm4": "21.02.02.1001", "name": "Kundur", "lat": 0.5833, "lon": 103.4167},
        {"adm4": "21.02.03.1001", "name": "Moro", "lat": 0.6667, "lon": 103.4167},
        {"adm4": "21.02.04.1001", "name": "Meral", "lat": 0.7833, "lon": 103.5000},
        {"adm4": "21.02.05.1001", "name": "Tebing", "lat": 0.7167, "lon": 103.3833},
    ],
    "dumai": [
        {"adm4": "14.71.02.1001", "name": "Dumai Timur", "lat": 1.6833, "lon": 101.4667},
        {"adm4": "14.71.03.1001", "name": "Medang Kampai", "lat": 1.7167, "lon": 101.4833},
        {"adm4": "14.71.04.1001", "name": "Bukit Kapur", "lat": 1.7167, "lon": 101.4167},
        {"adm4": "14.71.05.1001", "name": "Sungai Sembilan", "lat": 1.7833, "lon": 101.4333},
    ],
    "coastal_riau": [
        {"adm4": "14.03.01.1001", "name": "Bagansiapiapi", "lat": 1.4833, "lon": 100.8167, "region": "rokan_hilir"},
        {"adm4": "14.04.01.1001", "name": "Siak Sri Indrapura", "lat": 0.8000, "lon": 102.0167, "region": "siak"},
        {"adm4": "14.06.01.1001", "name": "Pangkalan Kerinci", "lat": 0.4000, "lon": 101.6833, "region": "pelalawan"},
        {"adm4": "14.08.01.1001", "name": "Rengat", "lat": -0.3833, "lon": 102.5667, "region": "indragiri_hulu"},
    ],
}

_ALL_BMKG_LOCATIONS = []
for group_name, locations in BMKG_LOCATIONS.items():
    for loc in locations:
        loc_copy = loc.copy()
        loc_copy["group"] = group_name
        _ALL_BMKG_LOCATIONS.append(loc_copy)


_BMKG_FALLBACK_FIXTURE = {
    "groups": {
        "batam": {"name": "Batam", "locations": []},
        "tanjung_pinang": {"name": "Tanjung Pinang", "locations": []},
        "karimun": {"name": "Karimun", "locations": []},
        "dumai": {"name": "Dumai", "locations": []},
        "coastal_riau": {"name": "Coastal Riau", "locations": []},
    },
    "source": "offline_fixture:BMKG_forecast",
    "is_live": False,
}


@dataclass
class SumatraLocationForecast:
    group: str
    location: str
    adm4: str
    latitude: float
    longitude: float
    forecast_time_local: str
    weather_condition: str
    temperature_c: Optional[float]
    humidity_pct: Optional[float]
    wind_speed_ms: Optional[float]
    wind_direction: str
    cloud_cover_pct: Optional[float]
    rainfall_mm: Optional[float]
    source: str


@dataclass
class SumatraGroupSummary:
    group_name: str
    group_key: str
    locations_reporting: int
    locations_total: int
    max_rainfall_mm: Optional[float]
    has_rain: Optional[bool]
    representative_weather: str
    dominant_wind_direction: str
    avg_wind_speed_ms: Optional[float]
    max_cloud_cover_pct: Optional[float]
    latest_forecast_time: str
    locations: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SumatraForecastSnapshot:
    snapshot_at: str
    source: str
    provider: str
    endpoint: str
    unit: str
    is_live: bool
    error: Optional[str] = None
    groups: Dict[str, SumatraGroupSummary] = field(default_factory=dict)
    partial: bool = False
    failed_locations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "unit": self.unit,
            "is_live": self.is_live,
            "error": self.error,
            "partial": self.partial,
            "failed_locations": self.failed_locations,
            "groups": {
                k: {
                    "group_name": v.group_name,
                    "group_key": v.group_key,
                    "locations_reporting": v.locations_reporting,
                    "locations_total": v.locations_total,
                    "max_rainfall_mm": v.max_rainfall_mm,
                    "has_rain": v.has_rain,
                    "representative_weather": v.representative_weather,
                    "dominant_wind_direction": v.dominant_wind_direction,
                    "avg_wind_speed_ms": v.avg_wind_speed_ms,
                    "max_cloud_cover_pct": v.max_cloud_cover_pct,
                    "latest_forecast_time": v.latest_forecast_time,
                    "locations": v.locations,
                }
                for k, v in self.groups.items()
            },
        }


class SumatraForecastApiClient:
    def __init__(
        self,
        base_url: str = _BMKG_BASE_URL,
        offline: bool = False,
        timeout: float = _BMKG_TIMEOUT,
    ) -> None:
        self.base_url = base_url
        self.offline = offline
        self.timeout = timeout

    def fetch(self) -> SumatraForecastSnapshot:
        key = (self.base_url.rstrip("/"), self.offline,
               tuple(str(loc["adm4"]) for loc in _ALL_BMKG_LOCATIONS))
        return _SUMATRA_CACHE.get_or_fetch(
            key, self._fetch_uncached, ttl_seconds=_SUMATRA_CACHE_TTL_S,
            error_ttl_seconds=_SUMATRA_FAILURE_TTL_S,
            cache_result=lambda snapshot: bool(snapshot.is_live and snapshot.groups) or self.offline,
        )

    def _fetch_uncached(self) -> SumatraForecastSnapshot:
        if self.offline:
            log.info("Sumatra forecast adapter offline=True; using fallback fixture.")
            return self._normalize(_BMKG_FALLBACK_FIXTURE, is_live=False, source="offline_fixture:BMKG_forecast")

        all_forecasts = []
        failed_locations = []

        # Every location creates its own httpx.Client in _fetch_location, so
        # requests can run concurrently without sharing a session. The worker
        # cap bounds provider load and thread usage.
        with ThreadPoolExecutor(max_workers=_SUMATRA_MAX_WORKERS) as pool:
            futures = {pool.submit(self._fetch_location, loc): loc for loc in _ALL_BMKG_LOCATIONS}
            for future in as_completed(futures):
                loc = futures[future]
                try:
                    forecast = future.result()
                    if forecast:
                        all_forecasts.append(forecast)
                    else:
                        failed_locations.append(loc["adm4"])
                except Exception as e:
                    log.warning("BMKG fetch failed for %s: %s", loc["adm4"], e)
                    failed_locations.append(loc["adm4"])

        if not all_forecasts and not self.offline:
            error_msg = f"BMKG API unavailable for all locations (failed: {len(failed_locations)})"
            log.warning(error_msg)
            return SumatraForecastSnapshot(
                snapshot_at=_now_iso(),
                source="error:BMKG_forecast",
                provider="BMKG / api.bmkg.go.id",
                endpoint=f"{self.base_url}?adm4={{ADM4}}",
                unit="mm",
                is_live=False,
                error=error_msg,
            )

        groups = self._aggregate_by_group(all_forecasts)

        source = "live_api:BMKG_forecast" if all_forecasts else "offline_fixture:BMKG_forecast"
        return SumatraForecastSnapshot(
            snapshot_at=_now_iso(),
            source=source,
            provider="BMKG / api.bmkg.go.id",
            endpoint=f"{self.base_url}?adm4={{ADM4}}",
            unit="mm",
            is_live=bool(all_forecasts),
            error=None,
            groups=groups,
            partial=bool(failed_locations),
            failed_locations=sorted(failed_locations),
        )

    def _fetch_location(self, loc: Dict[str, Any]) -> Optional[SumatraLocationForecast]:
        url = f"{self.base_url}?adm4={loc['adm4']}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url)
                if resp.status_code != 200:
                    log.debug(f"BMKG 404 for {loc['adm4']}: {loc['name']}")
                    return None
                data = resp.json()
        except Exception as e:
            log.warning(f"BMKG fetch failed for {loc['adm4']}: {e}")
            return None

        try:
            weather_data = data.get("data", [])
            if not weather_data:
                return None

            day = weather_data[0]
            cuaca_list = day.get("cuaca", [])
            if not cuaca_list or not cuaca_list[0]:
                return None

            first_forecast = cuaca_list[0][0]

            forecast_time = self._parse_timestamp(first_forecast.get("local_datetime"))

            return SumatraLocationForecast(
                group=loc["group"],
                location=loc["name"],
                adm4=loc["adm4"],
                latitude=loc["lat"],
                longitude=loc["lon"],
                forecast_time_local=forecast_time,
                weather_condition=first_forecast.get("weather_desc", "Unknown"),
                temperature_c=first_forecast.get("t"),
                humidity_pct=first_forecast.get("hu"),
                wind_speed_ms=first_forecast.get("ws"),
                wind_direction=first_forecast.get("wd", ""),
                cloud_cover_pct=first_forecast.get("tcc"),
                rainfall_mm=first_forecast.get("tp"),
                source="live_api:BMKG_forecast",
            )
        except Exception as e:
            log.warning(f"Failed to parse BMKG response for {loc['adm4']}: {e}")
            return None

    def _parse_timestamp(self, ts_str: Optional[str]) -> str:
        if not ts_str:
            return "N/A"
        try:
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=WIB_OFFSET)
            return dt.astimezone(SG_OFFSET).isoformat()
        except Exception:
            return "N/A"

    def _aggregate_by_group(self, forecasts: List[SumatraLocationForecast]) -> Dict[str, SumatraGroupSummary]:
        group_data: Dict[str, List[SumatraLocationForecast]] = {}
        for fc in forecasts:
            group_data.setdefault(fc.group, []).append(fc)

        summaries = {}
        for group_name, forecasts_list in group_data.items():
            if not forecasts_list:
                continue

            total = len(BMKG_LOCATIONS.get(group_name, []))
            reporting = len(forecasts_list)

            rainfalls = [f.rainfall_mm for f in forecasts_list if f.rainfall_mm is not None]
            max_rain = max(rainfalls) if rainfalls else None
            has_rain = any(r > 0 for r in rainfalls) if rainfalls else None

            weather_conditions = [f.weather_condition for f in forecasts_list if f.weather_condition]
            representative = max(set(weather_conditions), key=weather_conditions.count) if weather_conditions else "Unknown"

            wind_directions = [f.wind_direction for f in forecasts_list if f.wind_direction]
            wind_speeds = [f.wind_speed_ms for f in forecasts_list if f.wind_speed_ms is not None]
            dominant_wind = max(set(wind_directions), key=wind_directions.count) if wind_directions else "N/A"
            avg_wind = sum(wind_speeds) / len(wind_speeds) if wind_speeds else None

            clouds = [f.cloud_cover_pct for f in forecasts_list if f.cloud_cover_pct is not None]
            max_cloud = max(clouds) if clouds else None

            times = [f.forecast_time_local for f in forecasts_list if f.forecast_time_local != "N/A"]
            latest_time = max(times) if times else "N/A"

            loc_details = [
                {
                    "name": f.location,
                    "adm4": f.adm4,
                    "lat": f.latitude,
                    "lon": f.longitude,
                    "rainfall_mm": f.rainfall_mm,
                    "weather": f.weather_condition,
                    "wind_speed_ms": f.wind_speed_ms,
                    "wind_direction": f.wind_direction,
                    "cloud_cover_pct": f.cloud_cover_pct,
                    "forecast_time": f.forecast_time_local,
                }
                for f in forecasts_list
            ]

            summaries[group_name] = SumatraGroupSummary(
                group_name=group_name.replace("_", " ").title(),
                group_key=group_name,
                locations_reporting=reporting,
                locations_total=total,
                max_rainfall_mm=max_rain,
                has_rain=has_rain,
                representative_weather=representative,
                dominant_wind_direction=dominant_wind,
                avg_wind_speed_ms=round(avg_wind, 1) if avg_wind is not None else None,
                max_cloud_cover_pct=max_cloud,
                latest_forecast_time=latest_time,
                locations=loc_details,
            )

        return summaries

    def _normalize(self, payload: Dict[str, Any], is_live: bool, source: str) -> SumatraForecastSnapshot:
        return SumatraForecastSnapshot(
            snapshot_at=_now_iso(),
            source=source,
            provider="BMKG / api.bmkg.go.id",
            endpoint=f"{_BMKG_BASE_URL}?adm4={{ADM4}}",
            unit="mm",
            is_live=is_live,
            groups=payload.get("groups", {}),
        )


# ---------- Helper functions used by Flood Agent ----------
def get_sumatra_forecast_evidence(client: SumatraForecastApiClient) -> Dict[str, Any]:
    snapshot = client.fetch()
    valid_groups = [g for g in snapshot.groups.values() if g.max_rainfall_mm is not None]

    if not snapshot.is_live or snapshot.error or not valid_groups:
        return {
            "available": False,
            "source": snapshot.source,
            "error": snapshot.error or "No valid live rainfall values",
            "groups": {},
            "has_rain": None,
            "max_rainfall_mm": None,
            "weather_systems": [],
        }

    all_rainfalls = []
    weather_systems = []
    has_rain_any = False

    for group_key, group in snapshot.groups.items():
        if group.has_rain:
            has_rain_any = True
        if group.max_rainfall_mm is not None and group.max_rainfall_mm > 0:
            all_rainfalls.append(group.max_rainfall_mm)
        if group.max_rainfall_mm is not None and group.max_rainfall_mm > 30:
            weather_systems.append(f"heavy_rain_{group_key}")
        if "Hujan" in group.representative_weather or "Rain" in group.representative_weather:
            weather_systems.append(f"rain_{group_key}")

    batam = snapshot.groups.get("batam")
    karimun = snapshot.groups.get("karimun")
    dumai = snapshot.groups.get("dumai")
    coastal = snapshot.groups.get("coastal_riau")

    squall_score = 0
    if batam and batam.has_rain:
        squall_score += 1
    if karimun and karimun.has_rain:
        squall_score += 1
    if dumai and dumai.has_rain:
        squall_score += 1
    if coastal and coastal.has_rain:
        squall_score += 1

    if squall_score >= 2:
        weather_systems.append("possible_sumatra_squall")

    return {
        "available": True,
        "partial": snapshot.partial,
        "failed_locations": snapshot.failed_locations,
        "source": snapshot.source,
        "groups": {
            k: {
                "group_name": v.group_name,
                "locations_reporting": v.locations_reporting,
                "locations_total": v.locations_total,
                "max_rainfall_mm": v.max_rainfall_mm,
                "has_rain": v.has_rain,
                "representative_weather": v.representative_weather,
                "dominant_wind_direction": v.dominant_wind_direction,
                "avg_wind_speed_ms": v.avg_wind_speed_ms,
                "max_cloud_cover_pct": v.max_cloud_cover_pct,
                "latest_forecast_time": v.latest_forecast_time,
                "locations": v.locations,
            }
            for k, v in snapshot.groups.items()
        },
        "has_rain": any(g.has_rain is True for g in valid_groups),
        "max_rainfall_mm": max(all_rainfalls) if all_rainfalls else 0.0,
        "weather_systems": list(set(weather_systems)),
    }


# ---------- Timestamp helpers ----------
def _nea_to_iso(s: Optional[str]) -> str:
    if not s:
        return _now_iso()
    s2 = s.strip()
    if s2.endswith("+08:0"):
        s2 = s2[:-1] + "0"
    if s2.endswith("Z"):
        try:
            dt = datetime.fromisoformat(s2[:-1]).replace(tzinfo=timezone.utc)
            return dt.astimezone(SG_OFFSET).isoformat()
        except Exception:
            return s2
    if "+" in s2[10:] or s2[10:].count("-") > 0:
        try:
            dt = datetime.fromisoformat(s2)
            return dt.astimezone(SG_OFFSET).isoformat()
        except Exception:
            return s2
    try:
        dt = datetime.fromisoformat(s2).replace(tzinfo=SG_OFFSET)
        return dt.isoformat()
    except Exception:
        return s2


def _to_iso_sg(ts_str: str) -> str:
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
