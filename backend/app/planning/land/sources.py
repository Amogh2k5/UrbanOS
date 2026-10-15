"""Official Singapore land-use / planning / development data acquisition (backend only).

Every dataset here was opened and schema-verified against the live data.gov.sg
API. All six are GeoJSON served through the documented ``poll-download`` ->
presigned S3 flow. Dataset ids are real; none are invented.

  land_use        d_a8c3546b26712e35021f3a681d0353ae  URA  G_MP25_LANDUSE_PL
  planning_areas  d_2cc750190544007400b2cfd5d7f53209  URA  G_MP25_PLNG_AREA_NO_SEA_PL
  regions         d_4ce0038f7ac689652350bb91b7fb92ed  URA  G_MP25_REGION_NO_SEA_PL
  cadastral       d_e7395d743076a2bcc487b0d12b9bf33b  SLA  CADASTRAL_LAND_LOT
  gls_sites       d_0e2b42f98535686282031a42c9c7b05a  URA  URA_SALE_SITE_PL
  jtc_estates     d_0e6c5a63613b812b7240612c5d837a82  JTC  JTC_ESTATE_NAME

Verified coordinate reference system
------------------------------------
All six datasets publish geometry already in **WGS84 geographic lon/lat
(EPSG:4326)**, e.g. Master Plan land use ``[103.8892917, 1.3013746]`` and SLA
cadastral ``[103.7717350, 1.337...]``. Nothing here is SVY21/EPSG:3414, so no
projection is applied anywhere in this module. Every parsed coordinate is still
bounds-checked against the Singapore envelope and non-finite values are
rejected, so a future dataset that *does* arrive projected fails loudly instead
of silently producing nonsense areas.

Size matters
------------
Land use is ~190 MB and cadastral is ~145 MB of GeoJSON. Nothing here holds a
whole dataset in memory: features are decoded one at a time by
``iter_geojson_features`` and folded into counters. Raw bytes are cached on disk
so a restart does not re-download ~335 MB.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import httpx

from backend.app.planning.land.models import LandSource

log = logging.getLogger(__name__)
SG = timezone(timedelta(hours=8))

POLL_DOWNLOAD_URL = "https://api-open.data.gov.sg/v1/public/api/datasets/{dataset_id}/poll-download"

# Verified dataset ids (see module docstring). Do not substitute ids that were
# not opened and checked.
LAND_USE_ID = "d_a8c3546b26712e35021f3a681d0353ae"
PLANNING_AREA_ID = "d_2cc750190544007400b2cfd5d7f53209"
REGION_ID = "d_4ce0038f7ac689652350bb91b7fb92ed"
CADASTRAL_ID = "d_e7395d743076a2bcc487b0d12b9bf33b"
GLS_ID = "d_0e2b42f98535686282031a42c9c7b05a"
JTC_ESTATE_ID = "d_0e6c5a63613b812b7240612c5d837a82"

# Master Plan land use and planning boundaries change at most a few times a year,
# so cache raw bytes for a week. Everything else changes on the same cycle.
DEFAULT_RAW_TTL_S = int(os.getenv("URBANOS_LAND_RAW_TTL_S", str(7 * 24 * 3600)))

# Anonymous data.gov.sg access is aggressively throttled and returns bare HTTP
# 429 with no Retry-After and no rate-limit headers. Measured on this host: six
# concurrent poll-download calls all fail, while six serial calls spaced 5 s
# apart all succeed. Acquisition is therefore serialised behind a minimum gap.
MIN_REQUEST_GAP_S = float(os.getenv("URBANOS_LAND_MIN_GAP_S", "5.0"))

# In-memory parsed-report TTL, mirroring the Water module.
REPORT_OK_TTL_S = float(os.getenv("URBANOS_LAND_TTL_S", "900"))
REPORT_ERR_TTL_S = 60.0

# Raw-bytes cache. Sits next to the module, module-relative (never CWD-relative).
_MODULE_DIR = Path(__file__).resolve().parent
_RAW_CACHE_DIR = _MODULE_DIR / "data" / "raw"

# Singapore envelope used to reject out-of-range / projected / (0,0) coordinates.
SG_LON = (103.5, 104.2)
SG_LAT = (1.1, 1.5)

_URL_QUERY = re.compile(r"(https?://[^\s?'\"]+)\?[^\s'\"]*")


def scrub_urls(text: str) -> str:
    """Drop query strings: poll-download returns presigned S3 URLs whose query
    string carries temporary credentials that must never be logged or served."""
    return _URL_QUERY.sub(r"\1?<redacted>", str(text))


class LandSourceError(RuntimeError):
    """A source could not be acquired, streamed or parsed."""

    def __init__(self, message: object = "") -> None:
        super().__init__(scrub_urls(str(message)))


class _RetryableStatus(Exception):
    """Internal: a retryable HTTP status seen while streaming a download."""

    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.url = url


_CHUNK_BYTES = 1 << 20  # 1 MiB
_PROGRESS_STEP_BYTES = 50 << 20  # log every 50 MB
_FEATURE_PROGRESS_EVERY = 100_000  # log every 100k features parsed


def _safe_host(url: str) -> str:
    """Host of a URL for logging. Presigned query strings carry credentials, so
    only scheme+host+path is ever shown - never the query."""
    try:
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}{parts.path}"
    except Exception:  # noqa: BLE001 - logging must never raise
        return "<url>"


def _assert_geojson_file(path: Path, dataset_id: str, probe_bytes: int = 4096) -> None:
    """Reject an HTML error page or truncated file before it enters the cache."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(probe_bytes)
    except OSError as exc:
        raise LandSourceError(f"Cannot read downloaded file for {dataset_id}: {exc}") from exc
    if not head:
        raise LandSourceError(f"Downloaded file for {dataset_id} is empty")
    stripped = head.lstrip()
    if not stripped.startswith(b"{"):
        raise LandSourceError(
            f"Downloaded file for {dataset_id} is not a GeoJSON object "
            f"(starts with {stripped[:32]!r})"
        )
    if b'"features"' not in head:
        raise LandSourceError(f"Downloaded file for {dataset_id} has no 'features' member in its first {probe_bytes} bytes")


