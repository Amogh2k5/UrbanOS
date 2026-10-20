"""Acquisition, parsing, validation and failure handling for the Waste sources."""
from __future__ import annotations

import json

import httpx
import pytest

from backend.app.infrastructure.waste import sources as src
from backend.app.infrastructure.waste.sources import (
    SourceCache, WasteDataClient, WasteSourceError, fetch_waste_snapshot, parse_facility_geojson,
    parse_general_waste_collectors, parse_number, parse_waste_statistics, scrub_urls,
)
from waste_fixtures import (
    bins_geojson, collector_records, datastore_payload, disposal_geojson, ewaste_geojson, lighting_geojson,
    mutate, waste_stat_records,
)


def make_client(handler, **kw):
    return WasteDataClient(
        api_key=kw.pop("api_key", None), transport=httpx.MockTransport(handler),
        cache=kw.pop("cache", SourceCache()), sleep=lambda s: None, **kw,
    )


# ------------------------------------------------------------------ numbers
def test_parse_number_handles_missing_and_invalid():
    assert parse_number("7015000") == 7015000.0
    assert parse_number("1,234.5") == 1234.5
    for bad in (None, "", "na", "NA", "-", "abc", float("nan"), float("inf"), True):
        assert parse_number(bad) is None


# ------------------------------------------------------------ statistics table
def test_parse_statistics_blocks_and_values_match_real_response():
    t = parse_waste_statistics(waste_stat_records())
    assert set(t.total) == {"generated", "recycled", "disposed", "rate"}
    assert t.years == [2019, 2020, 2021, 2022, 2023, 2024, 2025]
    assert t.total["generated"][2025] == 7015000 and t.total["recycled"][2025] == 3657000
    assert t.total["disposed"][2025] == 3358000 and t.total["rate"][2025] == 52
    assert len(t.cats["generated"]) == 14 and len(t.cats["rate"]) == 14
    assert t.row_count() == 60


def test_same_category_name_in_each_block_resolves_by_block():
    t = parse_waste_statistics(waste_stat_records())
    # 'Food' appears in all four blocks with very different meanings
    assert t.cats["generated"]["food"][2025] == 790000
    assert t.cats["recycled"]["food"][2025] == 140000
    assert t.cats["disposed"]["food"][2025] == 649000
    assert t.cats["rate"]["food"][2025] == 18


def test_category_labels_and_keys_are_normalised():
    t = parse_waste_statistics(waste_stat_records())
    assert t.labels["plastic"] == "Plastics" and t.labels["construction_demolition"] == "Construction & Demolition"
    assert "ash_and_sludge" in t.cats["generated"] and "textile_leather" in t.cats["generated"]


def test_na_is_missing_never_zero():
    t = parse_waste_statistics(waste_stat_records())
    assert t.cats["rate"]["others"][2022] is None and t.cats["rate"]["others"][2025] is None
    assert t.cats["rate"]["others"][2021] == 8
    assert t.missing_cells == 4 and t.unparseable_cells == 0


def test_rows_are_ordered_by_id_not_by_position():
    recs = list(reversed(waste_stat_records()))
    t = parse_waste_statistics(recs)
    assert t.cats["recycled"]["food"][2025] == 140000 and t.total["generated"][2025] == 7015000


def test_block_membership_does_not_depend_on_indentation():
    recs = waste_stat_records()
    for r in recs:
        r["DataSeries"] = r["DataSeries"].strip()
    t = parse_waste_statistics(recs)
    assert t.cats["disposed"]["plastic"][2025] == 856000


def test_invalid_cells_are_dropped_and_counted():
    recs = mutate(waste_stat_records(), "Food", 0, 2025, "-5")
    recs = mutate(recs, "Food", 1, 2025, "abc")
    recs = mutate(recs, "Food", 3, 2025, 140)                     # a rate above 100%
    t = parse_waste_statistics(recs)
    assert t.cats["generated"]["food"][2025] is None and t.cats["recycled"]["food"][2025] is None
    assert t.cats["rate"]["food"][2025] is None
    assert t.unparseable_cells == 3
    assert t.cats["generated"]["food"][2024] == 784000            # neighbours untouched


def test_duplicate_series_rows_keep_first_and_warn():
    recs = waste_stat_records()
    dup = dict(recs[10]); dup["_id"] = 999; dup["2025"] = "1"       # second 'Food' in the generated block
    # place it inside the generated block by giving it an _id just after the last generated row
    dup["_id"] = 15.5
    t = parse_waste_statistics(recs + [dup])
    assert t.cats["generated"]["food"][2025] == 790000 and t.duplicate_rows == 1
    assert any("Duplicate row" in w for w in t.warnings)


def test_duplicate_block_header_is_ignored():
    recs = waste_stat_records()
    extra = {"_id": 1000, "DataSeries": "Total Generated", "2025": "1"}
    t = parse_waste_statistics(recs + [extra])
    assert t.total["generated"][2025] == 7015000 and t.duplicate_rows == 1


def test_row_before_any_header_and_nameless_rows_are_skipped():
    recs = [{"_id": 0, "DataSeries": "    Orphan", "2025": "5"}, {"_id": 1, "2025": "5"}] + waste_stat_records()
    t = parse_waste_statistics(recs)
    assert "orphan" not in t.cats["generated"] and t.total["generated"][2025] == 7015000
    assert len(t.warnings) == 2


