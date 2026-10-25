"""Official Construction data acquisition from data.gov.sg APIs. No synthetic fallback values."""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any
from backend.app.upstream import SingleFlightTTLCache, retry_429_delay

log = logging.getLogger(__name__)
SG = timezone(timedelta(hours=8))
BASE = "https://api-production.data.gov.sg/v2/public/api/datasets"

# Retry configuration for rate-limited requests
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 30.0
_SOURCE_CACHE = SingleFlightTTLCache()
_SOURCE_TTL_SECONDS = 1800.0
_SOURCE_ERROR_TTL_SECONDS = 30.0

# Dataset IDs from data.gov.sg
DATASETS = {
    "greenmark_buildings": {
        "id": "d_c4bd082b48fa7611713f39e23d250c27",
        "name": "Green Mark Buildings",
        "agency": "BCA",
        "url": "https://data.gov.sg/datasets/d_c4bd082b48fa7611713f39e23d250c27/view",
        "description": "Green Mark certified buildings with certification rating, dates, and building details.",
    },
    "ura_construction_pipeline": {
        "id": "d_38ed343cc32c3e0b6ebc43a6058e9860",
        "name": "Approval, Construction Commencement & Completion of Private Residential Properties, Annual",
        "agency": "URA",
        "url": "https://data.gov.sg/datasets/d_38ed343cc32c3e0b6ebc43a6058e9860/view",
        "description": "Annual residential construction pipeline: provisional permission, written permission, building plan approval, commencement, completion.",
    },
    "greenmark_geojson": {
        "id": "d_da116ef216e3fb501846e1c9faf7e683",
        "name": "Green Mark Buildings (GEOJSON)",
        "agency": "BCA",
        "url": "https://data.gov.sg/datasets/d_da116ef216e3fb501846e1c9faf7e683/view",
        "description": "Geospatial dataset of Green Mark certified buildings.",
    },
    "building_energy": {
        "id": "d_16e7a5921aef24f610f808b16d1480ce",
        "name": "Building Energy Performance Data for Commercial Buildings",
        "agency": "BCA",
        "url": "https://data.gov.sg/datasets/d_16e7a5921aef24f610f808b16d1480ce/view",
        "description": "Historical building energy performance data (2018 coverage only).",
    },
}


@dataclass
class SourceResult:
    key: str
    name: str
    agency: str
    url: str
    status: str
    records: list[dict[str, Any]] = field(default_factory=list)
    retrieved_at: str | None = None
    error: str | None = None
    fields: list[str] = field(default_factory=list)
    total_count: int | None = None
    coverage_start: str | None = None
    coverage_end: str | None = None
    last_updated_at: str | None = None


def _fetch_with_retry(req: urllib.request.Request, timeout: int = 30) -> dict:
    """Fetch URL with exponential backoff retry on rate limit (HTTP 429)."""
    last_exception = None
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                content = response.read().decode("utf-8")
                if not content.strip():
                    raise ValueError("Empty response from API")
                return json.loads(content)
        except urllib.error.HTTPError as exc:
            last_exception = exc
            backoff = retry_429_delay(exc, attempt, base_seconds=BASE_BACKOFF_SECONDS,
                                       max_seconds=MAX_BACKOFF_SECONDS)
            if backoff is not None and attempt < MAX_RETRIES - 1:
                log.warning("Rate limited (HTTP 429) on attempt %d/%d, backing off %.1fs",
                           attempt + 1, MAX_RETRIES, backoff)
                time.sleep(backoff)
                continue
            raise
        except json.JSONDecodeError as exc:
            last_exception = exc
            if attempt < MAX_RETRIES - 1:
                backoff = min(BASE_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)
                log.warning("JSON decode error on attempt %d/%d: %s, backing off %.1fs",
                           attempt + 1, MAX_RETRIES, exc, backoff)
                time.sleep(backoff)
                continue
            raise
        except Exception as exc:
            last_exception = exc
            if attempt < MAX_RETRIES - 1:
                backoff = min(BASE_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)
                log.warning("Request failed on attempt %d/%d: %s, backing off %.1fs",
                           attempt + 1, MAX_RETRIES, exc, backoff)
                time.sleep(backoff)
                continue
            raise
    raise last_exception


