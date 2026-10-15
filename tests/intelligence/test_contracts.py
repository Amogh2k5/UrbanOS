"""Shared intelligence contract tests.

Pure functions only - no network, no LLM, no database. These are the guard
rails that keep the rest of the platform from inventing findings.
"""
from __future__ import annotations

import pytest

from backend.app.intelligence.contracts import (
    CitySituationReport, CrossDomainImpact, DomainStatus, EvidenceRef, Finding,
    PriorityIncident, validate_finding, validate_report,
)
from backend.app.intelligence.normalize import (
    build_findings, build_kpi, determine_status, normalize_domain_report,
)

ALL_DOMAINS = ["traffic", "roads", "transit", "pm25", "weather", "flood",
               "fire", "crime", "water", "land"]


# ============================================================ contract invariants
def test_finding_without_evidence_is_rejected():
    f = Finding(id="t.1", domain="traffic", title="T", answer="A",
                data_kind="latest_available")
    assert validate_finding(f), "a claim without evidence must be rejected"


def test_finding_with_metrics_is_accepted():
    f = Finding(id="t.1", domain="traffic", title="T", answer="A",
                data_kind="live", metrics={"average_speed_kmh": 42.5})
    assert validate_finding(f) == []


def test_unavailable_finding_may_not_carry_severity():
    f = Finding(id="t.1", domain="traffic", title="T", answer="unavailable",
                data_kind="unavailable", severity="HIGH")
    problems = validate_finding(f)
    assert any("severity" in p for p in problems)


def test_empty_title_or_answer_is_rejected():
    for kwargs in ({"title": "", "answer": "A"}, {"title": "T", "answer": "  "}):
        f = Finding(id="t.1", domain="traffic", data_kind="unavailable", **kwargs)
        assert validate_finding(f)


def test_evidence_ref_citation_is_human_readable():
    ref = EvidenceRef(metric="rainfall", value=42.0, unit="mm",
                      source_name="NEA", observed_at="2026-10-11T09:00+08:00")
    c = ref.citation()
    assert "rainfall" in c and "42.0 mm" in c and "NEA" in c


# ============================================================ normalisation
def test_error_payload_is_unavailable_not_normal():
    s = normalize_domain_report("crime", {"error": "No data"})
    assert s.available is False
    assert s.overall_status is None, "unavailable must never report a status"
    assert s.confidence == "low"
    assert s.findings and s.findings[0].data_kind == "unavailable"
    assert s.findings[0].severity is None


def test_available_domain_carries_findings():
    data = {"overall_risk": "HIGH", "generated_at": "2026-10-11T00:00:00+08:00",
            "drain": {"readings_available": True, "sensors_with_readings": 12,
                      "sensor_count": 20, "sensors": []},
            "insights": [{"question": "Drain condition?", "answer": "12/20 reporting.",
                          "data_kind": "live"}]}
    s = normalize_domain_report("water", data)
    assert s.available is True
    assert s.findings, "available domains must expose findings"
    assert all(validate_finding(f) == [] for f in s.findings)


@pytest.mark.parametrize("domain", ALL_DOMAINS)
def test_every_domain_normalises_and_validates(domain):
    s = normalize_domain_report(domain, {"error": "test"})
    assert s.domain == domain
    assert s.findings and validate_finding(s.findings[0]) == []


def test_flood_enum_never_leaks_into_finding_text():
    """Regression: FloodRiskLevel is an enum in the raw report; it must be
    unwrapped before reaching user-facing text."""
    from enum import Enum

    class FloodRiskLevel(str, Enum):
        LOW = "LOW"

    f = build_findings("flood", {
        "risk_level": FloodRiskLevel.LOW,
        "primary_risk_factors": ["Heavy rainfall"],
        "active_alert_count": 0,
        "generated_at": "2026-10-11T09:00:00+08:00",
    })[0]
    assert "FloodRiskLevel" not in f.answer
    assert f.answer.startswith("Current flood risk is LOW.")
    assert f.metrics["risk_level"] == "LOW"


def test_flood_evidence_uses_scalars_not_nested_reprs():
    """Regression: nested evidence objects stringified into noise such as
    "Singapore rainfall: UNAVAILABLE ({'nested': 1})"."""
    f = build_findings("flood", {
        "risk_level": "LOW",
        "singapore_rainfall": {"status": "UNAVAILABLE", "detail": {"nested": 1},
                               "rain_mm": 12.5},
        "generated_at": "2026-10-11T09:00:00+08:00",
    })[0]
    joined = " ".join(f.evidence)
    assert "{'" not in joined
    assert "UNAVAILABLE" not in joined
    assert "rain_mm=12.5" in joined


