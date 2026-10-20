"""Official Singapore waste data acquisition (backend only).

Sources actually used (all located through data.gov.sg dataset pages; the statistics table
was additionally confirmed against the live ``datastore_search`` response on 11 Oct 2026):

  waste_statistics     d_daf568968ab40dc81e7b08887a83c8fa  SingStat table M891371 (MSE / NEA)
  general_collectors   d_b4de98f706379b787ab86d1e69412910  NEA licensed general waste collectors
  recycling_bins       d_4dde14826642f49eefff48b7832b90db  NEA recycling bins (GeoJSON, 18.5 MB)
  ewaste_points        d_db40d004afeb5a7f0f555fdcc34934cc  NEA e-waste collection points (GeoJSON)
  lighting_waste       d_6226f69998ed0cb62151af37706508cd  NEA lighting-waste collection points
  disposal_sites       d_4b6f69760d43000af97708ca7367c334  NEA waste disposal sites (landfill, WTE plants, TMTS)

Tabular datasets use the documented ``datastore_search`` API; the four location layers are
GeoJSON files fetched through the documented ``poll-download`` API.

None of these are live feeds.  Nothing here fabricates data: every parser returns only what the
source contains and reports what it had to drop.
"""
from __future__ import annotations

import html
import json
import logging
import math
import os
import re
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from backend.app.infrastructure.waste.models import SourceInfo

log = logging.getLogger(__name__)
SG = timezone(timedelta(hours=8))

DATASTORE_URL = "https://data.gov.sg/api/action/datastore_search"
POLL_DOWNLOAD_URL = "https://api-open.data.gov.sg/v1/public/api/datasets/{dataset_id}/poll-download"

WASTE_STATS_ID = "d_daf568968ab40dc81e7b08887a83c8fa"
COLLECTORS_ID = "d_b4de98f706379b787ab86d1e69412910"
BINS_ID = "d_4dde14826642f49eefff48b7832b90db"
EWASTE_ID = "d_db40d004afeb5a7f0f555fdcc34934cc"
LIGHTING_ID = "d_6226f69998ed0cb62151af37706508cd"
DISPOSAL_ID = "d_4b6f69760d43000af97708ca7367c334"

# Statistics change once a year; listings change rarely. Cache for hours, not seconds.
STATS_TTL_S = int(os.getenv("URBANOS_WASTE_CACHE_TTL_S", str(6 * 3600)))
FACILITY_TTL_S = int(os.getenv("URBANOS_WASTE_FACILITY_CACHE_TTL_S", str(24 * 3600)))
# data.gov.sg anonymous quota for poll-download is ~5 requests/minute (official download guide); an API key raises it.
POLL_INTERVAL_NO_KEY_S = 12.5
POLL_INTERVAL_WITH_KEY_S = 1.0
RATE_LIMIT_BACKOFF_S = 12.0          # first wait after an HTTP 429 without Retry-After (then x2, x3 ...)
FAILURE_RETRY_S = 300.0              # after a failed background download, wait this long before trying again
# Rough Singapore bounding box used to reject corrupt coordinates.
SG_LON = (103.5, 104.2)
SG_LAT = (1.1, 1.5)

_URL_QUERY = re.compile(r"(https?://[^\s?'\"]+)\?[^\s'\"]*")


def scrub_urls(text: str) -> str:
    """Drop query strings from URLs: data.gov.sg download links are presigned S3 URLs whose
    query string contains temporary credentials that must never be logged or served."""
    return _URL_QUERY.sub(r"\1?<redacted>", str(text))


class WasteSourceError(RuntimeError):
    """A source could not be acquired or parsed."""

    def __init__(self, message: object = "") -> None:
        super().__init__(scrub_urls(str(message)))


# ======================================================================
# Cache + HTTP
# ======================================================================
@dataclass
class FetchResult:
    data: Any
    fetched_at: datetime
    stale: bool = False
    error: Optional[str] = None


class SourceCache:
    """In-memory cache + the shared state of background layer downloads (state follows the cache so that
    every client sharing one cache also shares one view of what is in flight / has failed)."""

    def __init__(self) -> None:
        self._items: Dict[str, Tuple[float, datetime, Any]] = {}
        self._lock = threading.RLock()
        self.bg_lock = threading.Lock()
        self.bg_inflight: set = set()                     # dataset ids being downloaded right now
        self.bg_failed: Dict[str, Tuple[float, str]] = {}  # dataset id -> (monotonic time, error)

    def get(self, key: str, ttl_s: float, now: Optional[float] = None) -> Optional[FetchResult]:
        with self._lock:
            item = self._items.get(key)
        if item is None:
            return None
        stored_at, fetched_at, data = item
        # A zero TTL means "never cache", and an item exactly on its expiry
        # boundary is stale. Using <= kept zero-TTL test/client caches fresh
        # within the same clock tick and hid upstream refresh failures.
        if (now if now is not None else time.time()) - stored_at < ttl_s:
            return FetchResult(data=data, fetched_at=fetched_at)
        return None

    def get_any(self, key: str) -> Optional[FetchResult]:
        with self._lock:
            item = self._items.get(key)
        if item is None:
            return None
        return FetchResult(data=item[2], fetched_at=item[1], stale=True)

    def put(self, key: str, data: Any, fetched_at: Optional[datetime] = None) -> datetime:
        """Store ``data``. ``fetched_at`` lets a copy restored from disk keep its real age."""
        fetched_at = fetched_at or datetime.now(SG)
        age_s = max(0.0, (datetime.now(SG) - fetched_at).total_seconds())
        with self._lock:
            self._items[key] = (time.time() - age_s, fetched_at, data)
        return fetched_at

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
        with self.bg_lock:
            self.bg_inflight.clear()
            self.bg_failed.clear()