def test_empty_or_unrecognised_table_parses_to_empty():
    t = parse_waste_statistics([{"junk": "x"}])
    assert t.total == {} and t.years == []


# ------------------------------------------------------------ collectors
def test_collectors_reduce_to_name_and_class_only():
    c = parse_general_waste_collectors(collector_records())
    assert c.raw_rows == 8 and len(c.licensees) == 6
    assert c.duplicate_rows_removed == 1                           # case/spacing duplicate merged
    assert c.licensees["800 SUPER WASTE MANAGEMENT PTE LTD"] == frozenset({"A", "B"})
    assert c.licensees["SLUDGE CO PTE LTD"] == frozenset({"C"})
    assert c.licensees["OIL RECYCLERS PTE LTD"] == frozenset({"B.1"})
    assert c.unrecognised == {"Class Z": 1}
    # contact details never reach the parsed structure
    assert "secret" not in json.dumps(sorted(c.licensees)) and "6000000" not in repr(c)


# ------------------------------------------------------------ facility layers
def test_kml_layer_reads_description_table_and_skips_placeholder_names():
    layer = parse_facility_geojson(bins_geojson(), "recycling_bins")
    assert len(layer.facilities) == 3
    assert layer.invalid == 3 and layer.duplicates_removed == 1
    assert layer.by_name == {"Recycling Bins in HDB Estates": 2, "Recycling Bins at Schools": 1}
    assert all(not f.name.startswith("kml_") for f in layer.facilities)
    first = layer.facilities[0]
    assert first.address == "407 FERNVALE ROAD" and first.record_date == "2017-06-02"
    assert first.description == "Recycle & reuse"                   # HTML entity decoded
    assert layer.date_min == "2017-06-02" and layer.date_max == "2019-01-01"


def test_direct_property_layer_ewaste():
    layer = parse_facility_geojson(ewaste_geojson(), "ewaste")
    assert len(layer.facilities) == 2 and layer.invalid == 0
    assert layer.facilities[0].address == "460 ALEXANDRA ROAD"
    assert layer.facilities[0].record_date == "2022-06-02"
    assert layer.date_max == "2022-06-02"


