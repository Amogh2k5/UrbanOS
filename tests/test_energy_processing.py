
from backend.app.infrastructure.energy.processing import build_report

def test_missing_data_is_not_zero():
    report = build_report({"datasets": {"peak_demand": None, "consumption": None, "solar_region": None, "solar_capacity": None}, "errors": []})
    assert report.key_metrics["latest_peak_demand_mw"] is None
    assert report.key_metrics["latest_solar_capacity_mwp"] is None
    assert report.status == "UNAVAILABLE"
    assert all(s.status == "unavailable" for s in report.sources)

def test_normalizes_official_rows_and_latest_period():
    snapshot = {"errors": [], "datasets": {
        "peak_demand": {"records": [
            {"year": "2020", "mth": "1", "peak_system_demand_mw": "7000"},
            {"year": "2020", "mth": "2", "peak_system_demand_mw": "-"},
        ]},
        "consumption": {"records": [{"year": "2019", "sector": "Households", "energy_products": "Electricity", "consumption_ktoe": "123.4"}]},
        "solar_region": {"records": [{"year": "2020", "ura_planning_region": "Central", "residential_status": "Residential", "num_solar_pv_inst": "5", "inst_cap_kwac": "12.2"}]},
        "solar_capacity": {"records": [
            {"year": "2020", "residential_status": "Residential", "user_type": "Residential", "inst_cap_mwp": "1.5"},
            {"year": "2020", "residential_status": "Non-Residential", "user_type": "Private Sector", "inst_cap_mwp": "2.5"},
            {"year": "2019", "residential_status": "Residential", "user_type": "Residential", "inst_cap_mwp": "1.0"},
        ]},
    }}
    report = build_report(snapshot)
    assert report.key_metrics["latest_peak_demand_mw"] == 7000
    assert report.key_metrics["latest_peak_demand_period"] == "2020-01"
    assert report.key_metrics["latest_solar_capacity_mwp"] == 4.0
    assert report.consumption[0]["consumption_ktoe"] == 123.4
    assert report.solar_by_region[0]["region"] == "Central"
    assert report.forecast["available"] is False
