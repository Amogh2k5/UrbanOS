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

from backend.app.environment.weather.air_temperature import (
    AirTemperatureApiClient, AirTemperatureSnapshot, aggregate_city_temperature, aggregate_regional_temperatures
)

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))
_DEFAULT_BASE = "https://api-open.data.gov.sg/v2/real-time/api"
_ENDPOINT = "/twenty-four-hr-forecast"
_TIMEOUT = 8.0

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
