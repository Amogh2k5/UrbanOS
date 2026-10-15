"""Acquisition, streaming download, caching, failure and timeout behaviour.

Every test here is fully mocked with httpx.MockTransport - no real network.
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import httpx
import pytest

from backend.app.planning.land import sources as src
from backend.app.planning.land.sources import (
    DEFAULT_RAW_TTL_S, LAND_USE_ID, LandDataClient, LandSourceError, PlanningAreaIndex,
    SourceCache, _assert_geojson_file, _safe_host, fetch_land_snapshot, iter_geojson_features,
    parse_cadastral_feature, parse_gls_site_feature, parse_jtc_estate_feature,
    parse_land_use_feature, parse_planning_area_feature, parse_region_feature,
    ring_area_sqm, ring_outermost, scrub_urls,
)
from land_fixtures import (
    cadastral_doc, docs_by_key, gls_doc, jtc_doc, land_use_doc, land_use_feature,
    planning_area_doc, poll_download_response, region_doc,
)

DOCS = docs_by_key()


# --------------------------------------------------------------- helpers
def make_client(handler, tmp_path=None, **kw):
    """Build a client that NEVER touches the real on-disk raw cache.

    Without an explicit tmp_path the client gets a throwaway directory, so a
    test can never silently read the ~340 MB of real datasets that a live run
    leaves behind in the module's data/raw folder.
    """
    if tmp_path is None:
        tmp_path = Path(tempfile.mkdtemp(prefix="land-test-cache-"))
    kw.setdefault("min_gap_s", 0.0)  # no pacing in tests
    return LandDataClient(
        api_key=kw.pop("api_key", None),
        transport=httpx.MockTransport(handler),
        cache=kw.pop("cache", SourceCache()),
        sleep=kw.pop("sleep", lambda s: None),
        raw_cache_dir=kw.pop("raw_cache_dir", tmp_path),
        **kw,
    )


def all_sources_handler(fail_keys=(), status_overrides=None, body_overrides=None):
    """Serve poll-download + S3 for every dataset, with hooks to break things."""
    status_overrides = status_overrides or {}
    body_overrides = body_overrides or {}
    ids = {k: src._dataset_id_for(k) for k in DOCS}

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        for key, ds in ids.items():
            if ds in url and "poll-download" in url:
                if key in fail_keys:
                    return httpx.Response(status_overrides.get(key, 500))
                return httpx.Response(201, content=poll_download_response(DOCS[key], ds))
        for key, ds in ids.items():
            if ds in url:
                if key in fail_keys:
                    return httpx.Response(status_overrides.get(key, 500))
                return httpx.Response(200, content=body_overrides.get(key, DOCS[key]))
        return httpx.Response(404)

    return handler


# =================================================== incremental GeoJSON parser
@pytest.mark.parametrize("size", [1, 7, 13, 64, 997, 4096, 100_000])
def test_streaming_parser_survives_chunk_boundaries(size):
    """A feature split across chunks must not be dropped or duplicated, and must
    not spin (the regression that hung the live run)."""
    raw = land_use_doc()
    chunks = (raw[i:i + size] for i in range(0, len(raw), size))
    got = list(iter_geojson_features(chunks))
    assert len(got) == 3
    assert [f["properties"]["LU_DESC"] for f in got] == ["RESIDENTIAL", "COMMERCIAL", "PARK"]


def test_streaming_parser_terminates_on_truncated_input():
    raw = land_use_doc()
    out = list(iter_geojson_features([raw[: len(raw) // 2]]))
    assert len(out) < 3  # terminates, yields only complete features


@pytest.mark.parametrize("payload", [b"", b"{}", b'{"type":"FeatureCollection"}', b'{"features":[]}'])
def test_streaming_parser_handles_degenerate_documents(payload):
    assert isinstance(list(iter_geojson_features([payload])), list)


def test_streaming_parser_does_not_hang_on_partial_feature():
    """Guards the exact infinite loop: incomplete value at the buffer tail."""
    raw = land_use_doc()
    # Feed everything except the final bytes so the last feature is incomplete.
    chunks = (raw[: len(raw) - 5], b"")
    start = time.time()
    out = list(iter_geojson_features(chunks))
    assert time.time() - start < 5
    assert len(out) == 2


# ======================================================= streaming to disk
def test_large_download_streams_to_disk_without_buffering(tmp_path):
    """A dataset over the inline threshold must land on disk and stream back."""
    body = cadastral_doc(n=40)
    body = body.replace(b'"features":[', b'"features":[') + b" " * (9 << 20) + b""
    client = make_client(all_sources_handler(body_overrides={"cadastral": body}), tmp_path)
    feats = list(client.stream_features(src.CADASTRAL_ID))
    assert len(feats) == 40
    cached = client._read_disk(src.CADASTRAL_ID)
    assert cached is not None and cached.exists()
    assert cached.stat().st_size > (8 << 20)
    # Nothing large may linger in the in-memory feature cache.
    assert client.cache.get(f"ds:{src.CADASTRAL_ID}", 9999) is None


def test_small_download_is_cached_in_memory(tmp_path):
    client = make_client(all_sources_handler(), tmp_path)
    list(client.stream_features(src.PLANNING_AREA_ID))
    assert client.cache.get(f"ds:{src.PLANNING_AREA_ID}", 9999) is not None


def test_disk_cache_is_reused_without_network(tmp_path):
    """Second call must not touch HTTP at all."""
    calls = {"n": 0}

    def counting(req):
        calls["n"] += 1
        return all_sources_handler()(req)

    client = make_client(counting, tmp_path)
    list(client.stream_features(src.REGION_ID))
    first = calls["n"]
    assert first > 0
    client.cache.clear()  # drop memory cache, keep disk
    list(client.stream_features(src.REGION_ID))
    assert calls["n"] == first, "second read re-downloaded instead of using disk cache"


def test_expired_disk_cache_is_refetched(tmp_path):
    client = make_client(all_sources_handler(), tmp_path, ttl_s=3600)
    list(client.stream_features(src.REGION_ID))
    assert client._read_disk(src.REGION_ID) is not None
    expired = make_client(all_sources_handler(), tmp_path, ttl_s=-1)
    assert expired._read_disk(src.REGION_ID) is None


# ================================================== failed / interrupted download
def test_failed_download_retries_then_raises(tmp_path):
    sleeps = []
    client = make_client(
        all_sources_handler(fail_keys=("land_use",)), tmp_path,
        sleep=sleeps.append, max_attempts=3,
    )
    with pytest.raises(LandSourceError) as exc:
        list(client.stream_features(LAND_USE_ID))
    assert "500" in str(exc.value)
    assert len(sleeps) == 2  # two backoffs between three attempts


def test_429_is_retried_and_can_succeed(tmp_path):
    state = {"n": 0}

    def handler(req):
        if "poll-download" in str(req.url) and LAND_USE_ID in str(req.url):
            state["n"] += 1
            if state["n"] < 3:
                return httpx.Response(429)
            return httpx.Response(201, content=poll_download_response(land_use_doc(), LAND_USE_ID))
        return all_sources_handler()(req)

    sleeps = []
    client = make_client(handler, tmp_path, sleep=sleeps.append, max_attempts=4)
    feats = list(client.stream_features(LAND_USE_ID))
    assert len(feats) == 3
    assert state["n"] == 3
    assert sleeps and sleeps[0] == 5.0


def test_4xx_is_not_retried(tmp_path):
    calls = {"n": 0}

    def handler(req):
        if "poll-download" in str(req.url) and LAND_USE_ID in str(req.url):
            calls["n"] += 1
            return httpx.Response(404)
        return all_sources_handler()(req)

    client = make_client(handler, tmp_path, max_attempts=4)
    with pytest.raises(LandSourceError):
        list(client.stream_features(LAND_USE_ID))
    assert calls["n"] == 1


def test_partial_file_is_removed_after_failure(tmp_path):
    client = make_client(
        all_sources_handler(fail_keys=("cadastral",)), tmp_path, max_attempts=1
    )
    with pytest.raises(LandSourceError):
        list(client.stream_features(src.CADASTRAL_ID))
    leftovers = list(tmp_path.glob("*.part"))
    assert leftovers == [], f"partial download left behind: {leftovers}"
    assert list(tmp_path.glob("*.geojson")) == []


def test_interrupted_transfer_leaves_no_cache_entry(tmp_path):
    """Connection dies mid-body: no cache file, no .part, clear error."""
    def handler(req):
        if "poll-download" in str(req.url):
            return httpx.Response(201, content=poll_download_response(cadastral_doc()))
        if "files.example" in str(req.url):
            raise httpx.ReadError("peer closed", request=req)
        return all_sources_handler()(req)

    client = make_client(handler, tmp_path, max_attempts=2)
    with pytest.raises(LandSourceError) as exc:
        list(client.stream_features(src.CADASTRAL_ID))
    assert "ReadError" in str(exc.value) or "peer closed" in str(exc.value)
    assert list(tmp_path.glob("*.part")) == []
    assert client._read_disk(src.CADASTRAL_ID) is None


def test_html_error_page_is_rejected(tmp_path):
    html = b"<!DOCTYPE html><html><body>AccessDenied</body></html>"
    client = make_client(all_sources_handler(body_overrides={"regions": html}), tmp_path, max_attempts=1)
    with pytest.raises(LandSourceError) as exc:
        list(client.stream_features(src.REGION_ID))
    assert "not a GeoJSON object" in str(exc.value)
    assert list(tmp_path.glob("*.part")) == []


def test_empty_body_is_rejected(tmp_path):
    client = make_client(all_sources_handler(body_overrides={"regions": b""}), tmp_path, max_attempts=1)
    with pytest.raises(LandSourceError) as exc:
        list(client.stream_features(src.REGION_ID))
    assert "empty" in str(exc.value).lower()


def test_poll_download_not_ready_raises(tmp_path):
    def handler(req):
        return httpx.Response(200, json={"code": 1, "errMsg": "pending"})

    client = make_client(handler, tmp_path)
    with pytest.raises(LandSourceError, match="not ready"):
        list(client.stream_features(src.REGION_ID))


# ================================================================= timeouts
def test_timeouts_are_bounded_per_phase(tmp_path):
    client = make_client(lambda r: httpx.Response(200, content=region_doc()), tmp_path, timeout_s=60.0)
    t = client._timeouts()
    assert t.connect == 15.0 and t.pool == 15.0
    assert t.read == 60.0 and t.write == 60.0


def test_read_timeout_is_retried_then_surfaced(tmp_path):
    sleeps = []

    def handler(req):
        if "files.example" in str(req.url):
            raise httpx.ReadTimeout("slow", request=req)
        return all_sources_handler()(req)

    client = make_client(handler, tmp_path, sleep=sleeps.append, max_attempts=3)
    with pytest.raises(LandSourceError) as exc:
        list(client.stream_features(src.REGION_ID))
    assert "ReadTimeout" in str(exc.value)
    assert len(sleeps) == 2
    assert list(tmp_path.glob("*.part")) == []


def test_connect_timeout_is_retried(tmp_path):
    def handler(req):
        if "files.example" in str(req.url):
            raise httpx.ConnectTimeout("no route", request=req)
        return all_sources_handler()(req)

    client = make_client(handler, tmp_path, max_attempts=2)
    with pytest.raises(LandSourceError, match="ConnectTimeout"):
        list(client.stream_features(src.REGION_ID))


def test_retry_backoff_is_bounded():
    client = LandDataClient(min_gap_s=0.0)
    delays = [client._retry_delay(i) for i in range(1, 8)]
    assert delays[0] == 5.0 and delays[1] == 10.0
    assert max(delays) <= 30.0


# ================================================== rate-limit gate (429 guard)
def test_minimum_gap_is_enforced_between_requests():
    slept = []
    client = LandDataClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
                            sleep=slept.append, min_gap_s=5.0)
    client._gate()
    client._gate()
    assert slept, "second gated call did not wait"
    assert any(s > 0 for s in slept)


def test_gate_disabled_when_gap_zero():
    slept = []
    client = LandDataClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)), sleep=slept.append, min_gap_s=0.0)
    client._gate()
    client._gate()
    assert slept == []


# ============================================================ partial failure
def test_snapshot_degrades_when_one_source_fails(tmp_path):
    client = make_client(all_sources_handler(fail_keys=("jtc_estates",)), tmp_path)
    snap = fetch_land_snapshot(client)
    assert snap.jtc_estates == []
    assert len(snap.land_use) == 3 and len(snap.planning_areas) == 2
    assert len(snap.cadastral) == 3 and len(snap.gls_sites) == 2
    assert any("JTC" in e for e in snap.errors)
    assert src.source_status(snap) == "partial"


def test_snapshot_survives_every_source_failing(tmp_path):
    client = make_client(lambda r: httpx.Response(503), tmp_path, max_attempts=1)
    snap = fetch_land_snapshot(client)
    assert not snap.land_use and not snap.cadastral
    assert len(snap.errors) == 6
    assert src.source_status(snap) == "unavailable"


def test_snapshot_ordering_is_deterministic(tmp_path):
    a = fetch_land_snapshot(make_client(all_sources_handler(), tmp_path))
    b = fetch_land_snapshot(make_client(all_sources_handler(), tmp_path))
    assert [s.key for s in a.sources] == [s.key for s in b.sources]
    assert len(a.land_use) == len(b.land_use)


# ================================================== validation / CRS guarding
def test_geojson_validation_rejects_non_object(tmp_path):
    p = tmp_path / "x.geojson"
    p.write_bytes(b"   \n [1,2,3]")
    with pytest.raises(LandSourceError, match="not a GeoJSON object"):
        _assert_geojson_file(p, "d_x")


def test_geojson_validation_requires_features_key(tmp_path):
    p = tmp_path / "y.geojson"
    p.write_bytes(b'{"type":"FeatureCollection"}')
    with pytest.raises(LandSourceError, match="no 'features' member"):
        _assert_geojson_file(p, "d_y")


def test_geojson_validation_accepts_real_head(tmp_path):
    p = tmp_path / "z.geojson"
    p.write_bytes(land_use_doc())
    _assert_geojson_file(p, "d_z")


def test_scrub_urls_removes_presigned_credentials():
    signed = "https://s3.example.com/f.xlsx?X-Amz-Security-Token=TOPSECRET&X-Amz-Signature=abc"
    assert "TOPSECRET" not in scrub_urls(signed)
    assert "<redacted>" in scrub_urls(signed)


def test_safe_host_never_leaks_query():
    signed = "https://s3.example.com/blobs/f.geojson?X-Amz-Security-Token=TOPSECRET"
    shown = _safe_host(signed)
    assert "TOPSECRET" not in shown
    assert shown == "https://s3.example.com/blobs/f.geojson"


def test_source_error_scrubs_query():
    err = LandSourceError("failed https://s3.example.com/f?X-Amz-Security-Token=SECRET")
    assert "SECRET" not in str(err)


# ============================================================ parsers
def test_parse_land_use_uses_source_area_and_centroid():
    rec = parse_land_use_feature(land_use_feature("RESIDENTIAL", "2.8", 1234.5))
    assert rec["lu_desc"] == "RESIDENTIAL"
    assert rec["area_sqm"] == 1234.5  # source SHAPE.AREA wins, not recomputed
    assert rec["gpr"] == "2.8"
    assert rec["updated"] == "2025-12-29"


def test_parse_land_use_rejects_projected_or_sentinel_coordinates():
    for bad in [{"coordinates": [[[0.0, 0.0], [0.001, 0.0], [0.001, 0.001], [0.0, 0.001], [0.0, 0.0]]]},
                {"coordinates": [[[24084.0, 34974.0], [24085.0, 34974.0], [24085.0, 34975.0], [24084.0, 34974.0]]]}]:
        feat = land_use_feature()
        feat["geometry"] = {"type": "Polygon", "coordinates": bad["coordinates"]}
        assert parse_land_use_feature(feat) is None


def test_parse_land_use_rejects_empty_polygon():
    feat = land_use_feature()
    feat["geometry"] = {"type": "Polygon", "coordinates": [[[103.8, 1.3], [103.8, 1.3]]]}
    assert parse_land_use_feature(feat) is None


def test_parse_land_use_keeps_zone_whose_first_vertex_clips_envelope_edge():
    """Validation moved from ring[0] to the centroid: a zone that merely
    touches an envelope boundary must not be dropped.

    First vertex 103.0 is outside SG_LON=(103.5, 104.2), but the body of the
    zone is over Singapore and its centroid is 103.52.
    """
    feat = land_use_feature("RESIDENTIAL", "2.8")
    feat["geometry"] = {"type": "Polygon", "coordinates": [[
        [103.0, 1.30], [103.9, 1.30], [103.9, 1.31], [103.8, 1.31], [103.0, 1.30],
    ]]}
    rec = parse_land_use_feature(feat)
    assert rec is not None
    assert 103.5 <= rec["centroid_lon"] <= 104.2


def test_parse_land_use_rejects_offshore_zone_everywhere_outside():
    """The live layer carries one PORT / AIRPORT polygon at ~104.407 E, ~35 km
    east of Changi. Every vertex is outside, so it stays rejected."""
    feat = land_use_feature("PORT / AIRPORT", "EVA")
    feat["geometry"] = {"type": "Polygon", "coordinates": [[
        [104.40503, 1.32984], [104.41033, 1.32984], [104.41033, 1.33128],
        [104.40503, 1.33128], [104.40503, 1.32984],
    ]]}
    assert parse_land_use_feature(feat) is None


def test_parse_land_use_rejects_missing_geometry():
    feat = land_use_feature()
    feat["geometry"] = None
    assert parse_land_use_feature(feat) is None


def test_parse_land_use_missing_area_falls_back_to_geometry():
    feat = land_use_feature("RESIDENTIAL", "2.8")
    feat["properties"]["SHAPE.AREA"] = None
    rec = parse_land_use_feature(feat)
    assert rec["area_sqm"] and rec["area_sqm"] > 0


def test_parse_planning_area_carries_region_and_ring():
    doc = json.loads(planning_area_doc())
    rec = parse_planning_area_feature(doc["features"][0])
    assert rec["name"] == "BUKIT TIMAH" and rec["code"] == "BT"
    assert rec["region"] == "CENTRAL REGION" and rec["region_code"] == "CR"
    assert rec["_outer_ring"] and rec["_bbox"]


def test_parse_region_and_cadastral_and_gls_and_jtc():
    region = parse_region_feature(json.loads(region_doc())["features"][0])
    assert region["name"] == "CENTRAL REGION"

    cad = parse_cadastral_feature(json.loads(cadastral_doc())["features"][0])
    assert cad["lot_key"] == "MK10-00700X" and cad["area_sqm"] == 17682.5973

    gls = parse_gls_site_feature(json.loads(gls_doc())["features"][0])
    assert gls["devt_code"] == "Industrial" and gls["award_year"] == 1995
    assert gls["site_area_sqm"] == 60988.6 and gls["successful_price"] == 136390000

    jtc = parse_jtc_estate_feature(json.loads(jtc_doc())["features"][0])
    assert jtc["estate_name"] == "Jurong Industrial Estate Others"


def test_parse_number_never_yields_zero_for_missing():
    from backend.app.planning.land.sources import _num
    for bad in (None, "", "na", "NA", "-", "abc", float("nan"), float("inf"), True):
        assert _num(bad) is None


# ================================================================= geometry
def test_ring_outermost_handles_polygon_and_multipolygon():
    ring = [[103.8, 1.3], [103.9, 1.3], [103.9, 1.4], [103.8, 1.3]]
    assert ring_outermost({"type": "Polygon", "coordinates": [ring]}) == ring
    assert ring_outermost({"type": "MultiPolygon", "coordinates": [[ring]]}) == ring
    assert ring_outermost({"type": "LineString", "coordinates": []}) is None
    assert ring_outermost(None) is None


def test_ring_area_is_positive_and_plausible():
    ring = [[103.8, 1.3], [103.81, 1.3], [103.81, 1.31], [103.8, 1.31], [103.8, 1.3]]
    area = ring_area_sqm(ring)
    assert area and area > 0
    # ~1.11 km x 1.11 km
    assert 1.0e6 < area < 1.4e6


def test_planning_area_index_resolves_and_rejects_outside():
    idx = PlanningAreaIndex(step_deg=0.0025)
    pa = parse_planning_area_feature(json.loads(planning_area_doc())["features"][0])
    idx.build([pa])
    assert idx.built and idx.cell_count > 0
    assert idx.lookup(103.85, 1.33) == "BT"
    assert idx.lookup(1.0, 103.0) is None


def test_clear_disk_cache_removes_files(tmp_path):
    client = make_client(all_sources_handler(), tmp_path)
    list(client.stream_features(src.REGION_ID))
    assert list(tmp_path.glob("*.geojson"))
    assert client.clear_disk_cache() > 0
    assert not list(tmp_path.glob("*.geojson"))


def test_default_ttl_is_long_for_periodic_sources():
    assert DEFAULT_RAW_TTL_S >= 24 * 3600