def test_missing_name_falls_back_to_layer_label():
    gj = {"features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [103.8, 1.3]}}]}
    layer = parse_facility_geojson(gj, "lighting_waste")
    assert layer.facilities[0].name == "Lighting-waste collection points"


def test_swapped_or_out_of_range_coordinates_are_invalid_not_guessed():
    gj = {"features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [1.3, 103.8]}}]}
    assert parse_facility_geojson(gj, "ewaste").invalid == 1


# ------------------------------------------------------------ HTTP client
def test_datastore_pagination_collects_all_pages():
    pages = [{"_id": i} for i in range(1, 6)]

    def handler(req):
        off = int(req.url.params["offset"]); lim = int(req.url.params["limit"])
        return httpx.Response(200, json=datastore_payload(pages[off:off + 2], total=5))

    client = make_client(handler)
    # force page size 2 through the private method
    assert len(client._fetch_datastore_records("x", page_size=2)) == 5


def test_retries_429_with_retry_after_then_succeeds():
    calls = {"n": 0}
    sleeps = []

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json=datastore_payload([{"_id": 1}]))

    client = WasteDataClient(transport=httpx.MockTransport(handler), cache=SourceCache(), sleep=sleeps.append)
    assert client.get_records("x").data == [{"_id": 1}]
    assert calls["n"] == 3 and sleeps == [2.0, 2.0]


def test_persistent_5xx_raises_waste_source_error():
    client = make_client(lambda r: httpx.Response(503))
    with pytest.raises(WasteSourceError, match="HTTP 503"):
        client.get_records("x")


def test_http_4xx_is_not_retried():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(404)

    with pytest.raises(WasteSourceError, match="HTTP 404"):
        make_client(handler).get_records("x")
    assert calls["n"] == 1


def test_invalid_json_and_bad_shapes_are_rejected():
    with pytest.raises(WasteSourceError, match="Invalid JSON"):
        make_client(lambda r: httpx.Response(200, content=b"<html>")).get_records("x")
    with pytest.raises(WasteSourceError, match="Unexpected datastore_search shape"):
        make_client(lambda r: httpx.Response(200, json={"success": True, "result": {}})).get_records("x")
    with pytest.raises(WasteSourceError, match="datastore_search failed"):
        make_client(lambda r: httpx.Response(200, json={"success": False})).get_records("x")


def test_timeouts_become_waste_source_error():
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(WasteSourceError, match="ReadTimeout"):
        make_client(handler).get_records("x")


def test_api_key_header_sent_when_configured():
    seen = {}

    def handler(req):
        seen["key"] = req.headers.get("x-api-key")
        return httpx.Response(200, json=datastore_payload([{"_id": 1}]))

    make_client(handler, api_key="abc").get_records("x")
    assert seen["key"] == "abc"


def test_stale_cache_served_when_refresh_fails():
    cache = SourceCache()
    ok = make_client(lambda r: httpx.Response(200, json=datastore_payload([{"_id": 1}])), cache=cache, ttl_s=0)
    ok.get_records("x")
    bad = make_client(lambda r: httpx.Response(500), cache=cache, ttl_s=0)
    res = bad.get_records("x")
    assert res.stale and res.data == [{"_id": 1}] and "HTTP 500" in res.error


def test_fresh_cache_avoids_second_request():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(200, json=datastore_payload([{"_id": 1}]))

    c = make_client(handler)
    c.get_records("x"); c.get_records("x")
    assert calls["n"] == 1


def test_poll_download_flow_parses_geojson_and_caches_only_parsed_layer():
    raw = json.dumps(ewaste_geojson()).encode()
    calls = {"dl": 0}

    def handler(req):
        if "poll-download" in req.url.path:
            return httpx.Response(200, json={"code": 0, "data": {"url": "https://files.example/e.geojson?X-Amz-Signature=SECRET"}})
        calls["dl"] += 1
        return httpx.Response(200, content=raw)

    c = make_client(handler)
    res = c.get_facility_layer(src.EWASTE_ID, "ewaste")
    assert len(res.data.facilities) == 2
    c.get_facility_layer(src.EWASTE_ID, "ewaste")
    assert calls["dl"] == 1
    assert isinstance(c.cache.get_any(f"layer:{src.EWASTE_ID}").data, src.FacilityLayer)


def test_poll_download_without_url_and_non_geojson_fail_cleanly():
    c = make_client(lambda r: httpx.Response(200, json={"code": 1, "errMsg": "nope"}))
    with pytest.raises(WasteSourceError, match="did not return a file URL"):
        c.get_facility_layer(src.BINS_ID, "recycling_bins")

    def handler(req):
        if "poll-download" in req.url.path:
            return httpx.Response(200, json={"code": 0, "data": {"url": "https://files.example/x"}})
        return httpx.Response(200, content=b"not json")

    with pytest.raises(WasteSourceError, match="not valid JSON"):
        make_client(handler).get_facility_layer(src.BINS_ID, "recycling_bins")

    def handler2(req):
        if "poll-download" in req.url.path:
            return httpx.Response(200, json={"code": 0, "data": {"url": "https://files.example/x"}})
        return httpx.Response(200, json={"hello": "world"})

    with pytest.raises(WasteSourceError, match="not a GeoJSON"):
        make_client(handler2).get_facility_layer(src.BINS_ID, "recycling_bins")


def test_invalid_utf8_bytes_in_download_do_not_break_parsing():
    raw = json.dumps(ewaste_geojson()).encode().replace(b"ONE MARINA", b"ONE MAR\xa0INA")

    def handler(req):
        if "poll-download" in req.url.path:
            return httpx.Response(200, json={"code": 0, "data": {"url": "https://files.example/e"}})
        return httpx.Response(200, content=raw)

    assert len(make_client(handler).get_facility_layer(src.EWASTE_ID, "ewaste").data.facilities) == 2


def test_presigned_url_query_is_scrubbed_from_errors():
    assert scrub_urls("HTTP 403 from https://s3.example/f.json?X-Amz-Signature=SECRET&x=1") == "HTTP 403 from https://s3.example/f.json?<redacted>"

    def handler(req):
        if "poll-download" in req.url.path:
            return httpx.Response(200, json={"code": 0, "data": {"url": "https://files.example/f?X-Amz-Signature=SECRET"}})
        return httpx.Response(403)

    with pytest.raises(WasteSourceError) as ei:
        make_client(handler).get_facility_layer(src.BINS_ID, "recycling_bins")
    assert "SECRET" not in str(ei.value)


# ------------------------------------------------------------ snapshot
def _full_handler(req: httpx.Request):
    if "poll-download" in req.url.path:
        ds = req.url.path.split("/datasets/")[1].split("/")[0]
        return httpx.Response(200, json={"code": 0, "data": {"url": f"https://files.example/{ds}"}})
    if req.url.host == "files.example":
        gj = {src.BINS_ID: bins_geojson(), src.EWASTE_ID: ewaste_geojson(), src.LIGHTING_ID: lighting_geojson(),
              src.DISPOSAL_ID: disposal_geojson()}[req.url.path.lstrip("/")]
        return httpx.Response(200, content=json.dumps(gj).encode())
    rid = req.url.params["resource_id"]
    mapping = {src.WASTE_STATS_ID: waste_stat_records(), src.COLLECTORS_ID: collector_records()}
    return httpx.Response(200, json=datastore_payload(mapping[rid]))


def test_fetch_snapshot_all_sources_ok():
    snap = fetch_waste_snapshot(make_client(_full_handler))
    assert not snap.errors
    assert {s.key: s.status for s in snap.sources} == {
        "waste_statistics": "ok", "general_collectors": "ok", "recycling_bins": "ok",
        "ewaste_points": "ok", "lighting_waste": "ok", "disposal_sites": "ok",
    }
    assert [s.key for s in snap.sources][0] == "waste_statistics"          # deterministic catalog order
    stats = next(s for s in snap.sources if s.key == "waste_statistics")
    assert stats.latest_data_period == "2025" and stats.record_count == 60 and stats.last_fetched_at is not None
    assert len(snap.collectors.licensees) == 6
    assert {k: len(v.facilities) for k, v in snap.facilities.items()} == {
        "recycling_bins": 3, "ewaste": 2, "lighting_waste": 2, "disposal_sites": 3}


def test_fetch_snapshot_isolates_single_source_failure():
    def handler(req):
        if req.url.params.get("resource_id") == src.COLLECTORS_ID:
            return httpx.Response(500)
        return _full_handler(req)

    snap = fetch_waste_snapshot(make_client(handler))
    status = {s.key: s.status for s in snap.sources}
    assert status["general_collectors"] == "unavailable" and status["waste_statistics"] == "ok"
    assert snap.collectors is None and snap.table is not None
    assert any("General Waste Collectors" in e for e in snap.errors)


def test_fetch_snapshot_facility_failure_does_not_touch_statistics():
    def handler(req):
        if req.url.host == "files.example" and req.url.path.endswith(src.BINS_ID):
            return httpx.Response(500)
        return _full_handler(req)

    snap = fetch_waste_snapshot(make_client(handler))
    assert snap.facility_status["recycling_bins"] == "unavailable" and "recycling_bins" not in snap.facilities
    assert snap.facility_status["ewaste"] == "ok" and snap.table is not None


def test_fetch_snapshot_flags_empty_parse_as_unavailable():
    def handler(req):
        if req.url.params.get("resource_id") == src.WASTE_STATS_ID:
            return httpx.Response(200, json=datastore_payload([{"junk": "x"}]))
        return _full_handler(req)

    snap = fetch_waste_snapshot(make_client(handler))
    s = next(s for s in snap.sources if s.key == "waste_statistics")
    assert s.status == "unavailable" and snap.table is None
    assert any("no usable rows" in e for e in snap.errors)


def test_fetch_snapshot_everything_down_is_graceful():
    snap = fetch_waste_snapshot(make_client(lambda r: httpx.Response(503)))
    assert snap.table is None and snap.collectors is None and snap.facilities == {}
    assert all(s.status == "unavailable" for s in snap.sources) and len(snap.errors) == 6


def test_fetch_snapshot_marks_stale_cache():
    cache = SourceCache()
    fetch_waste_snapshot(make_client(_full_handler, cache=cache, ttl_s=0, facility_ttl_s=0))
    def flaky(req):
        if req.url.params.get("resource_id") == src.WASTE_STATS_ID:
            return httpx.Response(500)
        return _full_handler(req)
    snap = fetch_waste_snapshot(make_client(flaky, cache=cache, ttl_s=0, facility_ttl_s=0))
    s = next(s for s in snap.sources if s.key == "waste_statistics")
    assert s.status == "stale_cache" and snap.table is not None
    assert any("last cached copy" in w for w in snap.warnings)


# ------------------------------------------------- verbatim samples from the live dataset previews
REAL_LIGHTING = {  # d_6226f69998ed0cb62151af37706508cd, both features, as published (retrieved 12 Oct 2026)
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"Name": "kml_1", "Description": "<center><table><tr><th colspan='2' align='center'><em>Attributes</em></th></tr><tr bgcolor=\"#E3E3F3\"> <th>PHOTOURL</th> <td></td> </tr><tr bgcolor=\"\"> <th>LANDXADDRESSPOINT</th> <td></td> </tr><tr bgcolor=\"#E3E3F3\"> <th>ADDRESSPOSTALCODE</th> <td>455871</td> </tr><tr bgcolor=\"\"> <th>DESCRIPTION</th> <td>Recycle your old lightbulbs and florescent tubes. Opens Mon 11:30am to 7:30pm, Tue to Sun 11:30am to 8pm</td> </tr><tr bgcolor=\"#E3E3F3\"> <th>ADDRESSBUILDINGNAME</th> <td>Three Cubes</td> </tr><tr bgcolor=\"\"> <th>ADDRESSUNITNUMBER</th> <td>#01-06</td> </tr><tr bgcolor=\"#E3E3F3\"> <th>LANDYADDRESSPOINT</th> <td></td> </tr><tr bgcolor=\"\"> <th>ADDRESSBLOCKHOUSENUMBER</th> <td>55</td> </tr><tr bgcolor=\"#E3E3F3\"> <th>HYPERLINK</th> <td></td> </tr><tr bgcolor=\"\"> <th>ADDRESSFLOORNUMBER</th> <td></td> </tr><tr bgcolor=\"#E3E3F3\"> <th>NAME</th> <td>Lightbulb/Lamp Recycling Points</td> </tr><tr bgcolor=\"\"> <th>ACCESSRESTRICTION</th> <td></td> </tr><tr bgcolor=\"#E3E3F3\"> <th>ADDRESSSTREETNAME</th> <td>Siglap Road</td> </tr><tr bgcolor=\"\"> <th>INC_CRC</th> <td>2485B751C8B77474</td> </tr><tr bgcolor=\"#E3E3F3\"> <th>FMEL_UPD_D</th> <td>20190930163217</td> </tr></table></center>"}, "geometry": {"type": "Point", "coordinates": [103.923168090089, 1.3126056503473, 0]}},
        {"type": "Feature", "properties": {"Name": "kml_2", "Description": "<center><table><tr><th colspan='2' align='center'><em>Attributes</em></th></tr><tr bgcolor=\"#E3E3F3\"> <th>PHOTOURL</th> <td></td> </tr><tr bgcolor=\"\"> <th>LANDXADDRESSPOINT</th> <td></td> </tr><tr bgcolor=\"#E3E3F3\"> <th>ADDRESSPOSTALCODE</th> <td>159965</td> </tr><tr bgcolor=\"\"> <th>DESCRIPTION</th> <td>Recycle your old lightbulbs and florescent tubes. Opens 10am to 11pm daily</td> </tr><tr bgcolor=\"#E3E3F3\"> <th>ADDRESSBUILDINGNAME</th> <td>IKEA</td> </tr><tr bgcolor=\"\"> <th>ADDRESSUNITNUMBER</th> <td></td> </tr><tr bgcolor=\"#E3E3F3\"> <th>LANDYADDRESSPOINT</th> <td></td> </tr><tr bgcolor=\"\"> <th>ADDRESSBLOCKHOUSENUMBER</th> <td>317</td> </tr><tr bgcolor=\"#E3E3F3\"> <th>HYPERLINK</th> <td></td> </tr><tr bgcolor=\"\"> <th>ADDRESSFLOORNUMBER</th> <td></td> </tr><tr bgcolor=\"#E3E3F3\"> <th>NAME</th> <td>Lightbulb/Lamp Recycling Points</td> </tr><tr bgcolor=\"\"> <th>ACCESSRESTRICTION</th> <td></td> </tr><tr bgcolor=\"#E3E3F3\"> <th>ADDRESSSTREETNAME</th> <td>Alexandra Road</td> </tr><tr bgcolor=\"\"> <th>INC_CRC</th> <td>21A2DB6EFCA07F14</td> </tr><tr bgcolor=\"#E3E3F3\"> <th>FMEL_UPD_D</th> <td>20190930163217</td> </tr></table></center>"}, "geometry": {"type": "Point", "coordinates": [103.805808773108, 1.28797431732068, 0]}},
    ],
}


