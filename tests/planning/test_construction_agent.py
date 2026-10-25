from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from fastapi import HTTPException

from backend.app.planning.construction.agent import run_construction_agent
from backend.app.planning.construction.data import SourceResult
from backend.app.planning.construction import api as construction_api

SG = timezone(timedelta(hours=8))


def source(key, status="available", records=None, error=None):
    return SourceResult(
        key=key, name=key.replace("_", " "), agency="BCA", url="https://example.invalid",
        status=status, records=records or [], error=error,
    )


def snapshot(sources):
    return {"generated_at": datetime.now(SG).isoformat(), "sources": sources,
            "errors": [f"{s.name}: {s.error}" for s in sources.values() if s.error]}


def test_construction_successful_sources_build_report():
    report = run_construction_agent(fetcher=lambda: snapshot({
        "greenmark_buildings": source("greenmark_buildings", records=[{"Project_Name": "A", "Rating": "Platinum"}]),
        "ura_construction_pipeline": source("ura_construction_pipeline", records=[{"year": "2024", "building_completion": "10"}]),
    }))
    assert report.status == "OK"
    assert report.greenmark_summary["total_records"] == 1
    assert report.pipeline_records[0].year == 2024


def test_construction_failed_source_preserves_error_and_valid_data():
    report = run_construction_agent(fetcher=lambda: snapshot({
        "greenmark_buildings": source("greenmark_buildings", records=[{"Project_Name": "A"}]),
        "greenmark_geojson": source("greenmark_geojson", "unavailable", error="HTTP 403"),
    }))
    assert report.status == "PARTIAL"
    assert report.greenmark_buildings[0].project_name == "A"
    assert report.map_data["available"] is False
    assert any("HTTP 403" in warning for warning in report.warnings)
    assert any("HTTP 403" in error for error in report.errors)


def test_construction_empty_geojson_is_explicit_and_does_not_crash():
    report = run_construction_agent(fetcher=lambda: snapshot({
        "greenmark_buildings": source("greenmark_buildings", records=[{"Project_Name": "A"}]),
        "greenmark_geojson": source("greenmark_geojson", "empty"),
    }))
    assert report.status == "PARTIAL"
    assert report.map_data["available"] is False
    assert report.map_data["features"] == []
    assert any("status 'empty'" in warning for warning in report.warnings)


def test_construction_mapping_sources_are_normalized_at_input():
    report = run_construction_agent(fetcher=lambda: {"sources": {
        "greenmark_buildings": {"name": "Green Mark", "agency": "BCA", "url": "u", "status": "available", "records": [{"Rating": "Gold"}]},
        "greenmark_geojson": {"name": "Map", "agency": "BCA", "url": "u", "status": "unavailable", "error": "provider down", "records": []},
    }, "errors": ["Map: provider down"]})
    assert report.status == "PARTIAL"
    assert report.greenmark_summary["total_records"] == 1
    assert any("provider down" in warning for warning in report.warnings)


def test_failed_construction_warmup_does_not_cache_failure_and_can_retry():
    construction_api._cache.update({"report": None, "expires_at": 0.0})
    try:
        with patch.object(construction_api, "run_construction_agent", side_effect=[RuntimeError("temporary"), run_construction_agent(fetcher=lambda: snapshot({"greenmark_buildings": source("greenmark_buildings", records=[{"Rating": "Gold"}])}))]):
            try:
                construction_api.get_construction_report(refresh=True)
                assert False, "expected an explicit unavailable error"
            except HTTPException as exc:
                assert exc.status_code == 502
            assert construction_api._cache["report"] is None
            second = construction_api.get_construction_report(refresh=True)
            assert second.status == "OK"
    finally:
        construction_api._cache.update({"report": None, "expires_at": 0.0})