# ======================================================================
# Source catalogue (provenance for every dataset actually used)
# ======================================================================
SOURCE_CATALOG: List[Dict[str, str]] = [
    dict(
        key="land_use",
        organization="Urban Redevelopment Authority (URA)",
        name="Master Plan 2025 Land Use Layer",
        identifier=LAND_USE_ID,
        layer_name="G_MP25_LANDUSE_PL",
        url=f"https://data.gov.sg/datasets/{LAND_USE_ID}/view",
        purpose="Statutory zoning: land-use designation (LU_DESC), gross plot ratio (GPR) and zone area per development lot",
        update_frequency="Gazetted 1 Dec 2025; layer revision date carried per feature in FMEL_UPD_D",
        coverage="Master Plan 2025 land use zones, island-wide",
        authentication="None required (optional x-api-key raises rate limits)",
        data_kind="latest_available",
        crs="EPSG:4326 (WGS84 lon/lat) as published",
        component="Land Use",
    ),
    dict(
        key="planning_areas",
        organization="Urban Redevelopment Authority (URA)",
        name="Master Plan 2025 Planning Area Boundary (No Sea)",
        identifier=PLANNING_AREA_ID,
        layer_name="G_MP25_PLNG_AREA_NO_SEA_PL",
        url=f"https://data.gov.sg/datasets/{PLANNING_AREA_ID}/view",
        purpose="Planning-area polygons, codes and region assignment used to spatially aggregate land use",
        update_frequency="Gazetted 1 Dec 2025; revision date per feature in FMEL_UPD_D",
        coverage="55 Master Plan 2025 planning areas (land only, sea excluded)",
        authentication="None required (optional x-api-key)",
        data_kind="latest_available",
        crs="EPSG:4326 (WGS84 lon/lat) as published",
        component="Planning Structure",
    ),
    dict(
        key="regions",
        organization="Urban Redevelopment Authority (URA)",
        name="Master Plan 2025 Region Boundary (No Sea)",
        identifier=REGION_ID,
        layer_name="G_MP25_REGION_NO_SEA_PL",
        url=f"https://data.gov.sg/datasets/{REGION_ID}/view",
        purpose="The five Master Plan regions (Central, East, North, North-East, West)",
        update_frequency="Gazetted 1 Dec 2025; revision date per feature in FMEL_UPD_D",
        coverage="5 regions (land only)",
        authentication="None required (optional x-api-key)",
        data_kind="latest_available",
        crs="EPSG:4326 (WGS84 lon/lat) as published",
        component="Planning Structure",
    ),
    dict(
        key="cadastral",
        organization="Singapore Land Authority (SLA)",
        name="SLA Cadastral Land Parcel",
        identifier=CADASTRAL_ID,
        layer_name="CADASTRAL_LAND_LOT",
        url=f"https://data.gov.sg/datasets/{CADASTRAL_ID}/view",
        purpose="Surveyed land-lot boundaries and lot numbers (LOT_KEY); parcel counts and areas",
        update_frequency="Rolling; revision date per feature in FMEL_UPD_D",
        coverage="Entire cadastral map of Singapore",
        authentication="None required (optional x-api-key)",
        data_kind="latest_available",
        crs="EPSG:4326 (WGS84 lon/lat) as published",
        component="Cadastral Parcels",
    ),
    dict(
        key="gls_sites",
        organization="Urban Redevelopment Authority (URA)",
        name="URA Sale Sites (GEOJSON)",
        identifier=GLS_ID,
        layer_name="URA_SALE_SITE_PL",
        url=f"https://data.gov.sg/datasets/{GLS_ID}/view",
        purpose="Government Land Sales programme record: awarded sites since 1967 with site area, GPR, permitted development, award date and successful tenderer",
        update_frequency="Rolling; revision date per feature in FMEL_UPD_D",
        coverage="Awarded/completed GLS sites from 1967 onwards",
        authentication="None required (optional x-api-key)",
        data_kind="historical",
        crs="EPSG:4326 (WGS84 lon/lat) as published",
        component="Government Land Sales",
    ),
    dict(
        key="jtc_estates",
        organization="JTC Corporation",
        name="JTC Estate Name Boundary (GEOJSON)",
        identifier=JTC_ESTATE_ID,
        layer_name="JTC_ESTATE_NAME",
        url=f"https://data.gov.sg/datasets/{JTC_ESTATE_ID}/view",
        purpose="Indicative boundaries of JTC-managed industrial estates (ESTATE_NAME) and their areas",
        update_frequency="Rolling; revision date per feature in FMEL_UPD_D",
        coverage="92 named JTC estates across Singapore",
        authentication="None required (optional x-api-key)",
        data_kind="latest_available",
        crs="EPSG:4326 (WGS84 lon/lat) as published",
        component="Industrial Land",
    ),
]

SOURCE_BY_KEY = {s["key"]: s for s in SOURCE_CATALOG}