def test_real_lighting_layer_parses_exactly():
    layer = parse_facility_geojson(REAL_LIGHTING, "lighting_waste")
    assert len(layer.facilities) == 2 and layer.invalid == 0 and layer.duplicates_removed == 0
    a, b = layer.facilities
    assert a.name == "Lightbulb/Lamp Recycling Points" and b.name == a.name         # not the 'kml_N' placeholder
    assert a.address == "55 Siglap Road" and b.address == "317 Alexandra Road"       # first attribute NOT swallowed by the header row
    assert a.record_date == "2019-09-30" and layer.date_min == layer.date_max == "2019-09-30"
    assert a.description.startswith("Recycle your old lightbulbs") and (a.lon, a.lat) == (103.923168, 1.312606)


def test_real_disposal_and_ewaste_samples_parse_exactly():
    disposal = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [103.7695388919066, 1.206630551619241]},
         "properties": {"OBJECTID": 641, "ADDRESSBLOCKHOUSENUMBER": None, "ADDRESSBUILDINGNAME": None, "ADDRESSPOSTALCODE": "637821",
                        "ADDRESSSTREETNAME": "c/o 98 Tuas South Avenue 3", "DESCRIPTION": "Government operated offshore landfill",
                        "NAME": "Semakau Landfill", "FMEL_UPD_D": "20180201145018"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [103.79486741200466, 1.4622576941099386]},
         "properties": {"OBJECTID": 644, "ADDRESSBLOCKHOUSENUMBER": None, "ADDRESSSTREETNAME": "30 Attap Valley Road",
                        "DESCRIPTION": "Private municipal waste incineration plant", "NAME": "Senoko Waste-to-Energy Plant", "FMEL_UPD_D": "20180201145018"}},
    ]}
    layer = parse_facility_geojson(disposal, "disposal_sites")
    assert [f.name for f in layer.facilities] == ["Semakau Landfill", "Senoko Waste-to-Energy Plant"]
    assert layer.facilities[0].address == "c/o 98 Tuas South Avenue 3" and layer.date_max == "2018-02-01"
    assert layer.facilities[1].description == "Private municipal waste incineration plant"

    ew = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [103.70646088413002, 1.339830152579402]},
         "properties": {"OBJECTID": 19906, "NAME": "KGS E-waste Recycling Programme for Non-regulated E-waste", "ADDRESSBLOCKHOUSENUMBER": None,
                        "ADDRESSBUILDINGNAME": "JURONG POINT\ufffd", "ADDRESSSTREETNAME": "1 JURONG WEST CENTRAL 2, JURONG POINT, BESIDE SKECHERS #01-16H/J",
                        "DESCRIPTION": "Bin collection; E-waste accepted: Non-regulated products only", "ACCESSRESTRICTION": "Public", "FMEL_UPD_D": "20220518163655"}}]}
    f = parse_facility_geojson(ew, "ewaste").facilities[0]
    assert f.address == "1 JURONG WEST CENTRAL 2, JURONG POINT, BESIDE SKECHERS #01-16H/J" and f.record_date == "2022-05-18"


