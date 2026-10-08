"""Official Singapore water data acquisition (backend only).

Sources actually used (all discovered via data.gov.sg dataset pages):

  water_sales_annual   d_9db4902c7a47357441dac7d2806032a5  (MSE/PUB via SingStat)
  potable_annual       d_cb1d25dd5cfde21bb9fa704af0e3a962  (PUB)
  newater_annual       d_2eceeb792a0fca1caa74304d47b46060  (PUB)
  drinking_quality     d_f397c39929978d3047e0e32430c6763b  (PUB)
  drain_sensors        d_31333fa5cf0834f012d840365b336610  (PUB, XLSX sensor locations)

Tabular datasets use the documented ``datastore_search`` API. The sensor layer is
an XLSX file (confirmed on the live API) fetched through the documented ``poll-download`` API.

No live drain readings or reservoir levels exist as official open feeds that we
could find, so none are fetched. Nothing here fabricates data.
"""
from __future__ import annotations

import io
import json
import logging
import math
import os
import re
import threading
import time
import zipfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from backend.app.infrastructure.water.models import DrainSensor, SourceInfo

log = logging.getLogger(__name__)
SG = timezone(timedelta(hours=8))

DATASTORE_URL = "https://data.gov.sg/api/action/datastore_search"
POLL_DOWNLOAD_URL = "https://api-open.data.gov.sg/v1/public/api/datasets/{dataset_id}/poll-download"

WATER_SALES_ID = "d_9db4902c7a47357441dac7d2806032a5"
POTABLE_ID = "d_cb1d25dd5cfde21bb9fa704af0e3a962"
NEWATER_ID = "d_2eceeb792a0fca1caa74304d47b46060"
QUALITY_ID = "d_f397c39929978d3047e0e32430c6763b"
SENSORS_ID = "d_31333fa5cf0834f012d840365b336610"

# Annual/periodic datasets change at most yearly; cache for hours, not seconds.
DEFAULT_TTL_S = int(os.getenv("URBANOS_WATER_CACHE_TTL_S", str(6 * 3600)))
# Rough Singapore bounding box used to reject corrupt sensor coordinates.
SG_LON = (103.5, 104.2)
SG_LAT = (1.1, 1.5)


_URL_QUERY = re.compile(r"(https?://[^\s?'\"]+)\?[^\s'\"]*")


def scrub_urls(text: str) -> str:
    """Drop query strings from URLs: data.gov.sg download links are presigned S3 URLs
    whose query string contains temporary credentials that must never be logged/served."""
    return _URL_QUERY.sub(r"\1?<redacted>", str(text))


class WaterSourceError(RuntimeError):
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
    def __init__(self) -> None:
        self._items: Dict[str, Tuple[float, datetime, Any]] = {}
        self._lock = threading.RLock()

    def get(self, key: str, ttl_s: float, now: Optional[float] = None) -> Optional[FetchResult]:
        with self._lock:
            item = self._items.get(key)
        if item is None:
            return None
        stored_at, fetched_at, data = item
        if (now if now is not None else time.time()) - stored_at <= ttl_s:
            return FetchResult(data=data, fetched_at=fetched_at)
        return None

    def get_any(self, key: str) -> Optional[FetchResult]:
        with self._lock:
            item = self._items.get(key)
        if item is None:
            return None
        return FetchResult(data=item[2], fetched_at=item[1], stale=True)

    def put(self, key: str, data: Any) -> datetime:
        fetched_at = datetime.now(SG)
        with self._lock:
            self._items[key] = (time.time(), fetched_at, data)
        return fetched_at

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_GLOBAL_CACHE = SourceCache()