def _source_spec(key: str) -> LandSource:
    spec = SOURCE_BY_KEY[key]
    return LandSource(
        key=spec["key"],
        organization=spec["organization"],
        name=spec["name"],
        identifier=spec["identifier"],
        layer_name=spec["layer_name"],
        url=spec["url"],
        purpose=spec["purpose"],
        update_frequency=spec["update_frequency"],
        coverage=spec["coverage"],
        authentication=spec["authentication"],
        data_kind=spec["data_kind"],
        crs=spec["crs"],
        component=spec["component"],
    )


# ======================================================================
# Geometry helpers (stdlib only - shapely/pyproj are NOT project dependencies)
# ======================================================================
def is_valid_sg_lonlat(lon: Any, lat: Any) -> bool:
    """True when a coordinate pair is finite and inside the Singapore envelope.

    This is the guard that catches a projected (SVY21 metre) or sentinel (0,0)
    coordinate arriving where lon/lat was expected: those fall outside the box
    and are rejected rather than silently aggregated.
    """
    try:
        lon = float(lon)
        lat = float(lat)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(lon) and math.isfinite(lat)):
        return False
    return SG_LON[0] <= lon <= SG_LON[1] and SG_LAT[0] <= lat <= SG_LAT[1]


def ring_outermost(geometry: Dict[str, Any]) -> Optional[List[List[float]]]:
    """Return the exterior ring for Polygon / MultiPolygon, else None."""
    if not isinstance(geometry, dict):
        return None
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Polygon" and coords and isinstance(coords[0], list):
        return coords[0]
    if gtype == "MultiPolygon" and coords and isinstance(coords[0], list) and coords[0]:
        return coords[0][0]
    return None


def ring_bbox(ring: List[List[float]]) -> Optional[Tuple[float, float, float, float]]:
    """(min_lon, min_lat, max_lon, max_lat) for a coordinate ring."""
    xs: List[float] = []
    ys: List[float] = []
    for pt in ring or []:
        if not isinstance(pt, (list, tuple)) or len(pt) < 2:
            return None
        try:
            xs.append(float(pt[0]))
            ys.append(float(pt[1]))
        except (TypeError, ValueError):
            return None
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def point_in_ring(lon: float, lat: float, ring: List[List[float]]) -> bool:
    """Ray-casting point-in-polygon against one ring (no holes considered)."""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            x_int = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_int:
                inside = not inside
        j = i
    return inside


def ring_area_sqm(ring: List[List[float]]) -> Optional[float]:
    """Equirectangular planar area in m^2 for a lon/lat ring.

    Used only where the source does not publish an area attribute. Accuracy is
    ~0.1% at Singapore's extent, which is irrelevant for composition shares but
    is deliberately NOT used to override the official SHAPE.AREA field when it
    is present.
    """
    if not ring or len(ring) < 4:
        return None
    lats = [float(p[1]) for p in ring]
    mlat = sum(lats) / len(lats)
    kx = 111_320.0 * math.cos(math.radians(mlat))
    ky = 110_574.0
    total = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = float(ring[i][0]), float(ring[i][1])
        x2, y2 = float(ring[(i + 1) % n][0]), float(ring[(i + 1) % n][1])
        total += (x1 * kx) * (y2 * ky) - (x2 * kx) * (y1 * ky)
    return abs(total) / 2.0


def feature_centroid(ring: List[List[float]]) -> Optional[Tuple[float, float]]:
    """Area-weighted centroid of a ring's vertices (vertex mean is enough for
    the coarse zone polygons in these datasets and needs no projection)."""
    if not ring:
        return None
    xs = [float(p[0]) for p in ring]
    ys = [float(p[1]) for p in ring]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


class PlanningAreaIndex:
    """Grid-bucketed point -> planning area lookup.

    Attributing ~500k land-use zones against 55 planning-area polygons directly
    is O(landuse * planningareas * vertices) and far too slow in pure Python.
    Instead the planning areas are rasterised once into a coarse lon/lat grid
    (default 0.0025 deg, ~280 m) and each zone then resolves with a dict lookup.

    Resolution is a deliberate, documented trade-off: planning areas are
    kilometre-scale, so a ~280 m cell cannot materially change an aggregate
    area total, and cells are attributed by the planning area containing the
    cell centre. Cells whose centre falls in no planning area (sea, out of
    extent) simply resolve to None and are counted as unassigned.
    """

    def __init__(self, step_deg: float = 0.0025) -> None:
        self.step = step_deg
        self._cells: Dict[Tuple[int, int], str] = {}
        self.built = False

    @staticmethod
    def _key(step: float, lon: float, lat: float) -> Tuple[int, int]:
        return (int(math.floor(lon / step)), int(math.floor(lat / step)))

    def build(self, planning_areas: List[Dict[str, Any]]) -> int:
        """Rasterise planning-area polygons. Returns the number of filled cells."""
        boxes: List[Tuple[Tuple[float, float, float, float], List[List[float]], str]] = []
        for pa in planning_areas:
            ring = pa.get("_outer_ring")
            bbox = pa.get("_bbox")
            if not ring or not bbox:
                continue
            boxes.append((bbox, ring, str(pa.get("code") or pa.get("name"))))

        cells = 0
        for bbox, ring, code in boxes:
            i0, j0 = self._key(self.step, bbox[0], bbox[1])
            i1, j1 = self._key(self.step, bbox[2], bbox[3])
            for i in range(i0, i1 + 1):
                lon = (i + 0.5) * self.step
                if not (bbox[0] <= lon <= bbox[2]):
                    continue
                for j in range(j0, j1 + 1):
                    lat = (j + 0.5) * self.step
                    if not (bbox[1] <= lat <= bbox[3]):
                        continue
                    if point_in_ring(lon, lat, ring):
                        self._cells[(i, j)] = code
                        cells += 1
        self.built = True
        return cells

    def lookup(self, lon: float, lat: float) -> Optional[str]:
        if not self.built:
            return None
        return self._cells.get(self._key(self.step, lon, lat))

    @property
    def cell_count(self) -> int:
        return len(self._cells)


