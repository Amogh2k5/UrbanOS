from types import SimpleNamespace

import pytest
pytest.importorskip("langgraph")

from backend.app.safety.crime import agent


def test_crime_agent_builds_report_from_snapshot(monkeypatch):
    snapshot = SimpleNamespace(
        datasets={
            "crime_cases": [
                {"DataSeries": "Physical Crime Cases Recorded", "2025": "20857"},
                {"DataSeries": "Scams & Cybercrimes Cases Recorded", "2025": "41974"},
                {"DataSeries": "Scams", "2025": "37308"},
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
    monkeypatch.setattr(agent.DataGovCrimeClient, "fetch_all", lambda self: snapshot)
    report = agent.run_crime_agent()
    assert report.total_physical_crime_2025 == 20857
    assert report.total_scams_cybercrime_2025 == 41974
    assert report.is_ml_prediction is False
