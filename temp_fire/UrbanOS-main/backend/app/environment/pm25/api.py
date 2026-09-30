"""NEA Live API adapter for PM2.5 (data.gov.sg /v2/real-time/api/pm25).

Adapter owns ALL per-source quirks (URL, paging, auth, units, timezone,
nulls) per architecture proposal §4. API data is used **only for live
frontend KPI display** — never enters ML training/prediction, never touches
model artifacts.

Spec: docs/api/PM2.5.json  (openapi 3.0.3)
Server: https://api-open.data.gov.sg/v2/real-time/api/pm25
Auth: optional x-api-key header (raises rate limits)
Unit: µg/m3. Regions: north/south/east/west/central (lowercase in payload).
Timestamps: NEA strings carry no offset; treat as Asia/Singapore (+08:00).

This module does NOT depend on network availability for unit tests: pass
`offline=True` (default in tests) to use a deterministic fixture derived from
the spec's documented example values.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

import httpx

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))
_DEFAULT_BASE = "https://api-open.data.gov.sg/v2/real-time/api"
_ENDPOINT = "/pm25"
_TIMEOUT = 8.0

# Deterministic fixture pulled verbatim from the OpenAPI spec example values
# (PM2.5.json lines 138-153). Used only when offline=True OR when network fetch
# fails AND allow_fallback_fixture=True (so KPI endpoints degrade gracefully).
_FALLBACK_FIXTURE = {
    "code": 0,
    "errorMsg": "",
    "data": {
        "regionMetadata": [
            {"name": "West",    "labelLocation": {"latitude": 1.35735, "longitude": 103.7}},
            {"name": "East",    "labelLocation": {"latitude": 1.33,   "longitude": 103.94}},
            {"name": "Central", "labelLocation": {"latitude": 1.30767,"longitude": 103.819}},
            {"name": "South",   "labelLocation": {"latitude": 1.28,   "longitude": 103.82}},
            {"name": "North",   "labelLocation": {"latitude": 1.41891,"longitude": 103.82}},
        ],
        "items": [
            {
                "date": "2024-07-17T00:00:00.000Z",
                "updatedTimestamp": "2024-07-17T14:15:43+08:00",
                "timestamp": "2024-07-17T06:00:00.000Z",
                "readings": {
                    "pm25_one_hourly": {
                        "east": 18, "west": 12, "north": 11, "south": 8, "central": 7,
                    }
                },
            }
        ],
    },
}


@dataclass
class Pm25Reading:
    region: str
    value: float           # µg/m3
    observed_at: str       # ISO +08:00
    source: str            # e.g. "live_api:NEA_pm25" | "offline_fixture:NEA_pm25"


@dataclass
class Pm25LiveSnapshot:
    snapshot_at: str       # ISO +08:00 — when we fetched (or fixture time)
    source: str
    unit: str
    regions: Dict[str, Pm25Reading]
    raw_issue_timestamp: Optional[str]
    raw_updated_timestamp: Optional[str]
    is_live: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": "NEA / data.gov.sg",
            "endpoint": f"{_DEFAULT_BASE}{_ENDPOINT}",
            "unit": self.unit,
            "regions": {
                r: {
                    "region": v.region,
                    "value": v.value,
                    "observed_at": v.observed_at,
                    "source": v.source,
                }
                for r, v in self.regions.items()
            },
            "raw_issue_timestamp": self.raw_issue_timestamp,
            "raw_updated_timestamp": self.raw_updated_timestamp,
            "is_live": self.is_live,
        }


class Pm25ApiClient:
    """Adapter wrapping the NEA PM2.5 real-time endpoint.

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

    def fetch(self, date: Optional[str] = None) -> Pm25LiveSnapshot:
        """Fetch latest (or given date) PM2.5 snapshot.

        date: "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SS" or None for latest.
        """
        payload, is_live = self._get_payload(date)
        return self._normalize(payload, is_live=is_live)

    # ---------------------------------------------------------------- internals

    def _get_payload(self, date: Optional[str]):
        if self.offline:
            log.info("PM2.5 adapter offline=True; using fallback fixture.")
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
            log.warning("PM2.5 live fetch failed: %s", e)
            if self.allow_fallback_fixture:
                log.warning("PM2.5 falling back to deterministic fixture (KPI only).")
                return _FALLBACK_FIXTURE, False
            raise

    def _normalize(self, payload: dict, is_live: bool) -> Pm25LiveSnapshot:
        data = payload.get("data") or {}
        items = data.get("items") or []
        if not items:
            raise ValueError("PM2.5 payload missing data.items")
        latest = items[-1]  # API-most-recent item
        readings = (latest.get("readings") or {}).get("pm25_one_hourly") or {}

        raw_issue = latest.get("timestamp")
        raw_updated = latest.get("updatedTimestamp")
        observed_at = _nea_to_iso(raw_issue)

        regions: Dict[str, Pm25Reading] = {}
        for region_name, val in readings.items():
            r = region_name.lower()
            regions[r] = Pm25Reading(
                region=r,
                value=float(val),
                observed_at=observed_at,
                source=("live_api:NEA_pm25" if is_live else "offline_fixture:NEA_pm25"),
            )

        return Pm25LiveSnapshot(
            snapshot_at=_now_iso(),
            source=("live_api:NEA_pm25" if is_live else "offline_fixture:NEA_pm25"),
            unit="µg/m3",
            regions=regions,
            raw_issue_timestamp=raw_issue,
            raw_updated_timestamp=raw_updated,
            is_live=is_live,
        )


def _nea_to_iso(s: Optional[str]) -> str:
    """Coerce NEA's various timestamp formats to ISO +08:00.

    Examples seen:
        "2024-07-17T14:15:43+08:0"     -> fix to "+08:00"
        "2024-07-17T06:00:00.000Z"     -> Z = UTC; convert to +08:00
    """
    if not s:
        return _now_iso()
    s2 = s.strip()
    # Fix trailing +08:0 -> +08:00
    if s2.endswith("+08:0"):
        s2 = s2[:-1] + "0"
    if s2.endswith("Z"):
        # Treat Z as UTC
        try:
            dt = datetime.fromisoformat(s2[:-1]).replace(tzinfo=timezone.utc)
            return dt.astimezone(SG_OFFSET).isoformat()
        except Exception:
            return s2
    # Already has explicit offset (now fixed)
    if "+" in s2[10:] or s2[10:].count("-") > 0:
        try:
            dt = datetime.fromisoformat(s2)
            return dt.astimezone(SG_OFFSET).isoformat()
        except Exception:
            return s2
    # No tz token: assume +08:00 (spec says SGT)
    try:
        dt = datetime.fromisoformat(s2).replace(tzinfo=SG_OFFSET)
        return dt.isoformat()
    except Exception:
        return s2


def _now_iso() -> str:
    return datetime.now(SG_OFFSET).isoformat()