def test_real_recycling_bins_text_with_escaped_slashes_parses():
    """First two features of d_4dde14826642f49eefff48b7832b90db exactly as served (note the `<\\/em>` escapes and z=0)."""
    raw = r'''{ "type": "FeatureCollection", "features": [
{ "type": "Feature", "properties": { "Name": "kml_1", "Description": "<center><table><tr><th colspan='2' align='center'><em>Attributes<\/em><\/th><\/tr><tr bgcolor=\"#E3E3F3\"> <th>ADDRESSBLOCKHOUSENUMBER<\/th> <td>407<\/td> <\/tr><tr bgcolor=\"\"> <th>ADDRESSBUILDINGNAME<\/th> <td><\/td> <\/tr><tr bgcolor=\"#E3E3F3\"> <th>ADDRESSFLOORNUMBER<\/th> <td><\/td> <\/tr><tr bgcolor=\"\"> <th>ADDRESSPOSTALCODE<\/th> <td>790407<\/td> <\/tr><tr bgcolor=\"#E3E3F3\"> <th>ADDRESSSTREETNAME<\/th> <td>FERNVALE ROAD<\/td> <\/tr><tr bgcolor=\"\"> <th>ADDRESSTYPE<\/th> <td>H<\/td> <\/tr><tr bgcolor=\"#E3E3F3\"> <th>DESCRIPTION<\/th> <td>To deposit recyclables such as paper (e.g. carton boxes, newspaper, magazine), plastics (e.g. plastic bottle, container), glass (e.g. beverage glass bottle) and metals (e.g. drink cans, metal containe<\/td> <\/tr><tr bgcolor=\"\"> <th>HYPERLINK<\/th> <td>www.nea.gov.sg\/3R<\/td> <\/tr><tr bgcolor=\"#E3E3F3\"> <th>LANDXADDRESSPOINT<\/th> <td>0<\/td> <\/tr><tr bgcolor=\"\"> <th>LANDYADDRESSPOINT<\/th> <td>0<\/td> <\/tr><tr bgcolor=\"#E3E3F3\"> <th>NAME<\/th> <td>Recycling Bins in HDB Estates<\/td> <\/tr><tr bgcolor=\"\"> <th>PHOTOURL<\/th> <td><\/td> <\/tr><tr bgcolor=\"#E3E3F3\"> <th>INC_CRC<\/th> <td>A86545F66AF3A74E<\/td> <\/tr><tr bgcolor=\"\"> <th>FMEL_UPD_D<\/th> <td>20170602165922<\/td> <\/tr><tr bgcolor=\"#E3E3F3\"> <th>ADDRESSUNITNUMBER<\/th> <td><\/td> <\/tr><\/table><\/center>" }, "geometry": { "type": "Point", "coordinates": [ 103.875052888184996, 1.38854074075156, 0.0 ] } },
{ "type": "Feature", "properties": { "Name": "kml_2", "Description": "<center><table><tr><th colspan='2' align='center'><em>Attributes<\/em><\/th><\/tr><tr bgcolor=\"#E3E3F3\"> <th>ADDRESSBLOCKHOUSENUMBER<\/th> <td>897E<\/td> <\/tr><tr bgcolor=\"\"> <th>ADDRESSBUILDINGNAME<\/th> <td>HDB-HOUGANG<\/td> <\/tr><tr bgcolor=\"#E3E3F3\"> <th>ADDRESSSTREETNAME<\/th> <td>WOODLANDS DRIVE 50<\/td> <\/tr><tr bgcolor=\"\"> <th>NAME<\/th> <td>Recycling Bins in HDB Estates<\/td> <\/tr><tr bgcolor=\"#E3E3F3\"> <th>FMEL_UPD_D<\/th> <td>20170602165922<\/td> <\/tr><\/table><\/center>" }, "geometry": { "type": "Point", "coordinates": [ 103.794707851401, 1.43565919435279, 0.0 ] } }
] }'''
    layer = parse_facility_geojson(json.loads(raw), "recycling_bins")
    assert len(layer.facilities) == 2 and layer.invalid == 0
    a, b = layer.facilities
    assert a.address == "407 FERNVALE ROAD" and b.address == "897E WOODLANDS DRIVE 50"   # building name 'HDB-HOUGANG' not used
    assert a.name == b.name == "Recycling Bins in HDB Estates" and a.record_date == "2017-06-02"
    assert (a.lon, a.lat) == (103.875053, 1.388541)


