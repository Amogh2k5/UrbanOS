"""NEA Live API adapter for 5-minute rainfall observations.

Adapter owns ALL per-source quirks (URL, paging, auth, units, timezone,
nulls) per architecture proposal §4. API data is used **only for live
frontend KPI display** — never enters ML training/prediction, never touches
model artifacts.

Spec: NEA Rainfall 5-min API / data.gov.sg
Server: https://api-open.data.gov.sg/v2/real-time/api/rainfall
Auth: optional x-api-key header
Units: mm per 5-min interval. Timestamps: ISO with +08:00 offset.
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
_ENDPOINT = "/rainfall"
_TIMEOUT = 10.0

# Deterministic fixture derived from the NEA 5-min rainfall spec structure.
# Used for offline/testing and as a graceful degradation fallback for the
# live KPI endpoint (NOTHING here enters ML).
# Matches the actual API response format: data.stations + data.readings[].data[]
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
    """Single station rainfall reading."""
    station_id: str
    station_name: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    value_mm: float
    unit: str
    observed_at: str  # ISO +08:00
    source: str


@dataclass
class RainfallSnapshot:
    """Snapshot of rainfall readings at a point in time."""
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
    """Adapter wrapping the NEA 5-min rainfall real-time endpoint.

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

    def fetch(self, date: Optional[str] = None) -> RainfallSnapshot:
        """Fetch latest (or given date) rainfall snapshot.

        date: "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SS" or None for latest.
        """
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
        url = f"{self.base_url}{_ENDPOINT}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                return resp.json(), True
        except Exception as e:
            log.warning("Rainfall live fetch failed: %s", e)
            if self.allow_fallback_fixture:
                log.warning("Rainfall falling back to deterministic fixture (KPI only).")
                return _FALLBACK_FIXTURE, False
            raise

    def _normalize(self, payload: dict, is_live: bool) -> RainfallSnapshot:
        data = payload.get("data") or {}
        stations = data.get("stations") or []
        readings_list = data.get("readings") or []
        
        if not readings_list:
            raise ValueError("Rainfall payload missing data.readings")

        # The API returns readings as a list with one element (latest reading)
        latest_reading = readings_list[0] if readings_list else {}
        readings_raw = latest_reading.get("data") or []
        raw_issue = latest_reading.get("timestamp")

        # Build station metadata lookup
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
            endpoint=f"{self.base_url}{_ENDPOINT}",
            unit="mm",
            readings=readings,
            is_live=is_live,
        )


def _nea_to_iso(s: Optional[str]) -> str:
    """Coerce NEA timestamp formats to ISO +08:00."""
    if not s:
        return _now_iso()
    s2 = s.strip()
    # Fix trailing +08:0 -> +08:00
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


def _now_iso() -> str:
    return datetime.now(SG_OFFSET).isoformat()


# ============================================================
# Historical / offline rainfall aggregation (for Flood Agent)
# ============================================================