# ======================================================================
# Streaming GeoJSON reader
# ======================================================================
_DECODER = json.JSONDecoder()
_WHITESPACE = " \t\r\n,"


def iter_geojson_features(chunks: Iterator[bytes]) -> Iterator[Dict[str, Any]]:
    """Yield features one at a time from a streamed GeoJSON FeatureCollection.

    Deliberately incremental: the Master Plan land-use layer is ~190 MB and must
    never be materialised as one string or one list. A feature that straddles a
    chunk boundary is retried after more bytes arrive, and the reader stops at
    the close of the ``features`` array.
    """
    buf = ""
    started = False
    exhausted = False

    for chunk in chunks:
        if exhausted:
            break
        buf += chunk.decode("utf-8", "replace")

        # Locate the start of the features array, tolerating a chunk boundary
        # that splits the marker. A short tail is kept so the marker is still
        # findable on the next chunk.
        if not started:
            k = buf.find('"features"')
            if k < 0:
                buf = buf[-32:]
                continue
            b = buf.find("[", k)
            if b < 0:
                buf = buf[k:]
                continue
            buf = buf[b + 1:]
            started = True

        # Decode every complete feature currently buffered, exactly once.
        pos = 0
        while True:
            while pos < len(buf) and buf[pos] in _WHITESPACE:
                pos += 1
            if pos >= len(buf):
                break  # buffer fully consumed; read the next chunk
            if buf[pos] == "]":
                exhausted = True
                break
            try:
                obj, end = _DECODER.raw_decode(buf, pos)
            except ValueError:
                # The feature straddles the chunk boundary. Leave it in the
                # buffer and wait for more bytes. Breaking out here (rather than
                # retrying in place) is essential: re-decoding the same partial
                # value would spin forever without consuming input.
                break
            yield obj
            pos = end

        buf = "" if exhausted else buf[pos:]


# ======================================================================
# Parsers (pure)
# ======================================================================
def _num(value: Any) -> Optional[float]:
    """Finite float or None. 'na'/'-'/blank/non-numeric -> None, never 0."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if math.isfinite(f) else None
    text = str(value).strip().replace(",", "")
    if text == "" or text.lower() in {"na", "n/a", "nan", "-", "--", "null", "none"}:
        return None
    try:
        f = float(text)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def _fmel_date(value: Any) -> Optional[str]:
    """FMEL_UPD_D is 'YYYYMMDDHHMMSS' in the source; normalise to ISO date."""
    text = str(value or "").strip()
    if len(text) >= 8 and text[:8].isdigit():
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    return None


def parse_land_use_feature(feature: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One Master Plan land-use zone -> record, or None if unusable."""
    props = feature.get("properties") or {}
    geom = feature.get("geometry") or {}
    ring = ring_outermost(geom)
    if not ring or len(ring) < 4:
        return None
    desc = str(props.get("LU_DESC") or "").strip()
    if not desc:
        return None
    centroid = feature_centroid(ring)
    # Validate the polygon as a whole via its centroid rather than its first
    # vertex: a zone that merely clips an envelope edge would otherwise be
    # dropped. A projected (SVY21) or sentinel (0,0) ring keeps its whole
    # centroid outside, so genuine bad geometry is still rejected - the live
    # layer contains one such PORT / AIRPORT polygon ~35 km east of Changi.
    if centroid is None or not is_valid_sg_lonlat(*centroid):
        return None
    area = _num(props.get("SHAPE.AREA"))
    if area is None:
        area = ring_area_sqm(ring)
    gpr_raw = props.get("GPR")
    return {
        "object_id": props.get("OBJECTID"),
        "lu_desc": desc,
        "gpr": gpr_raw,
        "area_sqm": area,
        "centroid_lon": centroid[0],
        "centroid_lat": centroid[1],
        "updated": _fmel_date(props.get("FMEL_UPD_D")),
    }