# ================================================================== rate limiting, disk cache, background loading
import threading
import time as _time
from datetime import datetime, timedelta

from backend.app.infrastructure.waste.sources import LayerDiskCache


def _layer_handler(calls=None, gate=None, fail_files=False):
    """poll-download -> file URL; file host -> GeoJSON. Optional gate blocks file downloads; counts poll calls."""
    def handler(req: httpx.Request):
        if "poll-download" in req.url.path:
            if calls is not None:
                calls.append(req.url.path.split("/datasets/")[1].split("/")[0])
            ds = req.url.path.split("/datasets/")[1].split("/")[0]
            return httpx.Response(200, json={"code": 0, "data": {"url": f"https://files.example/{ds}"}})
        if req.url.host == "files.example":
            if gate is not None:
                gate.wait(5)
            if fail_files:
                return httpx.Response(500)
            gj = {src.BINS_ID: bins_geojson(), src.EWASTE_ID: ewaste_geojson(), src.LIGHTING_ID: lighting_geojson(),
                  src.DISPOSAL_ID: disposal_geojson()}[req.url.path.lstrip("/")]
            return httpx.Response(200, content=json.dumps(gj).encode())
        return _full_handler(req)
    return handler


def _wait_until(pred, timeout=5.0):
    end = _time.time() + timeout
    while _time.time() < end:
        if pred():
            return True
        _time.sleep(0.01)
    return False


def test_poll_download_requests_are_spaced_by_the_throttle():
    sleeps = []
    c = WasteDataClient(transport=httpx.MockTransport(_layer_handler()), cache=SourceCache(), sleep=sleeps.append,
                        poll_min_interval_s=12.5, disk_cache=None)
    c.get_facility_layer(src.EWASTE_ID, "ewaste")
    c.get_facility_layer(src.LIGHTING_ID, "lighting_waste")
    waits = [w for w in sleeps if w > 1]
    assert len(waits) == 1 and 12.0 < waits[0] <= 12.5        # the second layer waited ~one interval


