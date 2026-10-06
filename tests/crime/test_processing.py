from types import SimpleNamespace

from backend.app.safety.crime.processing import process_snapshot


def test_missing_values_are_not_converted_to_zero():
    snapshot = SimpleNamespace(
        datasets={
            "crime_cases": [
                {"DataSeries": "Physical Crime Cases Recorded", "2025": "20857", "2024": "na"},
                {"DataSeries": "Scams", "2025": "37308"},
                {"DataSeries": "Scams & Cybercrimes Cases Recorded", "2025": "41974"},
                {"DataSeries": "Physical Crime Rate", "2025": "341"},
            ],
            "major_offences": [],
            "arrests": [],
            "npc": [],
        },
        source_status="available",
        warnings=[],
        errors=[],
    )
    report = process_snapshot(snapshot)
    assert report.total_physical_crime_2025 == 20857
    assert report.total_scams_2025 == 37308
    assert report.physical_crime_rate_2025 == 341
    assert report.major_offences == []


def test_official_2025_scam_rows_are_present():
    snapshot = SimpleNamespace(
        datasets={"crime_cases": [], "major_offences": [], "arrests": [], "npc": []},
        source_status="available",
        warnings=[],
        errors=[],
    )
    report = process_snapshot(snapshot)
    assert len(report.scam_types) == 10
    assert any(x.name == "Investment scams" and x.cases == 5462 for x in report.scam_types)


def test_npc_data_is_kept_tabular_without_coordinates():
    snapshot = SimpleNamespace(
        datasets={
            "crime_cases": [],
            "major_offences": [],
            "arrests": [],
            "npc": [{"DataSeries": "Central Police Division - Total", "2025": "308"}],
        },
        source_status="available",
        warnings=[],
        errors=[],
    )
    report = process_snapshot(snapshot)
    assert report.npc_geography[0].npc == "Central Police Division - Total"
    assert report.npc_geography[0].values["2025"] == 308