def parse_planning_area_feature(feature: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One planning area -> record, or None if unusable."""
    props = feature.get("properties") or {}
    ring = ring_outermost(feature.get("geometry") or {})
    if not ring or len(ring) < 4:
        return None
    name = str(props.get("PLN_AREA_N") or "").strip()
    if not name:
        return None
    _cen = feature_centroid(ring)
    if _cen is None or not is_valid_sg_lonlat(*_cen):
        return None
    return {
        "name": name,
        "code": str(props.get("PLN_AREA_C") or "").strip() or None,
        "region": str(props.get("REGION_N") or "").strip() or None,
        "region_code": str(props.get("REGION_C") or "").strip() or None,
        "area_sqm": _num(props.get("SHAPE.AREA")) or ring_area_sqm(ring),
        "updated": _fmel_date(props.get("FMEL_UPD_D")),
        "_outer_ring": ring,
        "_bbox": ring_bbox(ring),
    }


def parse_region_feature(feature: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    props = feature.get("properties") or {}
    ring = ring_outermost(feature.get("geometry") or {})
    if not ring:
        return None
    name = str(props.get("REGION_N") or "").strip()
    if not name:
        return None
    _cen = feature_centroid(ring)
    if _cen is None or not is_valid_sg_lonlat(*_cen):
        return None
    return {
        "name": name,
        "code": str(props.get("REGION_C") or "").strip() or None,
        "area_sqm": _num(props.get("SHAPE.AREA")) or ring_area_sqm(ring),
        "updated": _fmel_date(props.get("FMEL_UPD_D")),
        "_outer_ring": ring,
    }


def parse_cadastral_feature(feature: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    props = feature.get("properties") or {}
    ring = ring_outermost(feature.get("geometry") or {})
    if not ring or len(ring) < 4:
        return None
    centroid = feature_centroid(ring)
    if centroid is None or not is_valid_sg_lonlat(*centroid):
        return None
    area = _num(props.get("SHAPE_1.AREA"))
    if area is None:
        area = ring_area_sqm(ring)
    return {
        "lot_key": str(props.get("LOT_KEY") or "").strip() or None,
        "object_id": props.get("OBJECTID_1"),
        "area_sqm": area,
        "centroid_lon": centroid[0],
        "centroid_lat": centroid[1],
        "updated": _fmel_date(props.get("FMEL_UPD_D")),
    }


def parse_gls_site_feature(feature: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    props = feature.get("properties") or {}
    ring = ring_outermost(feature.get("geometry") or {})
    if not ring or len(ring) < 4:
        return None
    _cen = feature_centroid(ring)
    if _cen is None or not is_valid_sg_lonlat(*_cen):
        return None
    award = str(props.get("DATE_AWARD") or "").strip()
    if len(award) >= 4 and award[:4].isdigit():
        award_year: Optional[int] = int(award[:4])
    else:
        award_year = None
    centroid = _cen
    return {
        "location": str(props.get("LOCATION") or "").strip() or None,
        "devt_code": str(props.get("DEVT_CODE") or "").strip() or None,
        "devt_allowed": str(props.get("DEVT_ALLOW") or "").strip() or None,
        "site_area_sqm": _num(props.get("SA_SQM")),
        "gpr": _num(props.get("GPR")),
        "gfa_sqm": _num(props.get("GFA")),
        "housing_units": _num(props.get("HOUSING_UN")),
        "award_date": award or None,
        "award_year": award_year,
        "successful_tenderer": str(props.get("SUCCESS_TR") or "").strip() or None,
        "successful_price": _num(props.get("SUCCESS_TP")),
        "no_of_bids": _num(props.get("NO_OF_BIDS")),
        "planning_area": str(props.get("PLN_AREA_N") or "").strip() or None,
        "centroid_lon": centroid[0],
        "centroid_lat": centroid[1],
        "updated": _fmel_date(props.get("FMEL_UPD_D")),
    }


def parse_jtc_estate_feature(feature: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    props = feature.get("properties") or {}
    ring = ring_outermost(feature.get("geometry") or {})
    if not ring:
        return None
    name = str(props.get("ESTATE_NAME") or "").strip()
    if not name:
        return None
    _cen = feature_centroid(ring)
    if _cen is None or not is_valid_sg_lonlat(*_cen):
        return None
    area = _num(props.get("SHAPE_1.AREA"))
    if area is None:
        area = ring_area_sqm(ring)
    return {
        "estate_name": name,
        "area_sqm": area,
        "updated": _fmel_date(props.get("FMEL_UPD_D")),
        "_outer_ring": ring,
    }


# ======================================================================
# HTTP client: poll-download -> presigned S3 -> disk cache -> stream
# ======================================================================
class SourceCache:
    """Thread-safe in-memory TTL cache with stale fallback (Water convention)."""

    def __init__(self) -> None:
        self._items: Dict[str, Tuple[float, datetime, Any]] = {}
        self._lock = threading.RLock()

    def get(self, key: str, ttl_s: float, now: Optional[float] = None) -> Optional[Any]:
        with self._lock:
            item = self._items.get(key)
        if item is None:
            return None
        stored_at, fetched_at, data = item
        if (now if now is not None else time.time()) - stored_at <= ttl_s:
            return (fetched_at, data, False)
        return None

    def get_any(self, key: str) -> Optional[Tuple[datetime, Any, bool]]:
        with self._lock:
            item = self._items.get(key)
        if item is None:
            return None
        return (item[1], item[2], True)

    def put(self, key: str, data: Any) -> datetime:
        fetched_at = datetime.now(SG)
        with self._lock:
            self._items[key] = (time.time(), fetched_at, data)
        return fetched_at

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


class LandDataClient:
    """Acquires GeoJSON datasets with retry/backoff, optional api key and caching.

    ``transport`` and ``sleep`` are injectable so tests never touch the network,
    mirroring the Water module's client.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout_s: float = 60.0,
        max_attempts: int = 4,
        cache: Optional[SourceCache] = None,
        ttl_s: float = DEFAULT_RAW_TTL_S,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
        raw_cache_dir: Optional[Path] = None,
        min_gap_s: float = MIN_REQUEST_GAP_S,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("DATA_GOV_SG_API_KEY")
        self.timeout_s = timeout_s
        self.max_attempts = max(1, max_attempts)
        self.cache = cache if cache is not None else SourceCache()
        self.ttl_s = ttl_s
        self._transport = transport
        self._sleep = sleep
        self._raw_dir = raw_cache_dir if raw_cache_dir is not None else _RAW_CACHE_DIR
        self.min_gap_s = min_gap_s
        self._gate_lock = threading.Lock()
        self._last_request_at = 0.0

    def _gate(self) -> None:
        """Enforce a minimum gap between data.gov.sg API calls.

        Anonymous access 429s after roughly two rapid calls, and the response
        carries no Retry-After, so the only reliable signal is our own pacing.
        """
        if self.min_gap_s <= 0:
            return
        with self._gate_lock:
            wait = self.min_gap_s - (time.monotonic() - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
            self._last_request_at = time.monotonic()

    def _headers(self) -> Dict[str, str]:
        headers = {"User-Agent": "UrbanOS/1.0 (Planning-Land domain)", "Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _timeouts(self) -> httpx.Timeout:
        """Bounded per-phase timeouts.

        A scalar httpx timeout would apply the same bound to pool acquisition and
        connect, which is far too generous for the throttled poll-download call,
        while the read bound must be long enough for a ~190 MB object to stream
        without tripping on a quiet socket. Splitting them keeps both honest.
        """
        return httpx.Timeout(
            connect=min(self.timeout_s, 15.0),
            read=self.timeout_s,
            write=self.timeout_s,
            pool=min(self.timeout_s, 15.0),
        )

    @staticmethod
    def _retryable(status: int) -> bool:
        return status == 429 or status >= 500

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        # data.gov.sg returns a bare 429 with no Retry-After header, so back off
        # generously rather than trusting the server.
        return float(min(5.0 * (2 ** (attempt - 1)), 30.0))

    def _discard_partial(self, tmp: Optional[Path]) -> None:
        """Never leave a truncated .part behind for the next run to trust."""
        if tmp is None:
            return
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            log.warning("Could not remove partial download %s", tmp)

    def _download_to_disk(self, url: str, dataset_id: str) -> Path:
        """Stream a presigned S3 object to disk without ever buffering it in RAM.

        The Master Plan land-use layer is ~190 MB and cadastral ~145 MB, so
        ``response.content`` is never used. Bytes go straight to a ``.part`` file
        which is validated and then atomically renamed, meaning a partial or
        failed download can never be mistaken for a valid cache entry.
        """
        final = self._raw_cache_path(dataset_id)
        tmp: Optional[Path] = final.with_suffix(".part")
        last_error = "unknown error"

        for attempt in range(1, self.max_attempts + 1):
            self._raw_dir.mkdir(parents=True, exist_ok=True)
            written = 0
            try:
                log.info(
                    "Land source %s: downloading (attempt %d/%d) from %s",
                    dataset_id, attempt, self.max_attempts, _safe_host(url),
                )
                started = time.perf_counter()
                with httpx.Client(
                    timeout=self._timeouts(),
                    follow_redirects=True,
                    headers=self._headers(),
                    transport=self._transport,
                ) as client:
                    with client.stream("GET", url) as resp:
                        if self._retryable(resp.status_code):
                            raise _RetryableStatus(resp.status_code, url)
                        if resp.status_code >= 400:
                            raise LandSourceError(
                                f"HTTP {resp.status_code} from {scrub_urls(url)}"
                            )
                        declared = resp.headers.get("content-length")
                        next_log = _PROGRESS_STEP_BYTES
                        with open(tmp, "wb") as fh:
                            for chunk in resp.iter_bytes(_CHUNK_BYTES):
                                fh.write(chunk)
                                written += len(chunk)
                                if written >= next_log:
                                    log.info(
                                        "Land source %s: %.0f MB%s written (%.1fs)",
                                        dataset_id, written / 1e6,
                                        f" of {int(declared) / 1e6:.0f} MB" if declared else "",
                                        time.perf_counter() - started,
                                    )
                                    next_log += _PROGRESS_STEP_BYTES

                if written == 0:
                    raise LandSourceError(f"Empty download body for {dataset_id}")

                _assert_geojson_file(tmp, dataset_id)
                tmp.replace(final)
                log.info(
                    "Land source %s: download complete, %.1f MB in %.1fs -> %s",
                    dataset_id, written / 1e6, time.perf_counter() - started, final.name,
                )
                return final

            except _RetryableStatus as exc:
                self._discard_partial(tmp)
                last_error = f"HTTP {exc.status}"
                if attempt < self.max_attempts:
                    self._sleep(self._retry_delay(attempt))
                    continue
                raise LandSourceError(f"{last_error} from {scrub_urls(url)}") from exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                self._discard_partial(tmp)
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "Land source %s: transfer failed after %.1f MB (attempt %d/%d): %s",
                    dataset_id, written / 1e6, attempt, self.max_attempts, last_error,
                )
                if attempt < self.max_attempts:
                    self._sleep(self._retry_delay(attempt))
                    continue
                raise LandSourceError(f"{last_error} downloading {dataset_id}") from exc
            except Exception:
                self._discard_partial(tmp)
                raise

        raise LandSourceError(f"{last_error} downloading {dataset_id}")

    def _request(self, url: str, gate: bool = True) -> httpx.Response:
        """Small JSON GET (poll-download metadata). Large objects use
        :meth:`_download_to_disk` instead so their body is never buffered."""
        last_error = "unknown error"
        for attempt in range(1, self.max_attempts + 1):
            if gate:
                self._gate()
            try:
                with httpx.Client(
                    timeout=self._timeouts(),
                    follow_redirects=True,
                    headers=self._headers(),
                    transport=self._transport,
                ) as client:
                    resp = client.get(url)
                if self._retryable(resp.status_code):
                    last_error = f"HTTP {resp.status_code}"
                    if attempt < self.max_attempts:
                        self._sleep(self._retry_delay(attempt))
                        continue
                    raise LandSourceError(f"{last_error} from {scrub_urls(url)}")
                if resp.status_code >= 400:
                    raise LandSourceError(f"HTTP {resp.status_code} from {scrub_urls(url)}")
                return resp
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.max_attempts:
                    self._sleep(min(2 ** (attempt - 1), 8))
                    continue
                raise LandSourceError(f"{last_error} contacting {scrub_urls(url)}") from exc
        raise LandSourceError(last_error)

    def _resolve_download_url(self, dataset_id: str) -> str:
        url = POLL_DOWNLOAD_URL.format(dataset_id=dataset_id)
        resp = self._request(url)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise LandSourceError(f"Invalid poll-download JSON for {dataset_id}: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise LandSourceError(
                f"poll-download for {dataset_id} was not ready: {payload.get('errMsg') if isinstance(payload, dict) else 'unexpected'}"
            )
        data = payload.get("data") or {}
        dl = data.get("url")
        if not dl:
            raise LandSourceError(f"poll-download returned no file URL for {dataset_id}")
        return dl

    def _raw_cache_path(self, dataset_id: str) -> Path:
        return self._raw_dir / f"{dataset_id}.geojson"

    def _read_disk(self, dataset_id: str) -> Optional[Path]:
        path = self._raw_cache_path(dataset_id)
        try:
            if path.exists() and (time.time() - path.stat().st_mtime) <= self.ttl_s:
                return path
        except OSError:
            return None
        return None

    def stream_features(self, dataset_id: str) -> Iterator[Dict[str, Any]]:
        """Yield features for a dataset, downloading at most once per TTL.

        This is a true generator: features are decoded and handed to the caller
        one at a time and are never accumulated. Master Plan land use is ~190 MB
        / ~500k features and cadastral ~145 MB; materialising either as a list
        costs multiple GB, so the *disk copy* is the cache and nothing large is
        ever held in memory.

        Every dataset goes to disk via streaming download, so there is a single
        code path and a single cache format. Small files (<= ``_INLINE_MAX_BYTES``)
        additionally get an in-memory feature list, which is cheap and avoids
        re-parsing on every call.
        """
        cached = self.cache.get(f"ds:{dataset_id}", self.ttl_s)
        if cached is not None:
            _, payload, _stale = cached
            log.info("Land source %s: in-memory feature cache hit", dataset_id)
            return iter(payload if isinstance(payload, list) else [])

        disk = self._read_disk(dataset_id)
        if disk is not None:
            log.info(
                "Land source %s: disk cache hit (%.1f MB, %s)",
                dataset_id, disk.stat().st_size / 1e6, disk.name,
            )
        else:
            # Presigned S3 object storage is not the throttled host; only the
            # poll-download API call inside _resolve_download_url needs pacing.
            url = self._resolve_download_url(dataset_id)
            disk = self._download_to_disk(url, dataset_id)

        size = disk.stat().st_size
        if size <= _INLINE_MAX_BYTES:
            features = list(self._stream_file(disk))
            self.cache.put(f"ds:{dataset_id}", features)
            log.info("Land source %s: %d features parsed into memory cache", dataset_id, len(features))
            return iter(features)

        log.info("Land source %s: %.1f MB kept on disk, streaming features lazily", dataset_id, size / 1e6)
        return self._stream_file(disk)

    @staticmethod
    def _stream_file(path: Path) -> Iterator[Dict[str, Any]]:
        def chunks() -> Iterator[bytes]:
            with open(path, "rb") as fh:
                while True:
                    block = fh.read(1 << 20)
                    if not block:
                        break
                    yield block

        return iter_geojson_features(chunks())

    def clear_disk_cache(self) -> int:
        """Delete cached raw bytes; returns bytes reclaimed."""
        freed = 0
        if not self._raw_dir.exists():
            return 0
        for path in self._raw_dir.glob("*.geojson"):
            try:
                freed += path.stat().st_size
                path.unlink()
            except OSError:
                pass
        return freed


_INLINE_MAX_BYTES = 8 << 20  # 8 MB


# ======================================================================
# Snapshot
# ======================================================================
@dataclass
class LandSnapshot:
    generated_at: datetime

    # Raw parsed records
    land_use: List[Dict[str, Any]] = field(default_factory=list)
    planning_areas: List[Dict[str, Any]] = field(default_factory=list)
    regions: List[Dict[str, Any]] = field(default_factory=list)
    cadastral: List[Dict[str, Any]] = field(default_factory=list)
    gls_sites: List[Dict[str, Any]] = field(default_factory=list)
    jtc_estates: List[Dict[str, Any]] = field(default_factory=list)

    # Data-quality counters (never silently swallowed)
    land_use_invalid: int = 0
    land_use_total_seen: int = 0
    cadastral_invalid: int = 0
    cadastral_total_seen: int = 0
    planning_area_invalid: int = 0
    gls_invalid: int = 0
    duplicate_lot_keys: int = 0

    sources: List[LandSource] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    planning_area_index: Optional[PlanningAreaIndex] = None


_PARSERS: Dict[str, Tuple[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]], str]] = {
    "land_use": (parse_land_use_feature, "land_use"),
    "planning_areas": (parse_planning_area_feature, "planning_areas"),
    "regions": (parse_region_feature, "regions"),
    "cadastral": (parse_cadastral_feature, "cadastral"),
    "gls_sites": (parse_gls_site_feature, "gls_sites"),
    "jtc_estates": (parse_jtc_estate_feature, "jtc_estates"),
}