def aggregate_rainfall_from_csv(
    csv_path: str,
    target_time: datetime,
    stations: Optional[List[str]] = None,
    windows_minutes: tuple = (15, 60, 180, 360, 1440),
) -> Dict[str, Any]:
    """Aggregate historical 5-min rainfall into rolling windows for a target time.

    Args:
        csv_path: Path to NEA 5-min rainfall CSV (e.g. nea_rainfall_2024.csv)
        target_time: Timezone-aware datetime (Asia/Singapore) to compute windows up to
        stations: Optional list of station_ids to include (None = all)
        windows_minutes: Rolling windows in minutes (default: 15m, 1h, 3h, 6h, 24h)

    Returns:
        Dict with per-station and spatial aggregates:
        {
            "target_time": ISO string,
            "stations": {station_id: {window_min: value_mm, ...}, ...},
            "spatial": {
                "max_15m": float,
                "max_1h": float,
                "max_3h": float,
                "max_6h": float,
                "max_24h": float,
                "stations_reporting": int,
                "stations_with_rain": int,
            },
            "peak_5m": float,
            "nearest_to_alerts": {},  # placeholder for zone-specific queries
        }
    """
    import pandas as pd

    # Read CSV (sample first few rows to check columns, then read full if needed)
    df = pd.read_csv(csv_path)

    # Parse timestamps (already ISO with +08:00 in CSV)
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("Asia/Singapore")

    # Filter to target date
    target_date = target_time.date()
    df = df[df["ts"].dt.date == target_date].copy()

    if df.empty:
        return _empty_rainfall_result(target_time)

    # Filter stations if specified
    if stations:
        df = df[df["station_id"].isin(stations)]

    # Sort by station and time
    df = df.sort_values(["station_id", "ts"]).reset_index(drop=True)

    # Convert reading_value to numeric
    df["reading_value"] = pd.to_numeric(df["reading_value"], errors="coerce").fillna(0.0)

    # Ensure target_time is tz-aware
    if target_time.tzinfo is None:
        target_time = target_time.replace(tzinfo=SG_OFFSET)
    target_ts = pd.Timestamp(target_time)

    result_stations = {}
    all_window_values = {w: [] for w in windows_minutes}
    peak_5m_values = []

    for station_id, group in df.groupby("station_id"):
        # Filter to readings up to target_time
        group = group[group["ts"] <= target_ts].copy()
        if group.empty:
            continue

        # 5-min values
        vals_5m = group["reading_value"].values
        peak_5m = float(vals_5m.max()) if len(vals_5m) > 0 else 0.0
        peak_5m_values.append(peak_5m)

        # Rolling sums for each window
        station_windows = {}
        for w in windows_minutes:
            # Number of 5-min intervals in window
            n_intervals = w // 5
            if len(vals_5m) >= n_intervals:
                window_sum = float(vals_5m[-n_intervals:].sum())
            else:
                window_sum = float(vals_5m.sum())
            station_windows[w] = window_sum
            all_window_values[w].append(window_sum)

        # Get station metadata
        lat = group["location_latitude"].iloc[0] if "location_latitude" in group.columns else None
        lon = group["location_longitude"].iloc[0] if "location_longitude" in group.columns else None

        result_stations[station_id] = {
            "station_id": station_id,
            "station_name": group["station_name"].iloc[0] if "station_name" in group.columns else station_id,
            "latitude": float(lat) if lat is not None and pd.notna(lat) else None,
            "longitude": float(lon) if lon is not None and pd.notna(lon) else None,
            "windows_mm": {f"rainfall_{w//60}h" if w >= 60 else f"rainfall_{w}m": station_windows[w] for w in windows_minutes},
            "peak_5m_mm": peak_5m,
            "intensity_15m_mm_hr": station_windows.get(15, 0) * 4,  # 15-min * 4 = mm/hr
            "intensity_1h_mm_hr": station_windows.get(60, 0),
        }

    # Spatial aggregates
    spatial = {
        f"max_{w//60}h" if w >= 60 else f"max_{w}m": max(all_window_values[w]) if all_window_values[w] else 0.0
        for w in windows_minutes
    }
    spatial["stations_reporting"] = len(result_stations)
    spatial["stations_with_rain"] = sum(1 for s in result_stations.values() if s["windows_mm"].get("rainfall_1h", 0) > 0)

    return {
        "target_time": target_ts.isoformat(),
        "stations": result_stations,
        "spatial": spatial,
        "peak_5m_mm": max(peak_5m_values) if peak_5m_values else 0.0,
        "nearest_to_alerts": {},  # TODO: integrate with zone lookup
        "data_source": "historical_csv:NEA_rainfall_5min",
    }


def _empty_rainfall_result(target_time: datetime) -> Dict[str, Any]:
    if target_time.tzinfo is None:
        target_time = target_time.replace(tzinfo=SG_OFFSET)
    return {
        "target_time": target_time.isoformat(),
        "stations": {},
        "spatial": {
            "max_15m": 0.0,
            "max_1h": 0.0,
            "max_3h": 0.0,
            "max_6h": 0.0,
            "max_24h": 0.0,
            "stations_reporting": 0,
            "stations_with_rain": 0,
        },
        "peak_5m_mm": 0.0,
        "nearest_to_alerts": {},
        "data_source": "historical_csv:NEA_rainfall_5min",
    }


# ============================================================
# Weather system evidence (placeholder for future integration)
# ============================================================

def get_weather_system_evidence(target_time: datetime) -> Dict[str, Any]:
    """Get regional weather system context for flood risk assessment.

    Currently returns empty structure. Future integration points:
    - NEA 24h forecast (already in environment module) for Sumatra squall / monsoon indicators
    - MSS weather warnings API
    - Regional radar/satellite products (if available)
    - Malaysia/Johor weather data (if API available)

    Returns:
        Dict with:
        - systems: list of detected weather systems (e.g., "sumatra_squall", "monsoon_surge")
        - wind_direction: regional wind direction if available
        - regional_precipitation: broader regional context
        - source: data source identifier
        - confidence: "none" | "low" | "medium" | "high"
    """
    return {
        "systems": [],
        "wind_direction": None,
        "regional_precipitation": None,
        "source": "unavailable",
        "confidence": "none",
        "note": "Regional weather system integration not yet implemented. NEA 24h forecast available via environment module.",
    }