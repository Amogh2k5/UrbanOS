"""Acquisition, parsing, validation and failure handling for the Water sources."""
from __future__ import annotations

import io
import zipfile

import httpx
import pytest

from backend.app.infrastructure.water import sources as src
from backend.app.infrastructure.water.sources import (
    SourceCache, WaterDataClient, WaterSourceError, fetch_water_snapshot, normalize_unit,
    parse_newater_annual, parse_number, parse_potable_annual, parse_sensor_geojson,
    parse_water_quality, parse_water_sales_annual, parse_sensor_rows, read_xlsx_rows, scrub_urls, svy21_to_wgs84,
)
from water_fixtures import (
    datastore_payload, newater_records, potable_records, quality_records, sensor_geojson,
    water_sales_records,
)


def make_client(handler, **kw):
    return WaterDataClient(
        api_key=kw.pop("api_key", None), transport=httpx.MockTransport(handler),
        cache=kw.pop("cache", SourceCache()), sleep=lambda s: None, **kw,
    )


# ------------------------------------------------------------------ parsing
def test_parse_number_handles_missing_and_invalid():
    assert parse_number("515.5") == 515.5
    assert parse_number("1,234.5") == 1234.5
    for bad in (None, "", "na", "NA", "-", "abc", float("nan"), float("inf"), True):
        assert parse_number(bad) is None


def test_parse_water_sales_annual_wide_format_with_na():
    sales = parse_water_sales_annual(water_sales_records())
    assert set(sales) == {"potable_total", "domestic", "non_domestic", "newater", "industrial"}
    assert sales["potable_total"][2025] == 515.5
    assert sales["domestic"][2015] == 297.1
    assert sales["newater"][2025] == 153.8
    # 'na' must stay missing, never become 0
    assert sales["industrial"][2025] is None and sales["industrial"][2024] is None
    assert sales["industrial"][2023] == 13.7


def test_parse_water_sales_ignores_unknown_series_and_negative_values():
    recs = [
        {"_id": 1, "DataSeries": "Something Else", "2025": "1"},
        {"_id": 2, "DataSeries": "Domestic Use", "2025": "-5", "2024": "300"},
    ]
    out = parse_water_sales_annual(recs)
    assert "something_else" not in out and list(out) == ["domestic"]
    assert out["domestic"][2025] is None and out["domestic"][2024] == 300.0


def test_parse_potable_long_format_skips_null_rows():
    recs = potable_records() + [{"year": None, "category": None, "sales_of_potable_water": None},
                                {"year": "2013", "category": "Domestic", "sales_of_potable_water": "x"}]
    out = parse_potable_annual(recs)
    assert out["domestic"][2008] == 271.4 and out["non_domestic"][2012] == 206.5
    assert 2013 not in out["domestic"]


def test_parse_newater_annual():
    out = parse_newater_annual(newater_records())
    assert out[2007] == 49.15 and out[2016] == 126.9 and len(out) == 10


def test_parse_quality_uses_latest_year_and_fixes_micro_sign():
    q = parse_water_quality(quality_records())
    assert q["year"] == 2025
    keys = {r["key"] for r in q["rows"]}
    assert keys == {"ecoli", "conductivity", "ph", "tds", "turbidity"}
    assert q["other_count"] == 1  # Gross Alpha
    cond = next(r for r in q["rows"] if r["key"] == "conductivity")
    assert cond["unit"] == "µS/cm" and cond["name"] == "Conductivity"
    assert normalize_unit("æg/L") == "µg/L"


def test_parse_quality_empty():
    assert parse_water_quality([])["year"] is None


def test_parse_sensor_geojson_validates_coordinates_and_names():
    sensors, invalid = parse_sensor_geojson(sensor_geojson())
    assert [s.id for s in sensors][:2] == ["s1", "s2"]
    assert sensors[0].name == "Sensor A" and sensors[0].longitude == 103.8198
    assert sensors[2].name == "From HTML"      # parsed from Description HTML
    assert invalid == 2                         # (0,0) outside Singapore + null geometry


# ------------------------------------------------------------ API acquisition
def test_datastore_pagination_and_api_key_header():
    seen = []

    def handler(req: httpx.Request):
        seen.append((dict(req.url.params), req.headers.get("x-api-key")))
        off = int(req.url.params["offset"])
        recs = [{"year": str(2000 + i)} for i in range(off, min(off + 2, 5))]
        return httpx.Response(200, json=datastore_payload(recs, total=5))

    client = make_client(handler, api_key="k123")
    res = client._fetch_datastore_records("d_x", page_size=2)
    assert len(res) == 5
    assert [p["offset"] for p, _ in seen] == ["0", "2", "4"]
    assert all(k == "k123" for _, k in seen)