_GLOBAL_CACHE = SourceCache()
_POLL_LOCK = threading.Lock()
_LAST_POLL = [0.0]          # monotonic time of the last poll-download request (the quota is per IP, so global)

_UNSET: Any = object()


# ----------------------------------------------------------------------
# Disk cache for the parsed location layers (static data; survives restarts)
# ----------------------------------------------------------------------
class LayerDiskCache:
    """One small JSON file per dataset holding the *parsed* layer (never the raw 18 MB download)."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    @classmethod
    def default(cls) -> Optional["LayerDiskCache"]:
        if os.getenv("URBANOS_WASTE_DISK_CACHE", "1") == "0":
            return None
        return cls(Path(os.getenv("URBANOS_WASTE_CACHE_DIR") or Path(tempfile.gettempdir()) / "urbanos_waste_cache"))

    def _path(self, dataset_id: str) -> Path:
        return self.directory / f"{re.sub(r'[^A-Za-z0-9_]', '', dataset_id)}.json"

    def save(self, dataset_id: str, layer: "FacilityLayer", fetched_at: datetime) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1, "kind": layer.kind, "fetched_at": fetched_at.isoformat(),
                "invalid": layer.invalid, "duplicates_removed": layer.duplicates_removed,
                "by_name": dict(layer.by_name),
                "facilities": [[f.id, f.lon, f.lat, f.name, f.address, f.record_date, f.description] for f in layer.facilities],
            }
            tmp = self._path(dataset_id).with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._path(dataset_id))          # atomic: readers never see a half-written file
        except OSError as exc:                            # a cache must never break the module
            log.warning("Could not write waste layer cache for %s: %s", dataset_id, exc)

    def load(self, dataset_id: str) -> Optional[Tuple[datetime, "FacilityLayer"]]:
        try:
            raw = json.loads(self._path(dataset_id).read_text(encoding="utf-8"))
            if raw.get("version") != 1:
                return None
            layer = FacilityLayer(kind=raw["kind"], invalid=int(raw["invalid"]),
                                  duplicates_removed=int(raw["duplicates_removed"]), by_name=Counter(raw["by_name"]))
            layer.facilities = [Facility(id=r[0], lon=float(r[1]), lat=float(r[2]), name=r[3], address=r[4],
                                         record_date=r[5], description=r[6]) for r in raw["facilities"]]
            return datetime.fromisoformat(raw["fetched_at"]), layer
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            return None                                   # missing / corrupt / old format => treated as a miss


class WasteDataClient:
    """HTTP client: timeout, retry/backoff (429/5xx), optional auth header, cache, and a throttle for the
    rate-limited ``poll-download`` endpoint (data.gov.sg: roughly 5 requests/minute without an API key)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout_s: float = 20.0,
        download_timeout_s: float = 90.0,
        max_attempts: int = 3,
        cache: Optional[SourceCache] = None,
        ttl_s: float = STATS_TTL_S,
        facility_ttl_s: float = FACILITY_TTL_S,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
        poll_min_interval_s: Optional[float] = None,
        rate_limit_backoff_s: float = RATE_LIMIT_BACKOFF_S,
        disk_cache: Any = _UNSET,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("DATA_GOV_SG_API_KEY")
        self.timeout_s = timeout_s
        self.download_timeout_s = download_timeout_s
        self.max_attempts = max(1, max_attempts)
        self.cache = cache if cache is not None else _GLOBAL_CACHE
        self.ttl_s = ttl_s
        self.facility_ttl_s = facility_ttl_s
        self._transport = transport
        self._sleep = sleep
        if poll_min_interval_s is None:
            env = os.getenv("URBANOS_WASTE_POLL_INTERVAL_S")
            poll_min_interval_s = float(env) if env else (POLL_INTERVAL_WITH_KEY_S if self.api_key else POLL_INTERVAL_NO_KEY_S)
        self.poll_min_interval_s = max(0.0, poll_min_interval_s)
        self.rate_limit_backoff_s = max(0.0, rate_limit_backoff_s)
        self.disk_cache: Optional[LayerDiskCache] = LayerDiskCache.default() if disk_cache is _UNSET else disk_cache

    # -- low level ------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        headers = {"User-Agent": "UrbanOS/1.0 (Waste domain)", "Accept": "application/json"}
        if self.api_key:  # optional; raises rate limits when present
            headers["x-api-key"] = self.api_key
        return headers

    def _throttle_poll(self) -> None:
        """Space poll-download requests (shared by every client in the process; the quota is per IP)."""
        if self.poll_min_interval_s <= 0:
            return
        with _POLL_LOCK:
            wait = _LAST_POLL[0] + self.poll_min_interval_s - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            _LAST_POLL[0] = time.monotonic()

    def _get(self, url: str, params: Optional[Dict[str, Any]] = None, timeout_s: Optional[float] = None) -> httpx.Response:
        """GET with timeout, retry/backoff on 429/5xx and transport errors."""
        last_error = "unknown error"
        for attempt in range(1, self.max_attempts + 1):
            try:
                with httpx.Client(
                    timeout=timeout_s or self.timeout_s,
                    follow_redirects=True,
                    headers=self._headers(),
                    transport=self._transport,
                ) as client:
                    resp = client.get(url, params=params)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_error = f"HTTP {resp.status_code} from {url}"
                    if resp.status_code == 429 and not self.api_key:
                        last_error += " (rate limited; anonymous data.gov.sg access allows ~5 downloads/minute - set DATA_GOV_SG_API_KEY)"
                    if attempt < self.max_attempts:
                        self._sleep(self._retry_delay(resp, attempt))
                        continue
                    raise WasteSourceError(last_error)
                if resp.status_code >= 400:
                    raise WasteSourceError(f"HTTP {resp.status_code} from {url}")
                return resp
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"{type(exc).__name__} contacting {url}: {exc}"
                if attempt < self.max_attempts:
                    self._sleep(min(2 ** (attempt - 1), 8))
                    continue
                raise WasteSourceError(last_error) from exc
        raise WasteSourceError(last_error)

    def _get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        resp = self._get(url, params)
        try:
            return resp.json()
        except ValueError as exc:
            raise WasteSourceError(f"Invalid JSON from {url}: {exc}") from exc

    def _retry_delay(self, resp: httpx.Response, attempt: int) -> float:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), 60.0))
            except ValueError:
                pass
        if resp.status_code == 429:      # quota windows are long: waiting 1-2 s just burns another request
            return min(self.rate_limit_backoff_s * attempt, 60.0)
        return float(min(2 ** (attempt - 1), 8))

    # -- datastore_search -------------------------------------------------
    def _fetch_datastore_records(self, resource_id: str, page_size: int = 500) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        offset = 0
        while True:
            payload = self._get_json(
                DATASTORE_URL,
                {"resource_id": resource_id, "limit": page_size, "offset": offset},
            )
            if not isinstance(payload, dict) or payload.get("success") is False:
                raise WasteSourceError(f"datastore_search failed for {resource_id}")
            result = payload.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("records"), list):
                raise WasteSourceError(f"Unexpected datastore_search shape for {resource_id}")
            batch = result["records"]
            records.extend(r for r in batch if isinstance(r, dict))
            total = result.get("total")
            offset += len(batch)
            if not batch or not isinstance(total, int) or offset >= total:
                break
            if offset > 50_000:  # hard stop against runaway pagination
                raise WasteSourceError(f"Refusing to page beyond 50k rows for {resource_id}")
        return records

    # -- poll-download (GeoJSON file) --------------------------------------
    def _download_geojson(self, dataset_id: str, polls: int = 3) -> Dict[str, Any]:
        meta_url = POLL_DOWNLOAD_URL.format(dataset_id=dataset_id)
        download_url: Optional[str] = None
        for i in range(polls):
            self._throttle_poll()
            meta = self._get_json(meta_url)
            if isinstance(meta, dict) and meta.get("code") == 0:
                download_url = (meta.get("data") or {}).get("url")
                if download_url:
                    break
            if i < polls - 1:
                self._sleep(2)
        if not download_url:
            raise WasteSourceError(f"poll-download did not return a file URL for {dataset_id}")
        content = self._get(download_url, timeout_s=self.download_timeout_s).content
        try:
            # errors="replace": some NEA address strings contain stray invalid bytes.
            data = json.loads(content.decode("utf-8-sig", errors="replace"))
        except ValueError as exc:
            raise WasteSourceError(f"{dataset_id} download is not valid JSON") from exc
        if not isinstance(data, dict) or not isinstance(data.get("features"), list):
            raise WasteSourceError(f"{dataset_id} JSON is not a GeoJSON FeatureCollection")
        return data

    # -- cached public API -------------------------------------------------
    def _cached(self, key: str, ttl_s: float, loader: Callable[[], Any]) -> FetchResult:
        fresh = self.cache.get(key, ttl_s)
        if fresh is not None:
            return fresh
        try:
            data = loader()
        except WasteSourceError as exc:
            stale = self.cache.get_any(key)
            if stale is not None:
                stale.error = str(exc)
                return stale
            raise
        return FetchResult(data=data, fetched_at=self.cache.put(key, data))

    def get_records(self, resource_id: str) -> FetchResult:
        return self._cached(f"ds:{resource_id}", self.ttl_s, lambda: self._fetch_datastore_records(resource_id))

    # -- location layers: memory -> disk -> network -------------------------
    def _age_s(self, fetched_at: datetime) -> float:
        return (datetime.now(SG) - fetched_at).total_seconds()

    def peek_facility_layer(self, dataset_id: str) -> Optional[FetchResult]:
        """Return a cached layer (memory, then disk) WITHOUT touching the network; ``stale`` = older than the TTL.
        None means nothing is cached anywhere."""
        key = f"layer:{dataset_id}"
        hit = self.cache.get_any(key)
        if hit is None and self.disk_cache is not None:
            disk = self.disk_cache.load(dataset_id)
            if disk is not None:
                fetched_at, layer = disk
                self.cache.put(key, layer, fetched_at)
                hit = FetchResult(data=layer, fetched_at=fetched_at, stale=True)
        if hit is None:
            return None
        hit.stale = self._age_s(hit.fetched_at) > self.facility_ttl_s
        return hit

    def get_facility_layer(self, dataset_id: str, kind: str) -> FetchResult:
        """Blocking fetch with cache. Only the parsed layer is cached, never the raw 18 MB document."""
        hit = self.peek_facility_layer(dataset_id)
        if hit is not None and not hit.stale:
            return hit
        try:
            layer = parse_facility_geojson(self._download_geojson(dataset_id), kind)
        except WasteSourceError as exc:
            if hit is not None:                 # an out-of-date copy beats nothing
                hit.stale, hit.error = True, str(exc)
                return hit
            raise
        fetched_at = self.cache.put(f"layer:{dataset_id}", layer)
        if self.disk_cache is not None:
            self.disk_cache.save(dataset_id, layer, fetched_at)
        return FetchResult(data=layer, fetched_at=fetched_at)

    # -- background loading (keeps the report fast while rate-limited downloads trickle in) ---
    def background_state(self, dataset_id: str) -> Tuple[str, Optional[str]]:
        """('loading', None) | ('failed', error) | ('idle', None)."""
        with self.cache.bg_lock:
            if dataset_id in self.cache.bg_inflight:
                return "loading", None
            failed = self.cache.bg_failed.get(dataset_id)
            if failed and time.monotonic() - failed[0] < FAILURE_RETRY_S:
                return "failed", failed[1]
        return "idle", None

    def ensure_layers_in_background(self, wanted: Dict[str, str]) -> None:
        """Start (once) a single worker that downloads the given {kind: dataset_id} layers one after another."""
        with self.cache.bg_lock:
            todo = {k: d for k, d in wanted.items() if d not in self.cache.bg_inflight}
            self.cache.bg_inflight.update(todo.values())
        if not todo:
            return

        def worker() -> None:
            for kind, dataset_id in todo.items():
                try:
                    self.get_facility_layer(dataset_id, kind)
                    with self.cache.bg_lock:
                        self.cache.bg_failed.pop(dataset_id, None)
                except WasteSourceError as exc:
                    log.warning("Background download of %s failed: %s", dataset_id, exc)
                    with self.cache.bg_lock:
                        self.cache.bg_failed[dataset_id] = (time.monotonic(), str(exc))
                except Exception as exc:  # noqa: BLE001 - a worker must never die silently
                    log.exception("Unexpected error downloading %s", dataset_id)
                    with self.cache.bg_lock:
                        self.cache.bg_failed[dataset_id] = (time.monotonic(), f"Unexpected error: {exc}")
                finally:
                    with self.cache.bg_lock:
                        self.cache.bg_inflight.discard(dataset_id)

        threading.Thread(target=worker, daemon=True, name="waste-layer-download").start()