def _fetch_dataset_uncached(key: str, limit: int = 5000) -> SourceResult:
    spec = DATASETS[key]
    all_records: list[dict[str, Any]] = []
    offset = 0
    headers = {"Accept": "application/json", "User-Agent": "UrbanOS-Construction/1.0"}
    api_key = os.getenv("DATA_GOV_SG_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    dataset_id = spec["id"]
    coverage_start = None
    coverage_end = None
    last_updated_at = None
    total_count = None

    while True:
        params = urllib.parse.urlencode({"limit": limit, "offset": offset})
        req = urllib.request.Request(f"{BASE}/{dataset_id}/list-rows?{params}", headers=headers)
        try:
            payload = _fetch_with_retry(req, timeout=30)
        except urllib.error.HTTPError as exc:
            msg = f"HTTP {exc.code}"
            if exc.code == 429:
                msg += " (rate limited)"
            log.warning("Construction dataset %s unavailable: %s", key, msg)
            return SourceResult(key, spec["name"], spec["agency"], spec["url"], "unavailable", error=msg)
        except Exception as exc:
            log.warning("Construction dataset %s unavailable: %s", key, exc)
            return SourceResult(key, spec["name"], spec["agency"], spec["url"], "unavailable", error=str(exc)[:240])

        if not payload.get("success", True) or not isinstance(payload.get("data"), dict):
            if payload.get("code") != 0:
                log.warning("Construction dataset %s returned error: %s", key, payload.get("errorMsg", "Unknown error"))
                return SourceResult(key, spec["name"], spec["agency"], spec["url"], "unavailable", error=payload.get("errorMsg", "API error"))

        data = payload.get("data", {})
        records = data.get("rows") or data.get("results") or []
        if not isinstance(records, list):
            raise ValueError("data.gov.sg records field was not a list")

        all_records.extend(records)

        # Get metadata from first response
        if offset == 0:
            total_count = data.get("total") or len(all_records)
            coverage_start = data.get("coverageStart")
            coverage_end = data.get("coverageEnd")
            last_updated_at = data.get("lastUpdatedAt") or payload.get("data", {}).get("lastUpdatedAt")

        if len(records) < limit:
            break
        offset += limit

    return SourceResult(
        key=key,
        name=spec["name"],
        agency=spec["agency"],
        url=spec["url"],
        status="available" if all_records else "empty",
        records=all_records,
        retrieved_at=datetime.now(SG).isoformat(),
        fields=sorted({str(k) for row in all_records[:10] for k in row.keys()}) if all_records else [],
        total_count=total_count,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        last_updated_at=last_updated_at,
    )


def _fetch_dataset(key: str, limit: int = 5000) -> SourceResult:
    cache_key = ("construction", key, limit)
    return _SOURCE_CACHE.get_or_fetch(
        cache_key,
        lambda: _fetch_dataset_uncached(key, limit),
        ttl_seconds=_SOURCE_TTL_SECONDS,
        error_ttl_seconds=_SOURCE_ERROR_TTL_SECONDS,
        cache_result=lambda result: result.status == "available",
    )


def _fetch_geojson_dataset_uncached(key: str) -> SourceResult:
    """Fetch GeoJSON dataset which may have different structure."""
    spec = DATASETS[key]
    headers = {"Accept": "application/json", "User-Agent": "UrbanOS-Construction/1.0"}
    api_key = os.getenv("DATA_GOV_SG_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    dataset_id = spec["id"]
    req = urllib.request.Request(f"{BASE}/{dataset_id}/list-rows", headers=headers)
    try:
        payload = _fetch_with_retry(req, timeout=30)
    except urllib.error.HTTPError as exc:
        msg = f"HTTP {exc.code}"
        if exc.code == 429:
            msg += " (rate limited)"
        log.warning("Construction GeoJSON dataset %s unavailable: %s", key, msg)
        return SourceResult(key, spec["name"], spec["agency"], spec["url"], "unavailable", error=msg)
    except json.JSONDecodeError as exc:
        log.warning("Construction GeoJSON dataset %s unavailable: JSON decode error: %s", key, exc)
        return SourceResult(key, spec["name"], spec["agency"], spec["url"], "unavailable", error="Invalid JSON response")
    except Exception as exc:
        log.warning("Construction GeoJSON dataset %s unavailable: %s", key, exc)
        return SourceResult(key, spec["name"], spec["agency"], spec["url"], "unavailable", error=str(exc)[:240])

    if not payload.get("success", True) or payload.get("code") != 0:
        return SourceResult(key, spec["name"], spec["agency"], spec["url"], "unavailable", error=payload.get("errorMsg", "API error"))

    data = payload.get("data", {})
    # GeoJSON might have features directly
    features = data.get("features") or data.get("rows") or data.get("results") or []
    if not isinstance(features, list):
        return SourceResult(key, spec["name"], spec["agency"], spec["url"], "empty", records=[])

    # Convert features to flat records
    records = []
    for feat in features:
        if isinstance(feat, dict) and "properties" in feat:
            row = {"geometry": feat.get("geometry")}
            row.update(feat["properties"])
            records.append(row)
        else:
            records.append(feat)

    return SourceResult(
        key=key,
        name=spec["name"],
        agency=spec["agency"],
        url=spec["url"],
        status="available" if records else "empty",
        records=records,
        retrieved_at=datetime.now(SG).isoformat(),
        fields=sorted({str(k) for row in records[:10] for k in row.keys()}) if records else [],
        total_count=len(records),
    )


def _fetch_geojson_dataset(key: str) -> SourceResult:
    cache_key = ("construction", key)
    return _SOURCE_CACHE.get_or_fetch(
        cache_key,
        lambda: _fetch_geojson_dataset_uncached(key),
        ttl_seconds=_SOURCE_TTL_SECONDS,
        error_ttl_seconds=_SOURCE_ERROR_TTL_SECONDS,
        cache_result=lambda result: result.status == "available",
    )


def clear_construction_source_cache() -> None:
    _SOURCE_CACHE.clear(preserve_errors=True)


def fetch_construction_snapshot() -> dict[str, Any]:
    """Fetch selected open construction datasets; preserve per-source failures."""
    sources = {}
    for key in DATASETS:
        if key == "greenmark_geojson":
            sources[key] = _fetch_geojson_dataset(key)
        else:
            sources[key] = _fetch_dataset(key)

    return {
        "generated_at": datetime.now(SG).isoformat(),
        "sources": sources,
        "errors": [f"{s.name}: {s.error}" for s in sources.values() if s.status == "unavailable"],
    }
