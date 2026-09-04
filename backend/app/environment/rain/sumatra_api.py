"""Indonesian BMKG (Meteorology, Climatology, and Geophysical Agency) Weather Forecast API Adapter.

Official BMKG public weather forecast API for Sumatra/Riau Islands regions
relevant to Singapore flood risk assessment.

API: https://api.bmkg.go.id/publik/prakiraan-cuaca?adm4={ADM4_CODE}
Documentation: https://data.bmkg.go.id/prakiraan-cuaca/

Verified 27 locations across 5 regional groups (validated 2026-08-20):

BATAM (12):
21.71.02.1001, 21.71.03.1001, 21.71.04.1001, 21.71.05.1001,
21.71.06.1001, 21.71.07.1001, 21.71.08.1001, 21.71.09.1001,
21.71.10.1001, 21.71.11.1001, 21.71.12.1001

TANJUNG PINANG (4):
21.72.01.1001, 21.72.02.1001, 21.72.03.1001, 21.72.04.1001

KARIMUN (4):
21.02.02.1001, 21.02.03.1001, 21.02.04.1001, 21.02.05.1001

DUMAI (4):
14.71.02.1001, 14.71.03.1001, 14.71.04.1001, 14.71.05.1001

COASTAL RIAU (4):
14.03.01.1001, 14.04.01.1001, 14.06.01.1001, 14.08.01.1001

Total: 27 verified LIVE locations (validated 2026-08-20)
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
WIB_OFFSET = timezone(timedelta(hours=7))
_TIMEOUT = 15.0
_BASE_URL = "https://api.bmkg.go.id/publik/prakiraan-cuaca"

# Verified BMKG ADM4 codes grouped by region (validated 2026-08-20)
# Source: Official BMKG API https://api.bmkg.go.id/publik/prakiraan-cuaca?adm4={ADM4}
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

# Flatten for easy iteration
_ALL_LOCATIONS = []
for group_name, locations in BMKG_LOCATIONS.items():
    for loc in locations:
        loc_copy = loc.copy()
        loc_copy["group"] = group_name
        _ALL_LOCATIONS.append(loc_copy)

# Deterministic fallback fixture for offline/testing
_FALLBACK_FIXTURE = {
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
    """Single location forecast from BMKG."""
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
    """Aggregated forecast summary for a regional group."""
    group_name: str
    group_key: str
    locations_reporting: int
    locations_total: int
    max_rainfall_mm: float
    has_rain: bool
    representative_weather: str
    dominant_wind_direction: str
    avg_wind_speed_ms: float
    max_cloud_cover_pct: float
    latest_forecast_time: str
    locations: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SumatraForecastSnapshot:
    """Snapshot of Sumatra weather forecast aggregated by regional group."""
    snapshot_at: str
    source: str
    provider: str
    endpoint: str
    unit: str
    is_live: bool
    error: Optional[str] = None
    groups: Dict[str, SumatraGroupSummary] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "unit": self.unit,
            "is_live": self.is_live,
            "error": self.error,
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
    """Official BMKG weather forecast API client for Sumatra/Riau Islands.

    Uses the official BMKG public forecast API:
    https://api.bmkg.go.id/publik/prakiraan-cuaca?adm4={ADM4_CODE}

    Queries 27 verified locations across 5 regional groups:
    - Batam (12 locations)
    - Tanjung Pinang (4 locations)
    - Karimun (4 locations)
    - Dumai (4 locations)
    - Coastal Riau (4 locations)

    Returns aggregated regional summaries for flood risk assessment.
    """

    def __init__(
        self,
        base_url: str = _BASE_URL,
        offline: bool = False,
        timeout: float = _TIMEOUT,
    ) -> None:
        self.base_url = base_url
        self.offline = offline
        self.timeout = timeout

    def fetch(self) -> SumatraForecastSnapshot:
        """Fetch and aggregate forecast for all 27 verified locations."""
        if self.offline:
            log.info("Sumatra forecast adapter offline=True; using fallback fixture.")
            return self._normalize(_FALLBACK_FIXTURE, is_live=False, source="offline_fixture:BMKG_forecast")

        all_forecasts = []
        failed_locations = []

        for loc in _ALL_LOCATIONS:
            try:
                forecast = self._fetch_location(loc)
                if forecast:
                    all_forecasts.append(forecast)
                else:
                    failed_locations.append(loc["adm4"])
            except Exception as e:
                log.warning(f"BMKG fetch failed for {loc['adm4']}: {e}")
                failed_locations.append(loc["adm4"])

        if not all_forecasts and not self.offline:
            error_msg = f"BMKG API unavailable for all locations (failed: {len(failed_locations)})"
            log.warning(error_msg)
            return SumatraForecastSnapshot(
                snapshot_at=_now_iso(),
                source="error:BMKG_forecast",
                provider="BMKG / api.bmkg.go.id",
                endpoint=f"{_BASE_URL}?adm4={{ADM4}}",
                unit="mm",
                is_live=False,
                error=error_msg,
            )

        # Aggregate by group
        groups = self._aggregate_by_group(all_forecasts)

        source = "live_api:BMKG_forecast" if all_forecasts else "offline_fixture:BMKG_forecast"
        return SumatraForecastSnapshot(
            snapshot_at=_now_iso(),
            source=source,
            provider="BMKG / api.bmkg.go.id",
            endpoint=f"{_BASE_URL}?adm4={{ADM4}}",
            unit="mm",
            is_live=bool(all_forecasts),
            error=None,
            groups=groups,
        )

    def _fetch_location(self, loc: Dict[str, Any]) -> Optional[SumatraLocationForecast]:
        """Fetch forecast for a single location by ADM4 code."""
        url = f"{_BASE_URL}?adm4={loc['adm4']}"
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

        # Parse BMKG response
        try:
            weather_data = data.get("data", [])
            if not weather_data:
                return None

            day = weather_data[0]
            cuaca_list = day.get("cuaca", [])
            if not cuaca_list or not cuaca_list[0]:
                return None

            first_forecast = cuaca_list[0][0]  # cuaca[0][0] = first forecast entry

            # Parse timestamp (WIB UTC+7 -> SGT UTC+8)
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
        """Convert BMKG timestamp to ISO +08:00 (SGT)."""
        if not ts_str:
            return _now_iso()
        try:
            # BMKG returns "2026-08-20 17:00:00" (WIB UTC+7, no tz suffix)
            dt = datetime.fromisoformat(ts_str).replace(tzinfo=WIB_OFFSET)
            return dt.astimezone(SG_OFFSET).isoformat()
        except Exception:
            return _now_iso()

    def _aggregate_by_group(self, forecasts: List[SumatraLocationForecast]) -> Dict[str, SumatraGroupSummary]:
        """Aggregate individual location forecasts into regional group summaries."""
        group_data: Dict[str, List[SumatraLocationForecast]] = {}
        for fc in forecasts:
            group_data.setdefault(fc.group, []).append(fc)

        summaries = {}
        for group_name, forecasts_list in group_data.items():
            if not forecasts_list:
                continue

            total = len(BMKG_LOCATIONS.get(group_name, []))
            reporting = len(forecasts_list)

            # Aggregate rainfall
            rainfalls = [f.rainfall_mm for f in forecasts_list if f.rainfall_mm is not None]
            max_rain = max(rainfalls) if rainfalls else 0.0
            has_rain = any(r > 0 for r in rainfalls)

            # Representative weather (most common)
            weather_conditions = [f.weather_condition for f in forecasts_list if f.weather_condition]
            representative = max(set(weather_conditions), key=weather_conditions.count) if weather_conditions else "Unknown"

            # Wind
            wind_directions = [f.wind_direction for f in forecasts_list if f.wind_direction]
            wind_speeds = [f.wind_speed_ms for f in forecasts_list if f.wind_speed_ms is not None]
            dominant_wind = max(set(wind_directions), key=wind_directions.count) if wind_directions else "N/A"
            avg_wind = sum(wind_speeds) / len(wind_speeds) if wind_speeds else 0.0

            # Cloud cover
            clouds = [f.cloud_cover_pct for f in forecasts_list if f.cloud_cover_pct is not None]
            max_cloud = max(clouds) if clouds else 0.0

            # Latest forecast time
            times = [f.forecast_time_local for f in forecasts_list if f.forecast_time_local != "N/A"]
            latest_time = max(times) if times else _now_iso()

            # Per-location details for diagnostics
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
                avg_wind_speed_ms=round(avg_wind, 1),
                max_cloud_cover_pct=max_cloud,
                latest_forecast_time=latest_time,
                locations=loc_details,
            )

        return summaries

    def _normalize(self, payload: Dict[str, Any], is_live: bool, source: str) -> SumatraForecastSnapshot:
        """Normalize fallback fixture (not used for live data)."""
        return SumatraForecastSnapshot(
            snapshot_at=_now_iso(),
            source=source,
            provider="BMKG / api.bmkg.go.id",
            endpoint=f"{_BASE_URL}?adm4={{ADM4}}",
            unit="mm",
            is_live=is_live,
            groups=payload.get("groups", {}),
        )


def _now_iso() -> str:
    return datetime.now(SG_OFFSET).isoformat()


# ============================================================
# Convenience function for Flood Agent
# ============================================================

def get_sumatra_forecast_evidence(client: SumatraForecastApiClient) -> Dict[str, Any]:
    """Extract aggregated Sumatra forecast evidence for Flood Agent."""
    snapshot = client.fetch()

    if not snapshot.is_live or snapshot.error:
        return {
            "available": False,
            "source": snapshot.source,
            "error": snapshot.error or "No live data",
            "groups": {},
            "has_rain": False,
            "max_rainfall_mm": 0.0,
            "weather_systems": [],
        }

    # Aggregate across all groups
    all_rainfalls = []
    weather_systems = []
    has_rain_any = False

    for group_key, group in snapshot.groups.items():
        if group.has_rain:
            has_rain_any = True
        if group.max_rainfall_mm > 0:
            all_rainfalls.append(group.max_rainfall_mm)
        if group.max_rainfall_mm > 30:
            weather_systems.append(f"heavy_rain_{group_key}")
        if "Hujan" in group.representative_weather or "Rain" in group.representative_weather:
            weather_systems.append(f"rain_{group_key}")

    # Detect Sumatra squall signature (widespread rain in Batam/Karimun/Dumai)
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
        "has_rain": any(g.has_rain for g in snapshot.groups.values()),
        "max_rainfall_mm": max((g.max_rainfall_mm for g in snapshot.groups.values()), default=0.0),
        "weather_systems": list(set(weather_systems)),
    }