# ======================================================================
# Parsing helpers (pure)
# ======================================================================
def _norm_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")


def parse_number(value: Any) -> Optional[float]:
    """Return a finite float, or None for missing / 'na' / '-' / non-numeric."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    text = str(value).strip().replace(",", "")
    if text == "" or text.lower() in {"na", "n/a", "nan", "-", "--", "null", "none"}:
        return None
    try:
        num = float(text)
    except ValueError:
        return None
    return num if math.isfinite(num) else None


def _is_missing_marker(value: Any) -> bool:
    return value is None or str(value).strip().lower() in {"", "na", "n/a", "nan", "-", "--", "null", "none"}


# ----------------------------------------------------------------- statistics table
BLOCK_HEADERS = {
    "total generated": "generated",
    "total recycled": "recycled",
    "total disposed": "disposed",
    "recycling rate": "rate",
    "overall recycling rate": "rate",
}
BLOCKS = ("generated", "recycled", "disposed", "rate")

CATEGORY_LABELS = {
    "construction_demolition": "Construction & Demolition",
    "ferrous_metal": "Ferrous metal",
    "non_ferrous_metal": "Non-ferrous metal",
    "used_slag": "Used slag",
    "scrap_tyres": "Scrap tyres",
    "horticultural": "Horticultural",
    "wood": "Wood",
    "paper_cardboard": "Paper/Cardboard",
    "glass": "Glass",
    "food": "Food",
    "ash_and_sludge": "Ash & sludge",
    "textile_leather": "Textile/Leather",
    "plastic": "Plastics",
    "others": "Others",
}


def category_key(label: str) -> str:
    key = _norm_key(label.replace("&", " and "))
    return {"construction_and_demolition": "construction_demolition", "plastics": "plastic"}.get(key, key)


@dataclass
class WasteTable:
    """Parsed 'Waste Management And Overall Recycling Rates, Annual' (tonnes; rate in %)."""

    total: Dict[str, Dict[int, Optional[float]]] = field(default_factory=dict)            # block -> year -> value
    cats: Dict[str, Dict[str, Dict[int, Optional[float]]]] = field(default_factory=dict)  # block -> cat -> year -> value
    labels: Dict[str, str] = field(default_factory=dict)
    years: List[int] = field(default_factory=list)
    duplicate_rows: int = 0
    unparseable_cells: int = 0
    missing_cells: int = 0
    warnings: List[str] = field(default_factory=list)

    def row_count(self) -> int:
        """Number of parsed series rows (block totals + category rows)."""
        return len(self.total) + sum(len(c) for c in self.cats.values())


def parse_waste_statistics(records: List[Dict[str, Any]]) -> WasteTable:
    """Parse the wide table: one row per series, one column per year.

    The table is made of four blocks (Total Generated / Total Recycled / Total Disposed / Recycling
    Rate).  Each block starts with its total row followed by the same 14 waste-type rows, so a
    category row can only be understood from the block header preceding it.  Rows are therefore
    processed in ``_id`` order, and a category is attached to the most recent block header.
    """
    table = WasteTable()
    ordered = sorted(
        enumerate(records),
        key=lambda iv: (iv[1].get("_id") if isinstance(iv[1].get("_id"), (int, float)) else iv[0] + 10**9, iv[0]),
    )
    year_set: set = set()
    block: Optional[str] = None
    seen: set = set()
    for _, rec in ordered:
        name = None
        for k, v in rec.items():
            if _norm_key(k) in {"dataseries", "data_series"} and isinstance(v, str):
                name = v
                break
        if name is None or not name.strip():
            table.warnings.append("Row without a data-series name was skipped")
            continue
        label = re.sub(r"\s+", " ", name.strip())
        header = BLOCK_HEADERS.get(label.lower())
        cells: Dict[int, Optional[float]] = {}
        for k, v in rec.items():
            if not re.fullmatch(r"\s*\d{4}\s*", str(k)):
                continue
            year = int(str(k).strip())
            if not 1900 <= year <= 2100:
                continue
            if _is_missing_marker(v):
                table.missing_cells += 1
                cells[year] = None
                continue
            num = parse_number(v)
            row_block = header or block
            if num is None or num < 0 or (row_block == "rate" and num > 100):
                table.unparseable_cells += 1
                cells[year] = None
                continue
            cells[year] = num
        year_set.update(cells)
        if header is not None:
            if header in table.total:
                table.duplicate_rows += 1
                table.warnings.append(f"Duplicate block header '{label}' ignored")
                block = None
                continue
            block = header
            table.total[block] = cells
            table.cats.setdefault(block, {})
            continue
        if block is None:
            table.warnings.append(f"Row '{label}' appears before any block header and was skipped")
            continue
        key = category_key(label)
        if (block, key) in seen:
            table.duplicate_rows += 1
            table.warnings.append(f"Duplicate row '{label}' in block '{block}'; the first occurrence was kept")
            continue
        seen.add((block, key))
        table.cats[block][key] = cells
        table.labels.setdefault(key, CATEGORY_LABELS.get(key, label))
    table.years = sorted(year_set)
    return table


# ----------------------------------------------------------------- general waste collectors
CLASS_DESCRIPTIONS = {
    "A": ("Class A", "Inorganic & bulky waste (e.g. construction debris, furniture, appliances) and recyclables excluding food waste"),
    "B": ("Class B", "Organic / putrescible waste from domestic, trade & industrial premises, markets & food centres (excl. used cooking oil)"),
    "B.1": ("Class B.1", "Used cooking oil"),
    "C": ("Class C", "Sewage, sludge & grease-interceptor waste from sanitary systems in ships, aircraft, septic tanks & treatment plants"),
}
_CLASS_TOKEN = re.compile(r"^class\s+([a-z](?:\.\d+)?)$", re.I)


@dataclass
class CollectorListing:
    licensees: Dict[str, frozenset] = field(default_factory=dict)   # normalised name -> class keys
    raw_rows: int = 0
    duplicate_rows_removed: int = 0
    unrecognised: Counter = field(default_factory=Counter)
    combinations: Counter = field(default_factory=Counter)


def _pick(record: Dict[str, Any], *candidates: str) -> Any:
    lookup = {_norm_key(k): v for k, v in record.items()}
    for cand in candidates:
        if cand in lookup:
            return lookup[cand]
    return None


def parse_general_waste_collectors(records: List[Dict[str, Any]]) -> CollectorListing:
    """Reduce the NEA licensee list to {licensee -> licence classes}.

    Only the licensee name and licence class are read: the dataset also publishes business
    e-mail addresses and phone numbers, which this module deliberately never ingests.
    """
    out = CollectorListing()
    for rec in records:
        out.raw_rows += 1
        name = _pick(rec, "licensee_name", "company_name", "name")
        classes_raw = _pick(rec, "class_of_waste", "class_of_licence", "class")
        if not isinstance(name, str) or not name.strip():
            continue
        norm_name = re.sub(r"\s+", " ", name.strip()).upper()
        keys: set = set()
        for token in str(classes_raw or "").split(","):
            token = token.strip()
            if not token:
                continue
            m = _CLASS_TOKEN.match(token)
            if m and m.group(1).upper() in CLASS_DESCRIPTIONS:
                keys.add(m.group(1).upper())
            else:
                out.unrecognised[token] += 1
        if norm_name in out.licensees:
            out.duplicate_rows_removed += 1
            keys |= set(out.licensees[norm_name])
        out.licensees[norm_name] = frozenset(keys)
    for keys in out.licensees.values():
        if keys:
            out.combinations[", ".join(f"Class {k}" for k in sorted(keys))] += 1
    return out


# ----------------------------------------------------------------- facility layers
FACILITY_LABELS = {
    "recycling_bins": "Recycling bins",
    "ewaste": "E-waste collection points",
    "lighting_waste": "Lighting-waste collection points",
    "disposal_sites": "Waste disposal sites",
}

# Keys are plain text ([^<]*): the table's header row (<th colspan=2><em>Attributes</em></th>) contains a
# nested tag and must NOT be allowed to swallow the first real attribute.
_TH_TD = re.compile(r"<th[^>]*>([^<]*)</th>\s*<td[^>]*>(.*?)</td>", re.I | re.S)


def _description_pairs(description: Any) -> Dict[str, str]:
    """Extract <th>KEY</th><td>VALUE</td> pairs used in NEA's KML-derived 'Description' property."""
    if not isinstance(description, str):
        return {}
    pairs: Dict[str, str] = {}
    for key, value in _TH_TD.findall(description):
        k = html.unescape(re.sub(r"<[^>]+>", "", key)).strip().upper()
        v = html.unescape(re.sub(r"<[^>]+>", "", value)).strip()
        if k:
            pairs[k] = v
    return pairs