def test_domain_status_matches_frontend_field_names():
    """The frontend type is a strict subset; these keys must exist."""
    s = normalize_domain_report("land", {"land_use": {"total_area_km2": 796.82}})
    payload = s.to_dict()
    for key in ("domain", "available", "overall_status", "overall_risk",
                "key_metrics", "active_alert_count", "affected_zones",
                "primary_risk_factors", "limitations", "is_ml_prediction"):
        assert key in payload, f"missing frontend field: {key}"


# ============================================================ status thresholds
def test_roads_critical_branch_is_reachable():
    """Regression: the old ordering tested >100 first, making critical dead."""
    assert determine_status("roads", {"road_works": {"active": 900}}) == "critical"
    assert determine_status("roads", {"road_works": {"active": 501}}) == "critical"
    assert determine_status("roads", {"road_works": {"active": 101}}) == "elevated"
    assert determine_status("roads", {"road_works": {"active": 0}}) == "normal"


def test_fire_escalates_in_order():
    assert determine_status("fire", {"active_incident_count": 0}) == "normal"
    assert determine_status("fire", {"active_incident_count": 3}) == "elevated"
    assert determine_status("fire", {"active_incident_count": 9}) == "critical"


def test_fire_never_invents_a_count_when_feed_is_empty():
    """None must stay None - never coerced to zero."""
    f = build_findings("fire", {"active_incident_count": None})[0]
    assert f.data_kind == "unavailable"
    assert "Absence of data" in f.answer or "unavailable" in f.answer.lower()


def test_water_risk_maps_to_status():
    assert determine_status("water", {"overall_risk": "CRITICAL"}) == "critical"
    assert determine_status("water", {"overall_risk": "MODERATE"}) == "elevated"
    assert determine_status("water", {"overall_risk": "LOW"}) == "normal"


def test_crime_is_never_escalated_without_a_severity_feed():
    for payload in ({"source_status": "ok", "total_physical_crime_2025": 999999},
                    {"source_status": "ok", "total_physical_crime_2025": 1}):
        assert determine_status("crime", payload) == "normal"


def test_crime_reports_unavailable_when_its_statistics_did_not_load():
    """Regression: an empty crime payload rendered as 'normal', implying a
    healthy picture when in fact nothing was fetched."""
    assert determine_status("crime", {"source_status": "unavailable"}) == "unavailable"
    assert determine_status("crime", {"source_status": "ok"}) == "unavailable"
    assert determine_status("crime", {}) == "unavailable"


# ==================================================================== KPIs
def test_crime_kpi_uses_real_report_fields():
    kpi = build_kpi("crime", {"total_physical_crime_2025": 4321})
    assert kpi and kpi["value"] == 4321


def test_kpi_is_none_when_no_supported_metric():
    assert build_kpi("crime", {"data_period": "2025"}) is None


def test_land_kpi_prefers_area_then_planning_areas():
    assert build_kpi("land", {"land_use": {"total_area_km2": 796.82},
                              "planning": {"planning_area_count": 55}})["value"] == 796.8
    assert build_kpi("land", {"planning": {"planning_area_count": 55}})["value"] == 55


# =============================================================== report checks
def test_cross_domain_impact_without_evidence_is_rejected():
    report = CitySituationReport(
        generated_at="2026-10-11T00:00:00+08:00",
        cross_domain_impacts=[CrossDomainImpact(
            type="drain_flood_context", description="d", severity="HIGH",
            domains_involved=["water", "flood"], evidence=[])],
    )
    problems = validate_report(report)
    assert any("no evidence" in p for p in problems)


def test_cross_domain_impact_with_evidence_passes():
    report = CitySituationReport(
        generated_at="2026-10-11T00:00:00+08:00",
        cross_domain_impacts=[CrossDomainImpact(
            type="drain_flood_context", description="d", severity="HIGH",
            domains_involved=["water", "flood"], evidence=["drain 98% of reference"])],
    )
    assert validate_report(report) == []


def test_single_domain_impact_is_not_cross_domain():
    report = CitySituationReport(
        generated_at="2026-10-11T00:00:00+08:00",
        cross_domain_impacts=[CrossDomainImpact(
            type="x", description="d", severity="LOW",
            domains_involved=["water"], evidence=["e"])],
    )
    assert any("fewer than 2 domains" in p for p in validate_report(report))


def test_unavailable_domain_must_not_report_a_status():
    good = DomainStatus(domain="water", available=False, overall_status=None)
    bad = DomainStatus(domain="water", available=False, overall_status="NORMAL")
    r1 = CitySituationReport(generated_at="x", domain_status={"water": good})
    r2 = CitySituationReport(generated_at="x", domain_status={"water": bad})
    assert validate_report(r1) == []
    assert any("must not report status" in p for p in validate_report(r2))


def test_available_domain_cannot_carry_an_error():
    r = CitySituationReport(
        generated_at="x",
        domain_status={"water": DomainStatus(domain="water", available=True,
                                             error="boom")},
    )
    assert any("carries an error" in p for p in validate_report(r))