def test_throttle_defaults_depend_on_api_key_and_can_be_disabled():
    assert WasteDataClient(api_key=None, disk_cache=None).poll_min_interval_s == src.POLL_INTERVAL_NO_KEY_S
    assert WasteDataClient(api_key="k", disk_cache=None).poll_min_interval_s == src.POLL_INTERVAL_WITH_KEY_S
    sleeps = []
    c = WasteDataClient(transport=httpx.MockTransport(_layer_handler()), cache=SourceCache(), sleep=sleeps.append,
                        poll_min_interval_s=0, disk_cache=None)
    c.get_facility_layer(src.EWASTE_ID, "ewaste"); c.get_facility_layer(src.LIGHTING_ID, "lighting_waste")
    assert sleeps == []


def test_429_without_retry_after_backs_off_for_a_long_time_and_explains_the_quota():
    sleeps = []
    c = WasteDataClient(api_key=None, transport=httpx.MockTransport(lambda r: httpx.Response(429)), cache=SourceCache(),
                        sleep=sleeps.append, poll_min_interval_s=0, disk_cache=None)
    with pytest.raises(WasteSourceError) as ei:
        c.get_facility_layer(src.BINS_ID, "recycling_bins")
    assert sleeps == [12.0, 24.0]                                # not 1-2 s: that just burns another request
    assert "HTTP 429" in str(ei.value) and "DATA_GOV_SG_API_KEY" in str(ei.value)
    keyed = WasteDataClient(api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(429)), cache=SourceCache(),
                            sleep=lambda s: None, poll_min_interval_s=0, disk_cache=None)
    with pytest.raises(WasteSourceError) as ei2:
        keyed.get_facility_layer(src.BINS_ID, "recycling_bins")
    assert "DATA_GOV_SG_API_KEY" not in str(ei2.value)


# ------------------------------------------------------------------ disk cache
def test_disk_cache_roundtrip_preserves_everything(tmp_path):
    layer = parse_facility_geojson(bins_geojson(), "recycling_bins")
    dc = LayerDiskCache(tmp_path)
    when = datetime.now(src.SG) - timedelta(hours=3)
    dc.save(src.BINS_ID, layer, when)
    got = dc.load(src.BINS_ID)
    assert got is not None
    fetched_at, loaded = got
    assert fetched_at == when and loaded.kind == "recycling_bins"
    assert loaded.facilities == layer.facilities and loaded.invalid == layer.invalid
    assert loaded.duplicates_removed == layer.duplicates_removed and loaded.by_name == layer.by_name
    assert not list(tmp_path.glob("*.tmp"))                        # atomic write left no temp file


def test_disk_cache_misses_are_safe(tmp_path):
    dc = LayerDiskCache(tmp_path)
    assert dc.load("d_nope") is None
    (tmp_path / "d_bad.json").write_text("{not json", encoding="utf-8")
    assert dc.load("d_bad") is None
    (tmp_path / "d_old.json").write_text(json.dumps({"version": 99}), encoding="utf-8")
    assert dc.load("d_old") is None
    blocker = tmp_path / "file"; blocker.write_text("x")
    LayerDiskCache(blocker / "sub").save("d_x", parse_facility_geojson(ewaste_geojson(), "ewaste"), datetime.now(src.SG))  # must not raise


def test_default_disk_cache_can_be_disabled_and_relocated(monkeypatch, tmp_path):
    monkeypatch.setenv("URBANOS_WASTE_DISK_CACHE", "0")
    assert LayerDiskCache.default() is None
    monkeypatch.setenv("URBANOS_WASTE_DISK_CACHE", "1")
    monkeypatch.setenv("URBANOS_WASTE_CACHE_DIR", str(tmp_path / "x"))
    assert LayerDiskCache.default().directory == tmp_path / "x"


def test_fresh_disk_copy_is_used_without_any_network(tmp_path):
    dc = LayerDiskCache(tmp_path)
    dc.save(src.EWASTE_ID, parse_facility_geojson(ewaste_geojson(), "ewaste"), datetime.now(src.SG))

    def no_network(req):
        raise AssertionError("network must not be touched")

    c = WasteDataClient(transport=httpx.MockTransport(no_network), cache=SourceCache(), sleep=lambda s: None, disk_cache=dc)
    res = c.get_facility_layer(src.EWASTE_ID, "ewaste")
    assert len(res.data.facilities) == 2 and not res.stale


def test_stale_disk_copy_is_refreshed_or_served_when_refresh_fails(tmp_path):
    dc = LayerDiskCache(tmp_path)
    old = datetime.now(src.SG) - timedelta(days=3)
    dc.save(src.EWASTE_ID, parse_facility_geojson(ewaste_geojson(), "ewaste"), old)
    # refresh fails -> the old copy is still served, flagged stale with the reason
    bad = WasteDataClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)), cache=SourceCache(),
                          sleep=lambda s: None, poll_min_interval_s=0, disk_cache=dc)
    res = bad.get_facility_layer(src.EWASTE_ID, "ewaste")
    assert res.stale and "HTTP 500" in res.error and len(res.data.facilities) == 2
    # refresh works -> new data, and the file on disk is updated
    good = WasteDataClient(transport=httpx.MockTransport(_layer_handler()), cache=SourceCache(),
                           sleep=lambda s: None, poll_min_interval_s=0, disk_cache=dc)
    res2 = good.get_facility_layer(src.EWASTE_ID, "ewaste")
    assert not res2.stale and dc.load(src.EWASTE_ID)[0] > old