def _record_date(value: Any) -> Optional[str]:
    text = re.sub(r"\D", "", str(value or ""))[:8]
    if len(text) != 8:
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


@dataclass(frozen=True)
class Facility:
    id: str
    lon: float
    lat: float
    name: str
    address: Optional[str] = None
    record_date: Optional[str] = None
    description: Optional[str] = None


@dataclass
class FacilityLayer:
    kind: str
    facilities: List[Facility] = field(default_factory=list)
    invalid: int = 0
    duplicates_removed: int = 0
    by_name: Counter = field(default_factory=Counter)

    @property
    def date_min(self) -> Optional[str]:
        dates = [f.record_date for f in self.facilities if f.record_date]
        return min(dates) if dates else None

    @property
    def date_max(self) -> Optional[str]:
        dates = [f.record_date for f in self.facilities if f.record_date]
        return max(dates) if dates else None


def parse_facility_geojson(geojson: Dict[str, Any], kind: str) -> FacilityLayer:
    """Parse a point layer. Handles both layouts seen on data.gov.sg: direct properties (e-waste)
    and the KML-derived layout whose real attributes sit in an HTML 'Description' table."""
    layer = FacilityLayer(kind=kind)
    seen: set = set()
    default_name = FACILITY_LABELS.get(kind, kind)
    for idx, feat in enumerate(geojson.get("features") or []):
        try:
            geom = feat.get("geometry") or {}
            if geom.get("type") != "Point":
                raise ValueError("not a point")
            coords = geom.get("coordinates") or []
            lon, lat = float(coords[0]), float(coords[1])
            if not (math.isfinite(lon) and math.isfinite(lat)):
                raise ValueError("non-finite")
            if not (SG_LON[0] <= lon <= SG_LON[1] and SG_LAT[0] <= lat <= SG_LAT[1]):
                raise ValueError("outside Singapore")
        except (TypeError, ValueError, IndexError, AttributeError):
            layer.invalid += 1
            continue
        props = feat.get("properties") if isinstance(feat.get("properties"), dict) else {}
        pairs = _description_pairs(props.get("Description"))
        # 'Description' (capital D, HTML table) is the KML attribute blob; 'DESCRIPTION' is a real text field.
        direct = {str(k).upper(): v for k, v in props.items() if k != "Description"}
        if not pairs and isinstance(props.get("Description"), str):
            direct.setdefault("DESCRIPTION", props["Description"])      # plain-text variant of the same field

        def field_value(key: str) -> Optional[str]:
            val = pairs.get(key)
            if val in (None, ""):
                val = direct.get(key)
            if val is None or str(val).strip() == "":
                return None
            return re.sub(r"\s+", " ", str(val)).strip()

        name = field_value("NAME") or default_name
        if re.fullmatch(r"kml_\d+", name, re.I):  # KML placeholder, not a real name
            name = default_name
        address_bits = [field_value("ADDRESSBLOCKHOUSENUMBER"), field_value("ADDRESSSTREETNAME")]
        address = " ".join(b for b in address_bits if b) or field_value("ADDRESSBUILDINGNAME")
        facility = Facility(
            id=f"{kind}-{idx + 1}", lon=round(lon, 6), lat=round(lat, 6), name=name, address=address,
            record_date=_record_date(field_value("FMEL_UPD_D")),
            description=(field_value("DESCRIPTION") or "")[:200] or None,
        )
        dedupe_key = (facility.lon, facility.lat, facility.name, facility.address)
        if dedupe_key in seen:
            layer.duplicates_removed += 1
            continue
        seen.add(dedupe_key)
        layer.facilities.append(facility)
        layer.by_name[name] += 1
    return layer