class WaterDataClient:
    """HTTP client with timeout, retry/backoff (429/5xx), auth header, cache."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout_s: float = 20.0,
        max_attempts: int = 3,
        cache: Optional[SourceCache] = None,
        ttl_s: float = DEFAULT_TTL_S,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("DATA_GOV_SG_API_KEY")
        self.timeout_s = timeout_s
        self.max_attempts = max(1, max_attempts)
        self.cache = cache if cache is not None else _GLOBAL_CACHE
        self.ttl_s = ttl_s
        self._transport = transport
        self._sleep = sleep

    # -- low level ------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        headers = {"User-Agent": "UrbanOS/1.0 (Water domain)", "Accept": "application/json"}
        if self.api_key:  # optional; raises rate limits when present
            headers["x-api-key"] = self.api_key
        return headers

    def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        """GET with timeout, retry/backoff on 429/5xx and transport errors."""
        last_error = "unknown error"
        for attempt in range(1, self.max_attempts + 1):
            try:
                with httpx.Client(
                    timeout=self.timeout_s,
                    follow_redirects=True,
                    headers=self._headers(),
                    transport=self._transport,
                ) as client:
                    resp = client.get(url, params=params)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_error = f"HTTP {resp.status_code} from {url}"
                    if attempt < self.max_attempts:
                        self._sleep(self._retry_delay(resp, attempt))
                        continue
                    raise WaterSourceError(last_error)
                if resp.status_code >= 400:
                    raise WaterSourceError(f"HTTP {resp.status_code} from {url}")
                return resp
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"{type(exc).__name__} contacting {url}: {exc}"
                if attempt < self.max_attempts:
                    self._sleep(min(2 ** (attempt - 1), 8))
                    continue
                raise WaterSourceError(last_error) from exc
        raise WaterSourceError(last_error)

    def _get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        resp = self._get(url, params)
        try:
            return resp.json()
        except ValueError as exc:
            raise WaterSourceError(f"Invalid JSON from {url}: {exc}") from exc

    @staticmethod
    def _retry_delay(resp: httpx.Response, attempt: int) -> float:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), 30.0))
            except ValueError:
                pass
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
                raise WaterSourceError(f"datastore_search failed for {resource_id}")
            result = payload.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("records"), list):
                raise WaterSourceError(f"Unexpected datastore_search shape for {resource_id}")
            batch = result["records"]
            records.extend(r for r in batch if isinstance(r, dict))
            total = result.get("total")
            offset += len(batch)
            if not batch or not isinstance(total, int) or offset >= total:
                break
            if offset > 50_000:  # hard stop against runaway pagination
                raise WaterSourceError(f"Refusing to page beyond 50k rows for {resource_id}")
        return records

    # -- poll-download (file) ----------------------------------------------
    def _fetch_sensor_layer(self, dataset_id: str, polls: int = 3) -> Dict[str, Any]:
        """Download the sensor-location file. data.gov.sg serves the PUB layer as an XLSX
        workbook (confirmed against the live API); GeoJSON is also accepted."""
        meta_url = POLL_DOWNLOAD_URL.format(dataset_id=dataset_id)
        download_url: Optional[str] = None
        for i in range(polls):
            meta = self._get_json(meta_url)
            if isinstance(meta, dict) and meta.get("code") == 0:
                download_url = (meta.get("data") or {}).get("url")
                if download_url:
                    break
            if i < polls - 1:
                self._sleep(2)
        if not download_url:
            raise WaterSourceError(f"poll-download did not return a file URL for {dataset_id}")
        content = self._get(download_url).content
        if content[:2] == b"PK":  # XLSX is a zip container
            return {"kind": "xlsx", "rows": read_xlsx_rows(content)}
        try:
            data = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise WaterSourceError(f"{dataset_id} download is neither XLSX nor JSON") from exc
        if not isinstance(data, dict) or not isinstance(data.get("features"), list):
            raise WaterSourceError(f"{dataset_id} JSON is not a GeoJSON FeatureCollection")
        return {"kind": "geojson", "data": data}

    # -- cached public API -------------------------------------------------
    def _cached(self, key: str, loader: Callable[[], Any]) -> FetchResult:
        fresh = self.cache.get(key, self.ttl_s)
        if fresh is not None:
            return fresh
        try:
            data = loader()
        except WaterSourceError as exc:
            stale = self.cache.get_any(key)
            if stale is not None:
                stale.error = str(exc)
                return stale
            raise
        return FetchResult(data=data, fetched_at=self.cache.put(key, data))

    def get_records(self, resource_id: str) -> FetchResult:
        return self._cached(f"ds:{resource_id}", lambda: self._fetch_datastore_records(resource_id))

    def get_sensor_layer(self, dataset_id: str) -> FetchResult:
        return self._cached(f"layer:{dataset_id}", lambda: self._fetch_sensor_layer(dataset_id))


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


def parse_year(value: Any) -> Optional[int]:
    num = parse_number(value)
    if num is None or num != int(num):
        return None
    year = int(num)
    return year if 1900 <= year <= 2100 else None


def _pick(record: Dict[str, Any], *candidates: str) -> Any:
    lookup = {_norm_key(k): v for k, v in record.items()}
    for cand in candidates:
        if cand in lookup:
            return lookup[cand]
    return None


SALES_SERIES = {
    "sales_of_potable_water": ("potable_total", "Potable water sales (total)"),
    "domestic_use": ("domestic", "Domestic potable water"),
    "non_domestic_use": ("non_domestic", "Non-domestic potable water"),
    "sales_of_newater": ("newater", "NEWater sales"),
    "sales_of_industrial_water": ("industrial", "Industrial water sales"),
}


def parse_water_sales_annual(records: List[Dict[str, Any]]) -> Dict[str, Dict[int, Optional[float]]]:
    """Parse the wide 'Water Sales, Annual' table (one row per series, one column per year)."""
    out: Dict[str, Dict[int, Optional[float]]] = {}
    for rec in records:
        series_name = None
        for k, v in rec.items():
            nk = _norm_key(k)
            if "series" in nk and isinstance(v, str):
                series_name = v
                break
        if series_name is None:  # fall back: first non-year, non-id text value
            for k, v in rec.items():
                if _norm_key(k) in {"_id", "id"} or re.fullmatch(r"\d{4}", str(k).strip()):
                    continue
                if isinstance(v, str) and parse_number(v) is None:
                    series_name = v
                    break
        if not series_name:
            continue
        mapped = SALES_SERIES.get(_norm_key(series_name))
        if mapped is None:
            continue
        key = mapped[0]
        row: Dict[int, Optional[float]] = {}
        for k, v in rec.items():
            year = parse_year(str(k).strip()) if re.fullmatch(r"\s*\d{4}\s*", str(k)) else None
            if year is None:
                continue
            num = parse_number(v)
            row[year] = num if (num is None or num >= 0) else None
        out[key] = row
    return out


def parse_potable_annual(records: List[Dict[str, Any]]) -> Dict[str, Dict[int, float]]:
    """Parse the long 'Volume of Potable Water sold, Annual' table."""
    out: Dict[str, Dict[int, float]] = {"domestic": {}, "non_domestic": {}}
    for rec in records:
        year = parse_year(_pick(rec, "year"))
        category = _norm_key(_pick(rec, "category") or "")
        value = parse_number(_pick(rec, "sales_of_potable_water", "value"))
        if year is None or value is None or value < 0:
            continue
        if category == "domestic":
            out["domestic"][year] = value
        elif category in {"non_domestic", "nondomestic"}:
            out["non_domestic"][year] = value
    return out


def parse_newater_annual(records: List[Dict[str, Any]]) -> Dict[int, float]:
    out: Dict[int, float] = {}
    for rec in records:
        year = parse_year(_pick(rec, "year"))
        value = parse_number(_pick(rec, "sale_of_newater", "volume_of_newater", "value"))
        if year is not None and value is not None and value >= 0:
            out[year] = value
    return out


_PARAM_KEYS = {
    "escherichia_coli_e_coli": "ecoli",
    "e_coli": "ecoli",
    "ph_value": "ph",
    "turbidity": "turbidity",
    "conductivity": "conductivity",
    "total_dissolved_solids": "tds",
    "colour": "colour",
}


def normalize_unit(unit: Any) -> str:
    """The dataset renders micro as 'æ' (e.g. 'æS/cm'); restore the micro sign."""
    text = str(unit or "").strip()
    return text.replace("æ", "µ").replace("μ", "µ")


def _parse_range(text: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    if not text:
        return None, None
    parts = re.split(r"\s+-\s+|\s*–\s*", str(text).strip())
    if len(parts) == 2:
        lo = parse_number(parts[0].lstrip("<>≤≥ "))
        hi = parse_number(parts[1].lstrip("<>≤≥ "))
        return lo, hi
    return None, None


def parse_water_quality(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return {'year': latest_year, 'rows': [...], 'other_count': n} for the latest year."""
    rows_by_year: Dict[int, List[Dict[str, Any]]] = {}
    for rec in records:
        year = parse_year(_pick(rec, "year"))
        name = str(_pick(rec, "parameter") or "").strip()
        if year is None or not name:
            continue
        avg_text = _pick(rec, "average")
        rng_text = _pick(rec, "range")
        rows_by_year.setdefault(year, []).append(
            {
                "name": name,
                "unit": normalize_unit(_pick(rec, "units", "unit")),
                "average": None if avg_text is None else str(avg_text).strip(),
                "range": None if rng_text is None else str(rng_text).strip(),
            }
        )
    if not rows_by_year:
        return {"year": None, "rows": [], "other_count": 0}
    latest = max(rows_by_year)
    key_rows = [r for r in rows_by_year[latest] if _norm_key(r["name"]) in _PARAM_KEYS]
    for r in key_rows:
        r["key"] = _PARAM_KEYS[_norm_key(r["name"])]
    return {
        "year": latest,
        "rows": key_rows,
        "other_count": len(rows_by_year[latest]) - len(key_rows),
    }