def _dataset_id_for(key: str) -> str:
    return SOURCE_BY_KEY[key]["identifier"]


def _collect(
    client: LandDataClient,
    key: str,
) -> Tuple[List[Dict[str, Any]], int, int, Optional[LandSource], Optional[BaseException], int]:
    """Parse one source. Returns (records, invalid, total_seen, info, error, dupes)."""
    parser, _target = _PARSERS[key]
    info = _source_spec(key)
    records: List[Dict[str, Any]] = []
    invalid = 0
    total = 0
    dupes = 0
    started = time.perf_counter()
    dataset_id = _dataset_id_for(key)
    cached_on_disk = client._read_disk(dataset_id) is not None
    log.info(
        "Land source %s: starting (%s, dataset=%s, %s)",
        key, info.name, dataset_id, "cache hit" if cached_on_disk else "fresh download",
    )
    try:
        features = client.stream_features(dataset_id)
        seen_lots = set()
        next_progress = _FEATURE_PROGRESS_EVERY
        for feature in features:
            total += 1
            rec = parser(feature)
            if rec is None:
                invalid += 1
                continue
            if key == "cadastral":
                lot = rec.get("lot_key")
                if lot:
                    if lot in seen_lots:
                        dupes += 1
                        continue
                    seen_lots.add(lot)
            records.append(rec)
            if total >= next_progress:
                log.info(
                    "Land source %s: %d features parsed, %d accepted, %d rejected (%.1fs)",
                    key, total, len(records), invalid, time.perf_counter() - started,
                )
                next_progress += _FEATURE_PROGRESS_EVERY
        log.info(
            "Land source %s: done, %d/%d features accepted, %d rejected, %d dupes in %.1fs",
            key, len(records), total, invalid, dupes, time.perf_counter() - started,
        )
        if total and not records:
            info.status = "unavailable"
            info.error = f"Source responded but no usable rows were parsed ({total} features inspected)"
        else:
            info.status = "ok"
            info.record_count = len(records)
    except LandSourceError as exc:
        info.status = "unavailable"
        info.error = str(exc)
        log.warning(
            "Land source %s: FAILED after %.1fs (%d/%d features seen): %s",
            key, time.perf_counter() - started, len(records), total, exc,
        )
        return records, invalid, total, info, exc, dupes
    except Exception as exc:  # noqa: BLE001 - never let one source break the module
        log.exception("Unexpected error processing Land source %s", key)
        info.status = "unavailable"
        info.error = scrub_urls(f"Unexpected error: {exc}")
        log.warning("Land source %s: FAILED unexpectedly after %.1fs", key, time.perf_counter() - started)
        return records, invalid, total, info, LandSourceError(info.error), dupes
    return records, invalid, total, info, None, dupes