# ======================================================================
# Snapshot
# ======================================================================
@dataclass
class WasteSnapshot:
    generated_at: datetime
    table: Optional[WasteTable] = None
    collectors: Optional[CollectorListing] = None
    facilities: Dict[str, FacilityLayer] = field(default_factory=dict)
    facility_status: Dict[str, str] = field(default_factory=dict)   # kind -> ok|stale_cache|unavailable
    sources: List[SourceInfo] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


SOURCE_CATALOG: List[Dict[str, str]] = [
    dict(
        key="waste_statistics", organization="SingStat (compiled from MSE / NEA)",
        name="Waste Management And Overall Recycling Rates, Annual", identifier=WASTE_STATS_ID,
        url=f"https://data.gov.sg/datasets/{WASTE_STATS_ID}/view",
        purpose="Waste generated, recycled and disposed (tonnes) and recycling rate (%), in total and for 14 waste types, incl. food waste",
        update_frequency="Annual (dataset page: data last updated 21 Jul 2026)",
        coverage="2000-2025, national", authentication="None required (optional x-api-key raises rate limits)",
        data_kind="latest_available", component="Generation, Recycling, Disposal, Categories, Food waste",
    ),
    dict(
        key="general_collectors", organization="NEA",
        name="Listing of General Waste Collectors", identifier=COLLECTORS_ID,
        url=f"https://data.gov.sg/datasets/{COLLECTORS_ID}/view",
        purpose="NEA-licensed general waste collectors and their licence class (A, B, B.1, C); only counts are used",
        update_frequency="Periodic (dataset page: data from Jan 2026, last updated 19 Jan 2026)",
        coverage="Jan 2026 listing, national", authentication="None required (optional x-api-key)",
        data_kind="reference", component="Waste Services",
    ),
    dict(
        key="recycling_bins", organization="NEA", name="Recycling Bins (GeoJSON)", identifier=BINS_ID,
        url=f"https://data.gov.sg/datasets/{BINS_ID}/view",
        purpose="Locations of recycling bins (HDB estates and other bin programmes)",
        update_frequency="Static (dataset page: last updated 06 Jun 2024; feature records stamped 2017)",
        coverage="Static point layer, national", authentication="None required",
        data_kind="reference", component="Recycling Infrastructure (map)",
    ),
    dict(
        key="ewaste_points", organization="NEA", name="E-waste Recycling (GeoJSON)", identifier=EWASTE_ID,
        url=f"https://data.gov.sg/datasets/{EWASTE_ID}/view",
        purpose="E-waste collection points (ALBA and KGS programmes)",
        update_frequency="Annual (publisher note: data last updated 2022-06-02 and may be outdated)",
        coverage="Static point layer, national", authentication="None required",
        data_kind="reference", component="Recycling Infrastructure (map)",
    ),
    dict(
        key="lighting_waste", organization="NEA", name="Lighting Waste Collection Points (GeoJSON)", identifier=LIGHTING_ID,
        url=f"https://data.gov.sg/datasets/{LIGHTING_ID}/view",
        purpose="Collection points for old light bulbs and fluorescent tubes",
        update_frequency="Annual (dataset page: last updated 06 Jun 2024; feature records stamped 2019)",
        coverage="Static point layer, national", authentication="None required",
        data_kind="reference", component="Recycling Infrastructure (map)",
    ),
    dict(
        key="disposal_sites", organization="NEA", name="Waste Disposal Site (GeoJSON)", identifier=DISPOSAL_ID,
        url=f"https://data.gov.sg/datasets/{DISPOSAL_ID}/view",
        purpose="Locations of Semakau Landfill, waste-to-energy / incineration plants and the Tuas Marine Transfer Station",
        update_frequency="Static (publisher note: data last updated 2018-02-01 and may be outdated; page updated 08 Nov 2025)",
        coverage="7 point features, national", authentication="None required",
        data_kind="reference", component="Waste Disposal Infrastructure (map)",
    ),
]