def test_peek_never_touches_the_network_and_reports_staleness(tmp_path):
    def no_network(req):
        raise AssertionError("network must not be touched")
    c = WasteDataClient(transport=httpx.MockTransport(no_network), cache=SourceCache(), disk_cache=LayerDiskCache(tmp_path))
    assert c.peek_facility_layer(src.BINS_ID) is None
    layer = parse_facility_geojson(ewaste_geojson(), "ewaste")
    c.disk_cache.save(src.EWASTE_ID, layer, datetime.now(src.SG) - timedelta(hours=1))
    assert c.peek_facility_layer(src.EWASTE_ID).stale is False
    c.facility_ttl_s = 60
    assert c.peek_facility_layer(src.EWASTE_ID).stale is True


# ------------------------------------------------------------------ non-blocking snapshot + background worker
def test_nonblocking_snapshot_returns_immediately_then_layers_arrive():
    gate = threading.Event()
    cache = SourceCache()
    c = WasteDataClient(transport=httpx.MockTransport(_layer_handler(gate=gate)), cache=cache, sleep=lambda s: None,
                        poll_min_interval_s=0, disk_cache=None)
    t0 = _time.time()
    snap = fetch_waste_snapshot(c, wait_for_layers=False)
    assert _time.time() - t0 < 2                                   # did not wait for the blocked downloads
    status = {s.key: s.status for s in snap.sources}
    assert status["waste_statistics"] == "ok" and status["general_collectors"] == "ok"
    assert {status[k] for k in ("recycling_bins", "ewaste_points", "lighting_waste", "disposal_sites")} == {"loading"}
    assert snap.errors == [] and snap.facilities == {} and snap.table is not None
    assert snap.facility_status["ewaste"] == "loading"

    gate.set()                                                      # let the background worker finish
    assert _wait_until(lambda: not cache.bg_inflight)
    snap2 = fetch_waste_snapshot(c, wait_for_layers=False)
    assert {s.status for s in snap2.sources} == {"ok"}
    assert {k: len(v.facilities) for k, v in snap2.facilities.items()} == {
        "recycling_bins": 3, "ewaste": 2, "lighting_waste": 2, "disposal_sites": 3}


def test_repeated_nonblocking_calls_start_only_one_download_per_layer():
    gate = threading.Event()
    polls = []
    cache = SourceCache()
    c = WasteDataClient(transport=httpx.MockTransport(_layer_handler(calls=polls, gate=gate)), cache=cache,
                        sleep=lambda s: None, poll_min_interval_s=0, disk_cache=None)
    for _ in range(5):
        fetch_waste_snapshot(c, wait_for_layers=False)
    gate.set()
    assert _wait_until(lambda: not cache.bg_inflight)
    assert sorted(polls) == sorted([src.BINS_ID, src.EWASTE_ID, src.LIGHTING_ID, src.DISPOSAL_ID])


def test_background_failure_becomes_unavailable_and_is_not_hammered():
    polls = []
    cache = SourceCache()
    c = WasteDataClient(transport=httpx.MockTransport(_layer_handler(calls=polls, fail_files=True)), cache=cache,
                        sleep=lambda s: None, poll_min_interval_s=0, disk_cache=None)
    fetch_waste_snapshot(c, wait_for_layers=False)
    assert _wait_until(lambda: not cache.bg_inflight)
    first = len(polls)
    snap = fetch_waste_snapshot(c, wait_for_layers=False)
    bins = next(s for s in snap.sources if s.key == "recycling_bins")
    assert bins.status == "unavailable" and "HTTP 500" in bins.error
    assert any("Recycling Bins" in e for e in snap.errors) and snap.table is not None
    assert len(polls) == first                                      # no immediate retry
    for ds, (_, msg) in list(cache.bg_failed.items()):               # pretend the retry window has passed
        cache.bg_failed[ds] = (_time.monotonic() - src.FAILURE_RETRY_S - 1, msg)
    snap2 = fetch_waste_snapshot(c, wait_for_layers=False)
    assert {s.status for s in snap2.sources if s.key == "ewaste_points"} == {"loading"}


def test_stale_cached_layer_is_served_and_refreshed_in_the_background():
    cache = SourceCache()
    layer = parse_facility_geojson(ewaste_geojson(), "ewaste")
    cache.put(f"layer:{src.EWASTE_ID}", layer, datetime.now(src.SG) - timedelta(days=3))
    c = WasteDataClient(transport=httpx.MockTransport(_layer_handler()), cache=cache, sleep=lambda s: None,
                        poll_min_interval_s=0, disk_cache=None)
    snap = fetch_waste_snapshot(c, wait_for_layers=False)
    ew = next(s for s in snap.sources if s.key == "ewaste_points")
    assert ew.status == "stale_cache" and len(snap.facilities["ewaste"].facilities) == 2
    assert any("refreshing in the background" in w for w in snap.warnings)
    assert _wait_until(lambda: not cache.bg_inflight)
    assert next(s for s in fetch_waste_snapshot(c, wait_for_layers=False).sources if s.key == "ewaste_points").status == "ok"


def test_blocking_mode_still_downloads_everything_and_default_client_is_shared(monkeypatch):
    snap = fetch_waste_snapshot(make_client(_layer_handler(), poll_min_interval_s=0, disk_cache=None))
    assert {s.status for s in snap.sources} == {"ok"}
    assert src.default_client() is src.default_client()