class _ThTdParser(HTMLParser):
    """Extract <th>KEY</th><td>VALUE</td> pairs used in Singapore geospatial Description fields."""

    def __init__(self) -> None:
        super().__init__()
        self.pairs: Dict[str, str] = {}
        self._cell: Optional[str] = None
        self._key: Optional[str] = None
        self._buf: List[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in {"th", "td"}:
            self._cell, self._buf = tag, []

    def handle_data(self, data: str) -> None:
        if self._cell:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == self._cell:
            text = "".join(self._buf).strip()
            if tag == "th":
                self._key = text
            elif self._key is not None:
                self.pairs[self._key.upper()] = text
                self._key = None
            self._cell = None


_NAME_PROPS = ("name", "sensor_name", "station_name", "stn_name", "location", "site_name", "label")


def parse_sensor_geojson(geojson: Dict[str, Any]) -> Tuple[List[DrainSensor], int]:
    """Return (valid sensors, number of invalid/dropped features).

    The property names of the PUB layer could not be inspected from the sandbox used to
    build this module, so name extraction is deliberately defensive: direct property keys
    first, then <th>/<td> pairs inside a 'Description' HTML property, else no name.
    """
    sensors: List[DrainSensor] = []
    invalid = 0
    for idx, feat in enumerate(geojson.get("features") or []):
        try:
            geom = feat.get("geometry") or {}
            if geom.get("type") != "Point":
                invalid += 1
                continue
            coords = geom.get("coordinates") or []
            lon, lat = float(coords[0]), float(coords[1])
            if not (math.isfinite(lon) and math.isfinite(lat)):
                raise ValueError("non-finite")
            if not (SG_LON[0] <= lon <= SG_LON[1] and SG_LAT[0] <= lat <= SG_LAT[1]):
                invalid += 1
                continue
        except (TypeError, ValueError, IndexError, AttributeError):
            invalid += 1
            continue

        props = feat.get("properties") or {}
        norm = {_norm_key(k): v for k, v in props.items()} if isinstance(props, dict) else {}
        name: Optional[str] = None
        for cand in _NAME_PROPS:
            val = norm.get(cand)
            if isinstance(val, str) and val.strip():
                name = val.strip()
                break
        if name is None and isinstance(norm.get("description"), str):
            parser = _ThTdParser()
            try:
                parser.feed(norm["description"])
            except Exception:  # noqa: BLE001 - malformed HTML must not break the layer
                pass
            for cand in ("NAME", "SENSOR_NAME", "STATION_NAME", "LOCATION", "STN_NAME"):
                if parser.pairs.get(cand):
                    name = parser.pairs[cand]
                    break
        sid = str(feat.get("id") or norm.get("id") or f"sensor-{idx + 1}")
        sensors.append(DrainSensor(id=sid, name=name, latitude=lat, longitude=lon))
    return sensors, invalid


# ---------------------------------------------------------------- XLSX (stdlib)
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Za-z]+", ref or "")
    idx = 0
    for ch in (letters.group(0).upper() if letters else "A"):
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def read_xlsx_rows(content: bytes) -> List[List[str]]:
    """Read the first worksheet of an XLSX workbook as rows of strings (no extra dependency)."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = z.namelist()
            shared: List[str] = []
            if "xl/sharedStrings.xml" in names:
                root = ET.fromstring(z.read("xl/sharedStrings.xml"))
                for si in root.iter(f"{_NS}si"):
                    shared.append("".join(t.text or "" for t in si.iter(f"{_NS}t")))
            sheets = sorted(n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
            if not sheets:
                raise WaterSourceError("XLSX workbook has no worksheet")
            sheet = ET.fromstring(z.read(sheets[0]))
    except (zipfile.BadZipFile, ET.ParseError, KeyError) as exc:
        raise WaterSourceError(f"Unreadable XLSX workbook: {exc}") from exc

    rows: List[List[str]] = []
    for row in sheet.iter(f"{_NS}row"):
        cells: Dict[int, str] = {}
        for c in row.iter(f"{_NS}c"):
            ctype = c.get("t")
            if ctype == "inlineStr":
                text = "".join(t.text or "" for t in c.iter(f"{_NS}t"))
            else:
                v = c.find(f"{_NS}v")
                raw = v.text if v is not None and v.text is not None else ""
                if ctype == "s":
                    try:
                        text = shared[int(raw)]
                    except (ValueError, IndexError):
                        text = ""
                else:
                    text = raw
            cells[_col_index(c.get("r", ""))] = text.strip()
        if cells:
            width = max(cells) + 1
            rows.append([cells.get(i, "") for i in range(width)])
    return rows


def svy21_to_wgs84(easting: float, northing: float) -> Tuple[float, float]:
    """Convert SVY21 (EPSG:3414) easting/northing in metres to WGS84 (lat, lon) degrees.

    Transverse Mercator inverse (Snyder) with the official SVY21 parameters. Verified against
    pyproj/EPSG:3414 to well under 1 cm for points across Singapore. SVY21 is WGS84-aligned,
    so no datum shift is needed.
    """
    a = 6378137.0
    f = 1 / 298.257223563
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    lat0, lon0 = math.radians(1.366666666666667), math.radians(103.83333333333333)
    k0, fe, fn = 1.0, 28001.642, 38744.572

    def meridian_arc(phi: float) -> float:
        return a * (
            (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
            - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
            + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
            - (35 * e2 ** 3 / 3072) * math.sin(6 * phi)
        )

    m1 = meridian_arc(lat0) + (northing - fn) / k0
    mu = m1 / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
        + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
        + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
        + (1097 * e1 ** 4 / 512) * math.sin(8 * mu)
    )
    c1 = ep2 * math.cos(phi1) ** 2
    t1 = math.tan(phi1) ** 2
    n1 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    r1 = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    d = (easting - fe) / (n1 * k0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (
        d ** 2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720
    )
    lon = lon0 + (
        d
        - (1 + 2 * t1 + c1) * d ** 3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120
    ) / math.cos(phi1)
    return math.degrees(lat), math.degrees(lon)


# Plausible SVY21 extent (metres) for Singapore incl. surrounding waters; used to decide whether
# an X/Y pair is SVY21 rather than lon/lat.
_SVY21_E = (-5_000.0, 60_000.0)
_SVY21_N = (10_000.0, 60_000.0)

_LAT_NAMES = {"lat", "latitude", "lat_deg", "y_lat"}
_LON_NAMES = {"lon", "lng", "long", "longitude", "lon_deg", "x_long"}
_X_NAMES = {"x", "easting", "x_coord", "svy21_x"}
_Y_NAMES = {"y", "northing", "y_coord", "svy21_y"}
_ID_NAMES = ("sensor_id", "station_id", "stn_id", "id", "objectid", "s_n", "sn", "no")
_WKT_POINT = re.compile(r"POINT\s*Z?\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)")


def _in_sg(lon: float, lat: float) -> bool:
    return SG_LON[0] <= lon <= SG_LON[1] and SG_LAT[0] <= lat <= SG_LAT[1]


def parse_sensor_rows(rows: List[List[str]]) -> Tuple[List[DrainSensor], int]:
    """Parse a tabular sensor layer.

    Recognises (a) latitude/longitude columns, (b) X/Y columns - SVY21 metres (the real PUB file:
    'Station ID, Station Name, X, Y') or lon/lat degrees - or (c) WKT 'POINT (lon lat)' values.
    The PUB file does not declare its CRS; SVY21 is inferred from the magnitudes and confirmed by
    converting known stations (e.g. 'Happy Ave OD (Jln Gembira)' lands in Geylang). Raises with the
    real headers if no coordinates are recognised - we never guess."""
    header_idx, headers = None, []
    for i, row in enumerate(rows[:15]):
        norm = [_norm_key(c) for c in row]
        if (
            (set(norm) & _LAT_NAMES and set(norm) & _LON_NAMES)
            or (set(norm) & _X_NAMES and set(norm) & _Y_NAMES)
            or any("geom" in n or n in {"wkt", "coordinates"} for n in norm)
        ):
            header_idx, headers = i, norm
            break
    if header_idx is None:
        first = [c for c in (rows[0] if rows else []) if c][:12]
        raise WaterSourceError(f"Sensor table has no recognised latitude/longitude columns; first row: {first}")

    def col(names: set) -> Optional[int]:
        for i, n in enumerate(headers):
            if n in names:
                return i
        return None

    lat_i, lon_i = col(_LAT_NAMES), col(_LON_NAMES)
    x_i, y_i = col(_X_NAMES), col(_Y_NAMES)
    name_i = next((i for i, n in enumerate(headers) if n in set(_NAME_PROPS) or n in {"stn_name", "station", "sensor"}), None)
    id_i = next((i for i, n in enumerate(headers) if n in _ID_NAMES), None)
    sensors: List[DrainSensor] = []
    invalid = 0
    for n, row in enumerate(rows[header_idx + 1:], start=1):
        if not any(row):
            continue
        get = lambda i: row[i] if i is not None and i < len(row) else ""  # noqa: E731
        lat = lon = None
        if lat_i is not None and lon_i is not None:
            lat, lon = parse_number(get(lat_i)), parse_number(get(lon_i))
        elif x_i is not None and y_i is not None:
            x, y = parse_number(get(x_i)), parse_number(get(y_i))
            if x is not None and y is not None:
                if _in_sg(x, y):                    # X/Y are really lon/lat degrees
                    lon, lat = x, y
                elif _SVY21_E[0] <= x <= _SVY21_E[1] and _SVY21_N[0] <= y <= _SVY21_N[1]:
                    lat, lon = svy21_to_wgs84(x, y)  # SVY21 metres -> WGS84
        else:
            for cell in row:
                m = _WKT_POINT.search(cell or "")
                if m:
                    lon, lat = float(m.group(1)), float(m.group(2))
                    break
        if lat is None or lon is None:
            invalid += 1
            continue
        if not _in_sg(lon, lat) and _in_sg(lat, lon):  # columns swapped
            lat, lon = lon, lat
        if not _in_sg(lon, lat):
            invalid += 1
            continue
        sensors.append(DrainSensor(
            id=(get(id_i) or f"sensor-{n}"), name=(get(name_i) or None), latitude=lat, longitude=lon))
    return sensors, invalid


def parse_sensor_layer(payload: Dict[str, Any]) -> Tuple[List[DrainSensor], int]:
    """Dispatch on the downloaded layer type (XLSX rows or GeoJSON)."""
    if payload.get("kind") == "xlsx":
        return parse_sensor_rows(payload.get("rows") or [])
    if payload.get("kind") == "geojson":
        return parse_sensor_geojson(payload.get("data") or {})
    raise WaterSourceError("Unknown sensor layer format")


# ======================================================================
# Snapshot
# ======================================================================
@dataclass
class WaterSnapshot:
    generated_at: datetime
    sales: Dict[str, Dict[int, Optional[float]]] = field(default_factory=dict)
    potable: Dict[str, Dict[int, float]] = field(default_factory=dict)
    newater_long: Dict[int, float] = field(default_factory=dict)
    quality: Dict[str, Any] = field(default_factory=dict)
    sensors: List[DrainSensor] = field(default_factory=list)
    invalid_sensors: int = 0
    sources: List[SourceInfo] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


SOURCE_CATALOG: List[Dict[str, str]] = [
    dict(
        key="water_sales_annual", organization="Ministry of Sustainability and the Environment / PUB (via SingStat)",
        name="Water Sales, Annual", identifier=WATER_SALES_ID,
        url=f"https://data.gov.sg/datasets/{WATER_SALES_ID}/view",
        purpose="Potable (total/domestic/non-domestic), NEWater and industrial water sales",
        update_frequency="Annual", coverage="2015-2025 (as shown on the dataset page, 30 Sep 2026)",
        authentication="None required (optional x-api-key raises rate limits)",
        data_kind="latest_available", component="Water Supply, Water Usage, NEWater",
    ),
    dict(
        key="potable_annual", organization="PUB", name="Volume of Potable Water sold, Annual",
        identifier=POTABLE_ID, url=f"https://data.gov.sg/datasets/{POTABLE_ID}/view",
        purpose="Longer domestic vs non-domestic potable history",
        update_frequency="Annual", coverage="2008-2025 (as shown on the dataset page)",
        authentication="None required (optional x-api-key)", data_kind="historical",
        component="Water Usage",
    ),
    dict(
        key="newater_annual", organization="PUB", name="Volume of NEWater sold, Annual",
        identifier=NEWATER_ID, url=f"https://data.gov.sg/datasets/{NEWATER_ID}/view",
        purpose="Long-run NEWater sales history",
        update_frequency="Annual",
        coverage="2007-2025 (confirmed from the live API on 30 Sep 2026)", authentication="None required (optional x-api-key)",
        data_kind="historical", component="NEWater",
    ),
    dict(
        key="drinking_quality", organization="PUB", name="Drinking water quality datasets",
        identifier=QUALITY_ID, url=f"https://data.gov.sg/datasets/{QUALITY_ID}/view",
        purpose="Annual average/range of pH, turbidity, E. coli, conductivity, TDS and others",
        update_frequency="Annual", coverage="2023-2025 (as shown on the dataset page)",
        authentication="None required (optional x-api-key)", data_kind="latest_available",
        component="Water Quality",
    ),
    dict(
        key="drain_sensors", organization="PUB", name="PUB Water Level Sensors",
        identifier=SENSORS_ID, url=f"https://data.gov.sg/datasets/{SENSORS_ID}/view",
        purpose="Locations of PUB drain/canal water-level sensors (Station ID, Name, X/Y in SVY21 -> converted to WGS84; no readings)",
        update_frequency="Periodic (dataset page showed 'last updated 13 Apr 2026')",
        coverage="Static sensor locations, delivered as an XLSX file", authentication="None required",
        data_kind="latest_available", component="Drain Condition (map)",
    ),
]


def _source(key: str) -> SourceInfo:
    spec = next(s for s in SOURCE_CATALOG if s["key"] == key)
    return SourceInfo(**spec)  # type: ignore[arg-type]


def _latest_period(years: List[int]) -> Optional[str]:
    return str(max(years)) if years else None


def fetch_water_snapshot(client: Optional[WaterDataClient] = None) -> WaterSnapshot:
    """Fetch and parse every source. Each failure is isolated and recorded."""
    client = client or WaterDataClient()
    snap = WaterSnapshot(generated_at=datetime.now(SG))

    def finish(
        key: str,
        res: Optional[FetchResult],
        parsed: Any,
        error: Optional[BaseException],
        apply: Callable[[Any], Tuple[Optional[str], int]],
    ) -> None:
        """Record one source's outcome on the snapshot (runs sequentially, in catalog order)."""
        info = _source(key)
        try:
            if error is not None:
                raise error
            assert res is not None
            period, count = apply(parsed)
            info.last_fetched_at = res.fetched_at
            info.latest_data_period = period
            info.record_count = count
            if res.stale:
                info.status = "stale_cache"
                info.error = res.error
                snap.warnings.append(f"{info.name}: live refresh failed; showing last cached copy ({res.error})")
            else:
                info.status = "ok"
            if count == 0:
                info.status = "unavailable"
                info.error = "Source responded but no usable rows were parsed"
                snap.errors.append(f"{info.name}: no usable rows parsed")
        except WaterSourceError as exc:
            info.status = "unavailable"
            info.error = str(exc)
            snap.errors.append(f"{info.name}: {exc}")
        except Exception as exc:  # noqa: BLE001 - never let one source break the module
            log.error("Unexpected error processing %s", key, exc_info=exc)
            info.status = "unavailable"
            info.error = scrub_urls(f"Unexpected error: {exc}")
            snap.errors.append(scrub_urls(f"{info.name}: unexpected error: {exc}"))
        snap.sources.append(info)

    def apply_sales(p: Any) -> Tuple[Optional[str], int]:
        snap.sales = p
        years = [y for row in p.values() for y, v in row.items() if v is not None]
        return _latest_period(years), sum(len(r) for r in p.values())

    def apply_potable(p: Any) -> Tuple[Optional[str], int]:
        snap.potable = p
        years = [y for row in p.values() for y in row]
        return _latest_period(years), sum(len(r) for r in p.values())

    def apply_newater(p: Any) -> Tuple[Optional[str], int]:
        snap.newater_long = p
        return _latest_period(list(p)), len(p)

    def apply_quality(p: Any) -> Tuple[Optional[str], int]:
        snap.quality = p
        return (str(p["year"]) if p.get("year") else None), len(p.get("rows", []))

    def apply_sensors(p: Any) -> Tuple[Optional[str], int]:
        snap.sensors, snap.invalid_sensors = p
        return None, len(snap.sensors)

    # The five sources are independent, so acquire them concurrently: total wait is roughly the
    # slowest single source instead of the sum of all five. Results are applied in catalog order,
    # so output stays deterministic.
    tasks = [
        ("water_sales_annual", lambda: client.get_records(WATER_SALES_ID), parse_water_sales_annual, apply_sales),
        ("potable_annual", lambda: client.get_records(POTABLE_ID), parse_potable_annual, apply_potable),
        ("newater_annual", lambda: client.get_records(NEWATER_ID), parse_newater_annual, apply_newater),
        ("drinking_quality", lambda: client.get_records(QUALITY_ID), parse_water_quality, apply_quality),
        ("drain_sensors", lambda: client.get_sensor_layer(SENSORS_ID), parse_sensor_layer, apply_sensors),
    ]

    def acquire(task: Any) -> Tuple[Optional[FetchResult], Any, Optional[BaseException]]:
        _key, fetch, parse, _apply = task
        try:
            res = fetch()
            return res, parse(res.data), None
        except Exception as exc:  # noqa: BLE001 - reported per source in finish()
            return None, None, exc

    with ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="water-src") as pool:
        outcomes = list(pool.map(acquire, tasks))
    for (key, _fetch, _parse, apply), (res, parsed, error) in zip(tasks, outcomes):
        finish(key, res, parsed, error, apply)
    return snap
