"""Official Housing data acquisition. No synthetic fallback values are used."""
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

log = logging.getLogger(__name__)
SG = timezone(timedelta(hours=8))
BASE = "https://data.gov.sg/api/action/datastore_search"

# Retry configuration for rate-limited requests
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 30.0

DATASETS = {
    "median_resale": {
        "id": "d_b51323a474ba789fb4cc3db58a3116d4",
        "name": "Median Resale Prices for Registered Applications by Town and Flat Type",
        "agency": "HDB",
        "period_note": "Quarterly; published dataset currently spans Q2 2007 onward.",
        "url": "https://data.gov.sg/datasets/d_b51323a474ba789fb4cc3db58a3116d4/view",
    },
    "resale_applications": {
        "id": "d_02aa4bb51bc674f3a2d0b9bb6911d934",
        "name": "Resale Applications by Flat Type",
        "agency": "HDB",
        "period_note": "Quarterly; published dataset currently spans Q1 2007 onward.",
        "url": "https://data.gov.sg/datasets/d_02aa4bb51bc674f3a2d0b9bb6911d934/view",
    },
    "hdb_property": {
        "id": "d_17f5382f26140b1fdae0ba2ef6239d2f",
        "name": "HDB Property Information",
        "agency": "HDB",
        "period_note": "Reference inventory; published coverage through Dec 2025.",
        "url": "https://data.gov.sg/datasets/d_17f5382f26140b1fdae0ba2ef6239d2f/view",
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


def _fetch_with_retry(req: urllib.request.Request, timeout: int = 20) -> dict:
    """Fetch URL with exponential backoff retry on rate limit (HTTP 429)."""
    last_exception = None
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_exception = exc
            if exc.code == 429 and attempt < MAX_RETRIES - 1:
                backoff = min(BASE_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)
                log.warning("Rate limited (HTTP 429) on attempt %d/%d, backing off %.1fs",
                           attempt + 1, MAX_RETRIES, backoff)
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


def _fetch_dataset(key: str, limit: int = 5000) -> SourceResult:
    spec = DATASETS[key]
    all_records: list[dict[str, Any]] = []
    offset = 0
    headers = {"Accept": "application/json", "User-Agent": "UrbanOS-Housing-Intelligence/1.0"}
    api_key = os.getenv("DATA_GOV_SG_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    while True:
        params = urllib.parse.urlencode({"resource_id": spec["id"], "limit": limit, "offset": offset})
        req = urllib.request.Request(f"{BASE}?{params}", headers=headers)
        try:
            payload = _fetch_with_retry(req, timeout=20)
        except urllib.error.HTTPError as exc:
            msg = f"HTTP {exc.code}"
            if exc.code == 429:
                msg += " (rate limited)"
            log.warning("Housing dataset %s unavailable: %s", key, msg)
            return SourceResult(key, spec["name"], spec["agency"], spec["url"], "unavailable", error=msg)
        except Exception as exc:
            log.warning("Housing dataset %s unavailable: %s", key, exc)
            return SourceResult(key, spec["name"], spec["agency"], spec["url"], "unavailable", error=str(exc)[:240])

        if not payload.get("success") or not isinstance(payload.get("result"), dict):
            raise ValueError("data.gov.sg response did not contain a successful datastore result")

        result = payload["result"]
        records = result.get("records") or []
        if not isinstance(records, list):
            raise ValueError("data.gov.sg records field was not a list")

        all_records.extend(records)

        if len(records) < limit:
            break
        offset += limit

    return SourceResult(
        key=key, name=spec["name"], agency=spec["agency"], url=spec["url"],
        status="available" if all_records else "empty", records=all_records,
        retrieved_at=datetime.now(SG).isoformat(),
        fields=sorted({str(k) for row in all_records[:5] for k in row.keys()}),
    )


def fetch_housing_snapshot() -> dict[str, Any]:
    """Fetch selected open HDB datasets; preserve per-source failures."""
    sources = {key: _fetch_dataset(key) for key in DATASETS}
    return {
        "generated_at": datetime.now(SG).isoformat(),
        "sources": sources,
        "errors": [f"{s.name}: {s.error}" for s in sources.values() if s.status == "unavailable"],
    }