def test_no_api_key_header_when_not_configured(monkeypatch):
    monkeypatch.delenv("DATA_GOV_SG_API_KEY", raising=False)
    seen = {}

    def handler(req):
        seen["h"] = req.headers.get("x-api-key")
        return httpx.Response(200, json=datastore_payload([{"a": 1}]))

    make_client(handler).get_records("d_x")
    assert seen["h"] is None


def test_retry_on_429_then_success_honours_retry_after():
    calls, sleeps = {"n": 0}, []

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json=datastore_payload([{"a": 1}]))

    client = WaterDataClient(transport=httpx.MockTransport(handler), cache=SourceCache(), sleep=sleeps.append)
    assert client.get_records("d_x").data == [{"a": 1}]
    assert calls["n"] == 3 and sleeps == [2.0, 2.0]


def test_persistent_500_raises():
    client = make_client(lambda req: httpx.Response(503))
    with pytest.raises(WaterSourceError, match="503"):
        client.get_records("d_x")


def test_timeout_raises_source_error():
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(WaterSourceError, match="ReadTimeout"):
        make_client(handler).get_records("d_x")


def test_invalid_json_and_bad_shapes_raise():
    with pytest.raises(WaterSourceError, match="Invalid JSON"):
        make_client(lambda r: httpx.Response(200, content=b"<html>")).get_records("d_x")
    with pytest.raises(WaterSourceError):
        make_client(lambda r: httpx.Response(200, json={"success": False})).get_records("d_x")
    with pytest.raises(WaterSourceError, match="Unexpected"):
        make_client(lambda r: httpx.Response(200, json={"success": True, "result": {}})).get_records("d_x")


def test_4xx_does_not_retry():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(404)

    with pytest.raises(WaterSourceError, match="404"):
        make_client(handler).get_records("d_x")
    assert calls["n"] == 1


def test_cache_hit_avoids_second_request_and_stale_fallback_on_failure():
    calls = {"n": 0, "fail": False}

    def handler(req):
        calls["n"] += 1
        if calls["fail"]:
            return httpx.Response(500)
        return httpx.Response(200, json=datastore_payload([{"a": 1}]))

    cache = SourceCache()
    client = make_client(handler, cache=cache, ttl_s=3600)
    first = client.get_records("d_x")
    client.get_records("d_x")
    assert calls["n"] == 1 and not first.stale

    # Expire the TTL, make upstream fail -> stale copy with error and ORIGINAL fetched_at
    expired = make_client(handler, cache=cache, ttl_s=-1)
    calls["fail"] = True
    res = expired.get_records("d_x")
    assert res.stale and res.error and res.data == [{"a": 1}]
    assert res.fetched_at == first.fetched_at


# ------------------------------------------------------- sensor layer (XLSX)
def make_xlsx(rows, shared=False):
    """Build a minimal .xlsx in memory (stdlib only) for tests."""
    def col(i):
        return chr(65 + i)

    strings, body = [], []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, v in enumerate(row):
            ref = f"{col(c)}{r}"
            if isinstance(v, (int, float)):
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            elif shared:
                strings.append(str(v))
                cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>')
        body.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{ns}"><sheetData>{"".join(body)}</sheetData></worksheet>')
        if shared:
            z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{ns}">' + "".join(f"<si><t>{t}</t></si>" for t in strings) + "</sst>")
    return buf.getvalue()


SENSOR_ROWS = [
    ["Station Name", "Latitude", "Longitude"],
    ["Alpha Canal", 1.3521, 103.8198],
    ["Beta Drain", 1.2900, 103.8500],
    ["Off Island", 0.0, 0.0],
    ["", "", ""],
    ["Swapped", 103.9, 1.33],
]


# First rows of the REAL PUB file as printed by scripts/inspect_water_sources.py (X/Y are SVY21 metres),
# plus one out-of-range row that must be rejected.
REAL_SENSOR_ROWS = [
    ["Station ID", "Station Name", "X", "Y"],
    ["CWS186", "Eng Neo Ave OD (Vanda Lk u/s culvert)", "24084.322517376098", "34974.364755337803"],
    ["CWS192", "Happy Ave OD (Jln Gembira)", "33422.299119933399", "34953.956110213898"],
    ["CWS193", "Harvey Rd/ Macpherson Rd", "33695.291173488302", "35022.606553196798"],
    ["BAD1", "Corrupt coordinates", "999999", "999999"],
]