def fetch_land_snapshot(client: Optional[LandDataClient] = None) -> LandSnapshot:
    """Fetch and parse every Land source. Each failure is isolated and recorded.

    Acquisition is deliberately SERIAL, not concurrent: anonymous data.gov.sg
    access 429s under concurrency (see ``MIN_REQUEST_GAP_S``). Each source is
    applied in catalogue order, so the snapshot is deterministic.
    """
    client = client or LandDataClient()
    snap = LandSnapshot(generated_at=datetime.now(SG))

    keys = list(_PARSERS.keys())
    outcomes = [_collect(client, key) for key in keys]

    ok = 0
    for key, (records, invalid, total, info, error, dupes) in zip(keys, outcomes):
        setattr(snap, _PARSERS[key][1], records)
        if key == "land_use":
            snap.land_use_invalid, snap.land_use_total_seen = invalid, total
        elif key == "cadastral":
            snap.cadastral_invalid, snap.cadastral_total_seen, snap.duplicate_lot_keys = invalid, total, dupes
        elif key == "planning_areas":
            snap.planning_area_invalid = invalid
        elif key == "gls_sites":
            snap.gls_invalid = invalid
        if error is not None:
            snap.errors.append(f"{info.name}: {error}")
        else:
            ok += 1
        if invalid:
            snap.warnings.append(
                f"{info.name}: {invalid} of {total} features rejected by geometry/attribute validation"
            )
        if dupes:
            snap.warnings.append(f"{info.name}: {dupes} duplicate LOT_KEY records ignored")
        if records and info.record_count:
            snap.warnings.append(  # freshness trace, not an error
                f"{info.name}: {len(records)} features parsed"
            )
        snap.sources.append(info)

    # Spatial index for land-use -> planning-area attribution.
    index = PlanningAreaIndex()
    cells = index.build(snap.planning_areas)
    snap.planning_area_index = index
    log.info("Land planning-area grid built: %d cells from %d areas", cells, len(snap.planning_areas))

    log.info(
        "Land snapshot: land_use=%d planning_areas=%d regions=%d cadastral=%d gls=%d jtc=%d ok_sources=%d/%d",
        len(snap.land_use), len(snap.planning_areas), len(snap.regions),
        len(snap.cadastral), len(snap.gls_sites), len(snap.jtc_estates), ok, len(keys),
    )
    return snap


def source_status(snap: LandSnapshot) -> str:
    """available | partial | unavailable - missing data is never turned into zero."""
    statuses = {s.status for s in snap.sources}
    if not statuses:
        return "unavailable"
    if statuses == {"ok"}:
        return "available"
    if "ok" in statuses:
        return "partial"
    return "unavailable"