FACILITY_SPECS = {
    "recycling_bins": dict(source="recycling_bins", dataset_id=BINS_ID, last_updated="2024-06-06"),
    "ewaste": dict(source="ewaste_points", dataset_id=EWASTE_ID, last_updated="2025-11-08"),
    "lighting_waste": dict(source="lighting_waste", dataset_id=LIGHTING_ID, last_updated="2024-06-06"),
    "disposal_sites": dict(source="disposal_sites", dataset_id=DISPOSAL_ID, last_updated="2025-11-08"),
}


def _source(key: str) -> SourceInfo:
    spec = next(s for s in SOURCE_CATALOG if s["key"] == key)
    return SourceInfo(**spec)  # type: ignore[arg-type]


def _peek_layer(client: WasteDataClient, kind: str, spec: Dict[str, str],
                to_load: Dict[str, str]) -> Tuple[SourceInfo, Any, List[str], List[str]]:
    """Non-blocking view of one location layer: cached -> ok / stale_cache; absent -> loading (or unavailable
    if the last background attempt failed recently). Layers that need (re)loading are added to ``to_load``."""
    info, errors, warnings, payload = _source(spec["source"]), [], [], None
    res = client.peek_facility_layer(spec["dataset_id"])
    state, bg_error = client.background_state(spec["dataset_id"])
    if res is not None:
        payload = res.data
        info.last_fetched_at, info.latest_data_period, info.record_count = res.fetched_at, payload.date_max, len(payload.facilities)
        if res.stale:
            info.status, info.error = "stale_cache", (bg_error if state == "failed" else None)
            hours = int(client.facility_ttl_s // 3600)
            warnings.append(f"{info.name}: showing a cached copy older than {hours} h; "
                            + (f"refresh failed ({bg_error})" if state == "failed" else "refreshing in the background"))
            if state == "idle":
                to_load[kind] = spec["dataset_id"]
        else:
            info.status = "ok"
        if not payload.facilities:
            info.status, info.error, payload = "unavailable", "Source responded but no usable rows were parsed", None
            errors.append(f"{info.name}: no usable rows parsed")
    elif state == "failed":
        info.status, info.error = "unavailable", bg_error
        errors.append(f"{info.name}: {bg_error}")
    else:
        info.status = "loading"
        if state == "idle":
            to_load[kind] = spec["dataset_id"]
    return info, payload, errors, warnings


_DEFAULT_CLIENT: Optional[WasteDataClient] = None
_DEFAULT_LOCK = threading.Lock()


def default_client() -> WasteDataClient:
    """One shared client per process (shared cache, throttle and background-download state)."""
    global _DEFAULT_CLIENT
    with _DEFAULT_LOCK:
        if _DEFAULT_CLIENT is None:
            _DEFAULT_CLIENT = WasteDataClient()
        return _DEFAULT_CLIENT


def fetch_waste_snapshot(client: Optional[WasteDataClient] = None, wait_for_layers: bool = True) -> WasteSnapshot:
    """Fetch and parse every source. Each failure is isolated and recorded.

    ``wait_for_layers=True``  (default; used by the inspect script and tests): download every location layer now.
    ``wait_for_layers=False`` (used by the API and the City Coordinator): statistics and the licence register are
        fetched normally, but the location layers are only *peeked* from memory/disk cache. Anything missing is
        reported as ``loading`` and downloaded by a background worker, because data.gov.sg limits anonymous file
        downloads to ~5/minute and one layer is 18.5 MB - the report must not wait for that.
    """
    client = client or default_client()
    snap = WasteSnapshot(generated_at=datetime.now(SG))

    def run(key: str, fetch: Callable[[], FetchResult], parse: Callable[[Any], Any],
            describe: Callable[[Any], Tuple[Optional[str], int]]) -> Tuple[SourceInfo, Any, List[str], List[str]]:
        info, errors, warnings, payload = _source(key), [], [], None
        try:
            res = fetch()
            payload = parse(res.data)
            period, count = describe(payload)
            info.last_fetched_at, info.latest_data_period, info.record_count = res.fetched_at, period, count
            if res.stale:
                info.status = "stale_cache"
                info.error = res.error
                warnings.append(f"{info.name}: live refresh failed; showing last cached copy ({res.error})")
            else:
                info.status = "ok"
            if count == 0:
                info.status, info.error = "unavailable", "Source responded but no usable rows were parsed"
                errors.append(f"{info.name}: no usable rows parsed")
                payload = None
        except WasteSourceError as exc:
            info.status, info.error = "unavailable", str(exc)
            errors.append(f"{info.name}: {exc}")
            payload = None
        except Exception as exc:  # noqa: BLE001 - never let one source break the module
            log.exception("Unexpected error processing %s", key)
            info.status, info.error = "unavailable", f"Unexpected error: {exc}"
            errors.append(f"{info.name}: unexpected error: {exc}")
            payload = None
        return info, payload, errors, warnings

    def describe_table(t: WasteTable) -> Tuple[Optional[str], int]:
        gen = t.total.get("generated", {})
        years = [y for y, v in gen.items() if v is not None]
        return (str(max(years)) if years else None), (t.row_count() if years else 0)

    def describe_collectors(c: CollectorListing) -> Tuple[Optional[str], int]:
        return "Jan 2026 listing", len(c.licensees)

    jobs: List[Tuple[str, Callable[[], Tuple[SourceInfo, Any, List[str], List[str]]]]] = [
        ("waste_statistics", lambda: run("waste_statistics", lambda: client.get_records(WASTE_STATS_ID),
                                         parse_waste_statistics, describe_table)),
        ("general_collectors", lambda: run("general_collectors", lambda: client.get_records(COLLECTORS_ID),
                                           parse_general_waste_collectors, describe_collectors)),
    ]
    if wait_for_layers:
        for kind, spec in FACILITY_SPECS.items():
            jobs.append((spec["source"], (lambda kind=kind, spec=spec: run(
                spec["source"], lambda: client.get_facility_layer(spec["dataset_id"], kind),
                lambda layer: layer, lambda layer: (layer.date_max, len(layer.facilities))))))
    else:
        to_load: Dict[str, str] = {}
        for kind, spec in FACILITY_SPECS.items():
            peeked = _peek_layer(client, kind, spec, to_load)
            jobs.append((spec["source"], (lambda peeked=peeked: peeked)))
        if to_load:
            client.ensure_layers_in_background(to_load)

    with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="waste-src") as pool:
        futures = [(key, pool.submit(job)) for key, job in jobs]
        results = [(key, fut.result()) for key, fut in futures]   # catalog order -> deterministic report

    for key, (info, payload, errors, warnings) in results:
        snap.sources.append(info)
        snap.errors.extend(errors)
        snap.warnings.extend(warnings)
        if key == "waste_statistics":
            snap.table = payload
        elif key == "general_collectors":
            snap.collectors = payload
        else:
            kind = next(k for k, s in FACILITY_SPECS.items() if s["source"] == key)
            snap.facility_status[kind] = info.status
            if payload is not None:
                snap.facilities[kind] = payload
    return snap