def test_svy21_conversion_matches_epsg3414_reference_values():
    # Reference values computed independently with pyproj (EPSG:3414 -> EPSG:4326).
    cases = [
        ((28001.642, 38744.572), (1.36666667, 103.83333333)),                       # SVY21 origin
        ((24084.322517376098, 34974.364755337803), (1.33257000, 103.79813400)),
        ((33422.299119933399, 34953.956110213898), (1.33238520, 103.88204100)),
        ((33695.291173488302, 35022.606553196798), (1.33300600, 103.88449400)),
    ]
    for (e, n), (lat, lon) in cases:
        got_lat, got_lon = svy21_to_wgs84(e, n)
        assert got_lat == pytest.approx(lat, abs=1e-7) and got_lon == pytest.approx(lon, abs=1e-7)


def test_parse_real_pub_sensor_file_format():
    sensors, invalid = parse_sensor_rows(read_xlsx_rows(make_xlsx(REAL_SENSOR_ROWS)))
    assert [x.id for x in sensors] == ["CWS186", "CWS192", "CWS193"]
    assert sensors[1].name == "Happy Ave OD (Jln Gembira)"
    assert sensors[1].latitude == pytest.approx(1.3323852, abs=1e-6) and sensors[1].longitude == pytest.approx(103.882041, abs=1e-6)
    assert invalid == 1


def test_xy_columns_that_are_already_lon_lat_are_not_reprojected():
    sensors, invalid = parse_sensor_rows([["Name", "X", "Y"], ["a", 103.8198, 1.3521]])
    assert sensors[0].longitude == 103.8198 and sensors[0].latitude == 1.3521 and invalid == 0


def test_read_xlsx_rows_inline_and_shared_strings():
    for shared in (False, True):
        rows = read_xlsx_rows(make_xlsx(SENSOR_ROWS, shared=shared))
        assert rows[0] == ["Station Name", "Latitude", "Longitude"]
        assert rows[1][0] == "Alpha Canal" and float(rows[1][1]) == 1.3521


def test_read_xlsx_rejects_garbage():
    with pytest.raises(WaterSourceError, match="Unreadable XLSX"):
        read_xlsx_rows(b"PK-not-really-a-zip")


def test_parse_sensor_rows_lat_lon_columns():
    sensors, invalid = parse_sensor_rows(read_xlsx_rows(make_xlsx(SENSOR_ROWS)))
    assert [s.name for s in sensors] == ["Alpha Canal", "Beta Drain", "Swapped"]
    assert sensors[0].latitude == 1.3521 and sensors[0].longitude == 103.8198
    assert sensors[2].latitude == 1.33 and sensors[2].longitude == 103.9    # swapped columns repaired
    assert invalid == 1                                                       # (0,0) rejected; blank row ignored


def test_parse_sensor_rows_wkt_geometry_column():
    rows = [["ID", "Name", "Geometry"], ["w1", "Wkt Sensor", "POINT (103.8198 1.3521)"], ["w2", "Bad", "POINT (0 0)"]]
    sensors, invalid = parse_sensor_rows(rows)
    assert len(sensors) == 1 and sensors[0].id == "w1" and sensors[0].longitude == 103.8198 and invalid == 1


def test_parse_sensor_rows_unrecognised_columns_fail_loudly_with_real_headers():
    with pytest.raises(WaterSourceError, match="no recognised latitude/longitude.*Foo"):
        parse_sensor_rows([["Name", "Foo", "Bar"], ["a", 28001, 38744]])


def test_poll_download_xlsx_flow():
    xlsx = make_xlsx(SENSOR_ROWS)

    def handler(req: httpx.Request):
        if "poll-download" in req.url.path:
            return httpx.Response(200, json={"code": 0, "data": {"url": "https://files.example/s3/PUBWaterLevelSensors.xlsx?X-Amz-Security-Token=SECRET"}})
        assert req.url.host == "files.example"
        return httpx.Response(200, content=xlsx)

    res = make_client(handler).get_sensor_layer("d_sensors")
    assert res.data["kind"] == "xlsx"
    sensors, _ = src.parse_sensor_layer(res.data)
    assert len(sensors) == 3


def test_poll_download_geojson_flow_still_supported():
    def handler(req: httpx.Request):
        if "poll-download" in req.url.path:
            return httpx.Response(200, json={"code": 0, "data": {"url": "https://files.example/s3/sensors.geojson"}})
        return httpx.Response(200, json=sensor_geojson())

    res = make_client(handler).get_sensor_layer("d_sensors")
    assert res.data["kind"] == "geojson" and len(src.parse_sensor_layer(res.data)[0]) == 3


def test_poll_download_not_ready_raises():
    client = make_client(lambda r: httpx.Response(200, json={"code": 1, "errMsg": "pending"}))
    with pytest.raises(WaterSourceError, match="file URL"):
        client.get_sensor_layer("d_sensors")


