from backend.app.planning.housing.data import DATASETS, SourceResult
from backend.app.planning.housing.processing import build_housing_report

def _source(key, rows, status="available"):
    spec = DATASETS[key]
    return SourceResult(key, spec["name"], spec["agency"], spec["url"], status, rows, "2026-10-11T10:00:00+08:00")

def test_builds_resale_trend_and_preserves_missing_values():
    snapshot = {
        "generated_at": "2026-10-11T10:00:00+08:00",
        "sources": {
            "median_resale": _source("median_resale", [
                {"quarter": "2025-Q4", "town": "Town A", "flat_type": "4-room", "price": "500000"},
                {"quarter": "2025-Q4", "town": "Town B", "flat_type": "4-room", "price": "600000"},
                {"quarter": "2026-Q1", "town": "Town A", "flat_type": "4-room", "price": "520000"},
                {"quarter": "2026-Q1", "town": "Town B", "flat_type": "4-room", "price": "-"},
            ]),
            "resale_applications": _source("resale_applications", [], status="unavailable"),
            "hdb_property": _source("hdb_property", [
                {"blk_no": "10", "street": "TEST STREET", "year_completed": "1990",
                 "total_dwelling_units": "100", "bldg_contract_town": "Town A"},
            ]),
        },
        "errors": ["applications source unavailable"],
    }
    report = build_housing_report(snapshot)
    assert report.status == "PARTIAL"
    assert report.kpis["latest_median_resale_period"] == "2026-Q1"
    assert report.kpis["town_flat_type_median_price_rows"] == 1
    assert report.town_prices[0]["4-room"] == 520000
    assert report.kpis["resale_applications"] is None
    assert report.housing_stock["total_dwelling_units_in_records"] == 100
    assert report.map_data["features"] == []

def test_missing_sources_do_not_become_zero():
    snapshot = {
        "generated_at": "2026-10-11T10:00:00+08:00",
        "sources": {
            k: _source(k, [], status="unavailable") for k in DATASETS
        },
        "errors": ["all sources unavailable"],
    }
    report = build_housing_report(snapshot)
    assert report.status == "UNAVAILABLE"
    assert report.kpis["hdb_property_records"] is None
    assert report.kpis["resale_applications"] is None
    assert report.rental_market["hdb_median_rent"] is None