def test_download_that_is_neither_xlsx_nor_json_raises():
    def handler(req):
        if "poll-download" in req.url.path:
            return httpx.Response(200, json={"code": 0, "data": {"url": "https://files.example/x"}})
        return httpx.Response(200, content=b"\x87\x00binary")

    with pytest.raises(WaterSourceError, match="neither XLSX nor JSON"):
        make_client(handler).get_sensor_layer("d_sensors")


def test_signed_url_credentials_never_appear_in_errors():
    signed = "https://s3.example.com/f.xlsx?X-Amz-Security-Token=TOPSECRET&X-Amz-Signature=abc"
    assert "TOPSECRET" not in scrub_urls(f"HTTP 500 from {signed}") and "<redacted>" in scrub_urls(signed)

    def handler(req):
        if "poll-download" in req.url.path:
            return httpx.Response(200, json={"code": 0, "data": {"url": signed}})
        return httpx.Response(503)

    with pytest.raises(WaterSourceError) as exc:
        make_client(handler).get_sensor_layer("d_sensors")
    assert "TOPSECRET" not in str(exc.value) and "X-Amz-Signature" not in str(exc.value)


# --------------------------------------------------------------- snapshot
def _full_handler(req: httpx.Request):
    if "poll-download" in req.url.path:
        return httpx.Response(200, json={"code": 0, "data": {"url": "https://files.example/s.geojson"}})
    if req.url.host == "files.example":
        return httpx.Response(200, content=make_xlsx(REAL_SENSOR_ROWS))
    rid = req.url.params["resource_id"]
    mapping = {src.WATER_SALES_ID: water_sales_records(), src.POTABLE_ID: potable_records(),
               src.NEWATER_ID: newater_records(), src.QUALITY_ID: quality_records()}
    return httpx.Response(200, json=datastore_payload(mapping[rid]))


def test_fetch_snapshot_all_sources_ok():
    snap = fetch_water_snapshot(make_client(_full_handler))
    assert not snap.errors
    assert {s.key: s.status for s in snap.sources} == {
        "water_sales_annual": "ok", "potable_annual": "ok", "newater_annual": "ok",
        "drinking_quality": "ok", "drain_sensors": "ok",
    }
    sales_src = next(s for s in snap.sources if s.key == "water_sales_annual")
    assert sales_src.latest_data_period == "2025" and sales_src.last_fetched_at is not None
    assert len(snap.sensors) == 3 and snap.invalid_sensors == 1


def test_fetch_snapshot_isolates_single_source_failure():
    def handler(req):
        if req.url.params.get("resource_id") == src.QUALITY_ID:
            return httpx.Response(500)
        return _full_handler(req)

    snap = fetch_water_snapshot(make_client(handler))
    status = {s.key: s.status for s in snap.sources}
    assert status["drinking_quality"] == "unavailable" and status["water_sales_annual"] == "ok"
    assert any("Drinking water quality" in e for e in snap.errors)


def test_fetch_snapshot_flags_empty_parse_as_unavailable():
    def handler(req):
        if req.url.params.get("resource_id") == src.NEWATER_ID:
            return httpx.Response(200, json=datastore_payload([{"junk": "x"}]))
        return _full_handler(req)

    snap = fetch_water_snapshot(make_client(handler))
    assert next(s for s in snap.sources if s.key == "newater_annual").status == "unavailable"


# ------------------------------------------------------------ concurrency
def test_sources_are_fetched_concurrently_and_in_catalog_order():
    import time

    def slow_handler(req: httpx.Request):
        time.sleep(0.25)               # every upstream request takes 250 ms
        return _full_handler(req)

    t0 = time.perf_counter()
    snap = fetch_water_snapshot(make_client(slow_handler))
    elapsed = time.perf_counter() - t0

    # Sequential would need ~1.5 s (4 x 1 request + sensor layer's 2 requests); concurrent ~0.5 s.
    assert elapsed < 1.1, f"sources were not fetched concurrently ({elapsed:.2f}s)"
    assert [s.key for s in snap.sources] == [
        "water_sales_annual", "potable_annual", "newater_annual", "drinking_quality", "drain_sensors",
    ]
    assert not snap.errors and len(snap.sensors) == 3


def test_one_slow_failure_does_not_block_or_break_other_sources():
    def handler(req: httpx.Request):
        if req.url.params.get("resource_id") == src.POTABLE_ID:
            raise httpx.ConnectTimeout("boom", request=req)
        return _full_handler(req)

    snap = fetch_water_snapshot(make_client(handler))
    status = {s.key: s.status for s in snap.sources}
    assert status["potable_annual"] == "unavailable" and status["water_sales_annual"] == "ok"
    assert any("ConnectTimeout" in e for e in snap.errors)
