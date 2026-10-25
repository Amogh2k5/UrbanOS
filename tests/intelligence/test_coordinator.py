"""Focused tests for the deterministic City Coordinator.

The water suite already pins the contract end-to-end. These tests cover the
guarantees that suite cannot reach on its own: failure isolation across every
domain, the "unknown is not normal" rule, evidence gating on cross-domain
impacts, determinism, and evidence-linked recommendations.
"""
from __future__ import annotations

import contextlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from coordinator.city_agent import (
    CORE_DOMAINS, CityCoordinatorState, analyze_cross_domain_impacts,
    collect_reports, generate_recommendations, normalize, normalize_state,
    prioritize_risks,
)
from backend.app.coordinator.domain_graph import DomainGraphRegistry
from backend.app.coordinator import city_agent as coordinator_module
from backend.app.intelligence.contracts import validate_report

ALL_RUNNERS = [
    "EnvironmentModule", "run_traffic_agent", "run_flood_agent_v3",
    "run_water_agent", "run_land_agent", "run_fire_agent", "run_crime_agent",
]


def _state_with_status(**overrides) -> CityCoordinatorState:
    """A state whose domain_status is set directly, skipping collection."""
    st = CityCoordinatorState()
    base = {
        "environment": {"available": True, "overall_risk": "LOW",
                        "key_metrics": {}, "limitations": [], "confidence": "high"},
        "traffic": {"available": True, "overall_risk": "LOW",
                    "key_metrics": {}, "limitations": [], "confidence": "high"},
        "flood": {"available": True, "overall_risk": "LOW",
                  "key_metrics": {}, "limitations": [], "confidence": "high"},
    }
    base.update(overrides)
    st.domain_status = base
    return st


# ================================================== failure isolation
def test_every_domain_failing_still_yields_a_report():
    """One failing module must never crash the coordinator."""
    with patch("coordinator.city_agent.EnvironmentModule") as env, \
         patch("coordinator.city_agent.run_traffic_agent", side_effect=RuntimeError("t")), \
         patch("coordinator.city_agent.run_flood_agent_v3", side_effect=RuntimeError("f")), \
         patch("coordinator.city_agent.run_water_agent", side_effect=RuntimeError("w")), \
         patch("coordinator.city_agent.run_land_agent", side_effect=RuntimeError("l")), \
         patch("coordinator.city_agent.run_fire_agent", side_effect=RuntimeError("fi")), \
         patch("coordinator.city_agent.run_crime_agent", side_effect=RuntimeError("c")):
        env.return_value.run.side_effect = RuntimeError("e")
        st = collect_reports(CityCoordinatorState())

    assert st.environment_report is None
    # Every failure is recorded, as an error, a warning, or both.
    assert any("Water report unavailable" in w for w in st.warnings)
    assert any("Land report unavailable" in w for w in st.warnings)
    assert any("Traffic Agent failed" in e for e in st.errors)
    assert any("Flood Agent failed" in e for e in st.errors)
    assert any("Environment Agent failed" in e for e in st.errors)

    st = normalize_state(st)
    st = prioritize_risks(st)
    st = analyze_cross_domain_impacts(st)
    st = generate_recommendations(st)
    report = normalize(st).report

    assert report is not None
    assert validate_report(report) == []
    assert set(report.domain_status) >= set(CORE_DOMAINS)


def test_coordinator_deadline_is_handled_without_waiting(monkeypatch):
    class ImmediateAdapter:
        def invoke(self, *args, **kwargs):
            return SimpleNamespace(graph_state={"report": None}, errors=[], warnings=[])

    monkeypatch.setattr(DomainGraphRegistry, "get", classmethod(lambda cls, name: ImmediateAdapter()))
    monkeypatch.setattr(coordinator_module, "wait", lambda futures, timeout: (set(), set(futures)))
    state = collect_reports(CityCoordinatorState())
    assert any("30 second coordinator deadline" in message for message in state.errors + state.warnings)


def test_partial_graph_failure_keeps_independent_domain_results(monkeypatch):
    class Adapter:
        def __init__(self, domain):
            self.domain = domain
        def invoke(self, *args, **kwargs):
            if self.domain == "traffic":
                raise RuntimeError("isolated test failure")
            report = SimpleNamespace(
                domain=self.domain, subdomain=self.domain,
                generated_at="2026-10-24T00:00:00+08:00", source_status="test",
                is_ml_prediction=False,
            )
            return SimpleNamespace(graph_state={"report": report}, errors=[], warnings=[])

    monkeypatch.setattr(
        DomainGraphRegistry, "get",
        classmethod(lambda cls, name: Adapter(name)),
    )
    state = collect_reports(CityCoordinatorState())
    assert state.traffic_report is None
    assert state.flood_report is not None
    assert any("Traffic Agent failed" in message for message in state.errors)


@pytest.mark.parametrize("runner", ALL_RUNNERS)
def test_single_domain_failure_is_isolated(runner):
    """Patch exactly one domain to fail; the run must still complete and record it.

    The other domains are stubbed rather than really executed: this test is
    about failure isolation, not agent behaviour, and running seven live agents
    per parameter would dominate the suite runtime.
    """
    stub = SimpleNamespace(
        domain="test", subdomain="stub", generated_at="2026-10-11T00:00:00+08:00",
        source_status="ok", is_ml_prediction=False,
        overall_status="NORMAL", overall_risk="LOW", overall_congestion_level="free_flow",
        overall_average_speed=55.0, risk_level="LOW", risk_score=0.0,
        active_alert_count=0, affected_zones=[], primary_risk_factors=[],
        confidence="high", limitations=[], warnings=[], errors=[], alerts=[],
        incidents=[], regions=[], data_quality_flags=[], key_metrics={},
        model_dump=lambda **_k: {"subdomain": "stub"},
    )

    with contextlib.ExitStack() as stack:
        started = {name: stack.enter_context(patch(f"coordinator.city_agent.{name}"))
                   for name in ALL_RUNNERS if name != "EnvironmentModule"}
        env_mod = stack.enter_context(patch("coordinator.city_agent.EnvironmentModule"))

        for name, p in started.items():
            if name == runner:
                p.side_effect = RuntimeError("boom")
            else:
                p.side_effect = None
                p.return_value = stub
        env_mod.return_value.run.side_effect = (
            RuntimeError("boom") if runner == "EnvironmentModule" else None
        )
        env_mod.return_value.run.return_value = stub

        st = collect_reports(CityCoordinatorState())

    recorded = st.errors + st.warnings
    assert recorded, f"{runner} failure was not recorded"
    recorded = st.errors + st.warnings
    assert any("unavailable" in m or "failed" in m.lower() for m in recorded), (
        f"{runner} failure was recorded only as {recorded!r}"
    )
    if runner in ("run_water_agent", "run_land_agent"):
        # Advisory domains must not be recorded as errors.
        assert not any("Agent failed" in e for e in st.errors), st.errors


# ================================================== unknown is never normal
def test_missing_report_becomes_unavailable_with_an_error():
    st = normalize_state(CityCoordinatorState())
    for domain in CORE_DOMAINS + ("water", "land", "fire", "crime"):
        ds = st.domain_status[domain]
        assert ds["available"] is False
        assert ds["error"], domain
        assert ds["overall_status"] is None, f"{domain} reported a status with no data"
        assert ds["overall_risk"] is None, f"{domain} reported a risk with no data"


def test_unavailable_domains_do_not_lower_city_risk():
    st = _state_with_status(
        water={"available": False, "overall_risk": None, "key_metrics": {},
               "error": "unavailable", "limitations": []},
        land={"available": False, "overall_risk": None, "key_metrics": {},
              "error": "unavailable", "limitations": []},
    )
    out = prioritize_risks(st)
    assert out.overall_risk_level == "LOW"
    assert out.overall_city_status == "NORMAL"


def test_unknown_risk_does_not_escalate():
    st = _state_with_status(
        water={"available": True, "overall_risk": "UNKNOWN", "key_metrics": {},
               "limitations": []},
    )
    out = prioritize_risks(st)
    assert out.overall_risk_level == "LOW"


def test_unavailable_domain_creates_no_priority_incident():
    st = _state_with_status(
        water={"available": False, "overall_risk": None, "key_metrics": {},
               "error": "down", "limitations": []},
    )
    out = prioritize_risks(st)
    assert not any(i["domain"] == "water" for i in out.priority_incidents)


def test_no_data_recommendation_does_not_claim_normality():
    st = _state_with_status(
        water={"available": False, "overall_risk": None, "key_metrics": {},
               "error": "down", "limitations": []},
    )
    st = prioritize_risks(st)
    st = generate_recommendations(st)
    joined = " ".join(st.city_level_recommendations).lower()
    assert "absence of data is not evidence" in joined


# ================================================== cross-domain evidence gating
def _drain_state(readings_available: bool, max_pct=None, elevated=0, flood_risk="HIGH"):
    return _state_with_status(
        water={"available": True, "overall_risk": "MODERATE", "key_metrics": {
            "drain_readings_available": readings_available,
            "drain_max_fill_pct": max_pct,
            "drain_elevated_count": elevated,
        }, "limitations": []},
        flood={"available": True, "overall_risk": flood_risk,
               "affected_zones": ["Central"], "key_metrics": {}, "limitations": [],
               "active_alert_count": 2},
    )


def test_impact_requires_real_readings_and_flood_risk():
    st = analyze_cross_domain_impacts(_drain_state(True, 97.5, 1, "HIGH"))
    impact = next(i for i in st.cross_domain_impacts if i["type"] == "drain_flood_context")
    assert impact["severity"] == "HIGH"
    assert set(impact["domains_involved"]) == {"water", "flood"}
    assert impact["evidence"], "impact must carry evidence"


def test_no_impact_without_real_readings():
    st = analyze_cross_domain_impacts(_drain_state(False, None, 0, "HIGH"))
    assert not [i for i in st.cross_domain_impacts if i["type"] == "drain_flood_context"]


def test_no_impact_without_elevated_flood_risk():
    st = analyze_cross_domain_impacts(_drain_state(True, 97.5, 1, "LOW"))
    assert not [i for i in st.cross_domain_impacts if i["type"] == "drain_flood_context"]


def test_no_impact_when_flood_domain_is_missing():
    st = _drain_state(True, 97.5, 1, "HIGH")
    st.domain_status["flood"] = {"available": False, "overall_risk": None,
                                 "key_metrics": {}, "error": "down"}
    out = analyze_cross_domain_impacts(st)
    assert not out.cross_domain_impacts


def test_observed_air_quality_drives_the_environment_domain():
    """The cross-domain air-quality rules must judge what is measured now, not
    a model forecast fed by the static research dataset (which ends in 2024)."""
    from backend.app.coordinator import city_agent

    observed = {
        "available": True, "max_pm25": 119.0, "mean_pm25": 101.0,
        "regions": {"west": 119.0, "east": 114.0, "central": 105.0, "north": 60.0},
        "observed_at": "2026-10-17T03:00:00+08:00",
    }
    rep = MagicMock()
    rep.regions = [{"pm25_next_day_max": 20.0}]
    rep.weather_forecast = {"forecast_code": "TS"}
    rep.data_quality_flags = []
    rep.generated_at = "2026-10-17T03:00:00+08:00"
    rep.model_dump.return_value = {"regions": [{"pm25_next_day_max": 20.0}]}
    rep.model_dump.side_effect = lambda **kw: {"regions": [{"pm25_next_day_max": 20.0}]}

    with patch.object(city_agent, "_observed_air_quality", lambda: observed):
        out = city_agent._normalize_environment(rep)

    assert out["overall_risk"] == "HIGH"          # 119 is above the PSI high band
    assert out["key_metrics"]["max_pm25_observed"] == 119.0
    assert out["key_metrics"]["max_pm25_next_day_max"] == 20.0
    assert "west" in out["affected_zones"]
    # And the forecast is still reported, just not used as the conclusion.
    assert out["key_metrics"]["forecast_pm25_risk"] == "LOW"


def test_unhealthy_air_and_disrupted_traffic_produce_a_validated_signal():
    """Regression: the engine could never pair these, so it produced nothing
    while the city genuinely had two problems at once."""
    st = _state_with_status(
        traffic={"available": True, "overall_status": "disrupted", "overall_risk": "HIGH",
                 "affected_zones": ["West North"], "key_metrics": {}, "limitations": []},
        environment={
            "available": True, "overall_status": "ELEVATED", "overall_risk": "HIGH",
            "affected_zones": ["west"],
            "key_metrics": {
                "max_pm25_observed": 119.0,
                "observed_pm25_regions": {"west": 119.0, "east": 114.0},
                "observed_pm25_at": "2026-10-17T03:00:00+08:00",
                "weather_forecast_available": True,
            },
            "limitations": [],
        },
    )
    out = analyze_cross_domain_impacts(st)
    aq_traffic = [i for i in out.cross_domain_impacts if i["type"] == "air_quality_traffic"]

    assert len(aq_traffic) == 1
    impact = aq_traffic[0]
    # Both sides carry their own evidence; neither is inferred from the other.
    assert any("119" in e for e in impact["evidence"])
    assert any("disrupted" in e for e in impact["evidence"])
    assert impact["evidence"]                       # never empty
    assert set(impact["domains_involved"]) == {"air_quality", "traffic"}
    # It becomes an actionable priority incident, not just a count.
    assert any(i["type"] == "air_quality_traffic" for i in out.priority_incidents)


def test_healthy_air_with_disrupted_traffic_produces_no_air_quality_signal():
    """The rule must not fire on traffic alone."""
    st = _state_with_status(
        traffic={"available": True, "overall_status": "disrupted", "overall_risk": "HIGH",
                 "affected_zones": ["West North"], "key_metrics": {}, "limitations": []},
        environment={
            "available": True, "overall_status": "NORMAL", "overall_risk": "LOW",
            "affected_zones": [],
            "key_metrics": {"max_pm25_observed": 40.0,
                            "observed_pm25_regions": {"west": 40.0},
                            "weather_forecast_available": True},
            "limitations": [],
        },
    )
    out = analyze_cross_domain_impacts(st)
    types = [i["type"] for i in out.cross_domain_impacts]
    assert "air_quality_traffic" not in types
    # ...and the engine explains why it did not fire.
    assert any(m["rule"] == "air_quality_traffic" for m in out.near_misses)


def test_near_misses_never_become_signals():
    """A near miss is disclosure only: it must not reach incidents or risk."""
    st = _state_with_status(
        flood={"available": True, "overall_risk": "LOW", "affected_zones": [],
               "key_metrics": {}, "limitations": []},
        traffic={"available": True, "overall_status": "normal", "overall_risk": "LOW",
                 "affected_zones": [], "key_metrics": {}, "limitations": []},
    )
    out = analyze_cross_domain_impacts(st)
    assert out.cross_domain_impacts == []
    assert out.priority_incidents == []
    assert out.near_misses


def test_data_gaps_lists_only_real_gaps_not_methodology_notes():
    """Regression: the Data Gaps section repeated the coordinator's own
    methodology notes, overstating how much data was missing."""
    from backend.app.coordinator.city_agent import CityCoordinatorState, build_report
    from backend.app.coordinator.city_agent import _normalize_crime

    state = CityCoordinatorState()
    state.domain_status = {
        "crime": {**_normalize_crime(None), "available": False,
                  "error": "Crime statistics are unavailable for the published period."},
        "land": {"available": True, "overall_status": "NORMAL", "overall_risk": "LOW",
                 "key_metrics": {}, "limitations": [], "affected_zones": []},
    }
    state.warnings = ["Water report unavailable"]
    state.errors = ["Fire Agent failed"]

    report = build_report(state).report

    assert report.data_gaps
    joined = " ".join(report.data_gaps).lower()
    assert "crime" in joined
    # Methodology boilerplate must not be dressed up as a data gap.
    assert "deterministic rule engine" not in joined
    assert "core domains" not in joined


def test_co_elevated_domains_are_counted_but_never_causally_linked():
    """Correlation is not causation.

    Two elevated domains with no shared driver must not produce a causal
    impact. They may legitimately produce ``multi_domain_high_risk``, which is
    explicitly a count and says so.
    """
    st = _state_with_status(
        water={"available": True, "overall_risk": "HIGH", "key_metrics": {}, "limitations": []},
        flood={"available": True, "overall_risk": "HIGH",
               "affected_zones": ["Central"], "key_metrics": {}, "limitations": []},
    )
    out = analyze_cross_domain_impacts(st)
    types = [i["type"] for i in out.cross_domain_impacts]

    # No causal pair is asserted between water and flood.
    assert "drain_flood_context" not in types
    assert "flood_traffic" not in types
    # The co-elevation is still surfaced, as a count.
    multi = [i for i in out.cross_domain_impacts if i["type"] == "multi_domain_high_risk"]
    assert len(multi) == 1
    assert set(multi[0]["domains_involved"]) == {"water", "flood"}
    assert "No causal link" in multi[0]["description"]


def test_impact_passes_the_shared_contract_validator():
    st = analyze_cross_domain_impacts(_drain_state(True, 97.5, 1, "HIGH"))
    st = prioritize_risks(st)
    report = normalize(st).report
    problems = [p for p in validate_report(report)
                if "no evidence" in p or "fewer than 2" in p]
    assert problems == []


# ================================================== recommendations
def test_recommendations_are_domain_prefixed_and_evidence_backed():
    st = analyze_cross_domain_impacts(_drain_state(True, 97.5, 1, "HIGH"))
    st.overall_risk_level = "HIGH"
    st = generate_recommendations(st)
    water_recs = [r for r in st.city_level_recommendations if r.startswith("WATER:")]
    assert water_recs
    assert "drain" in water_recs[0].lower()


def test_recommendation_not_emitted_without_supporting_impact():
    """No measured drain loading -> water stays LOW -> nothing to recommend."""
    st = _drain_state(False, None, 0, "HIGH")
    st.domain_status["water"]["overall_risk"] = "LOW"
    st = analyze_cross_domain_impacts(st)
    st.overall_risk_level = "HIGH"
    st = generate_recommendations(st)
    assert not [r for r in st.city_level_recommendations if r.startswith("WATER:")]
    # Flood is genuinely elevated, so its own recommendation must still exist.
    assert [r for r in st.city_level_recommendations if r.startswith("FLOOD:")]


# ================================================== determinism
def test_prioritization_is_deterministic():
    a = prioritize_risks(_state_with_status()).overall_risk_level
    b = prioritize_risks(_state_with_status()).overall_risk_level
    assert a == b == "LOW"


def test_worst_known_risk_wins():
    st = _state_with_status(
        traffic={"available": True, "overall_risk": "CRITICAL",
                 "key_metrics": {}, "limitations": [], "affected_zones": ["Central"]},
    )
    out = prioritize_risks(st)
    assert out.overall_risk_level == "CRITICAL"
    assert out.overall_city_status == "CRITICAL"
    # A lone elevated domain is not a co-occurring incident, so it raises city
    # risk and produces a recommendation rather than a priority incident.
    assert out.priority_incidents == []
    st2 = generate_recommendations(out)
    assert any(r.startswith("TRAFFIC:") for r in st2.city_level_recommendations)


def test_priority_incidents_track_co_occurring_conditions():
    st = analyze_cross_domain_impacts(_drain_state(True, 97.5, 1, "HIGH"))
    kinds = {i["type"] for i in st.priority_incidents}
    assert "drain_flood_context_overlap" in kinds


def test_confidence_rule_is_unaffected_by_extra_domains():
    core_only = _state_with_status()
    with_extra = _state_with_status(
        water={"available": True, "overall_risk": "UNKNOWN", "key_metrics": {}, "limitations": []},
        land={"available": True, "overall_risk": "UNKNOWN", "key_metrics": {}, "limitations": []},
        fire={"available": False, "overall_risk": None, "key_metrics": {}, "error": "x"},
        crime={"available": False, "overall_risk": None, "key_metrics": {}, "error": "x"},
    )
    assert prioritize_risks(core_only).confidence == prioritize_risks(with_extra).confidence


# ================================================== final report
def test_final_report_passes_contract_validation_when_nothing_is_collected():
    st = normalize_state(CityCoordinatorState())
    st = prioritize_risks(st)
    st = analyze_cross_domain_impacts(st)
    st = generate_recommendations(st)
    report = normalize(st).report
    assert validate_report(report) == []
    assert report.overall_city_status == "UNKNOWN"
    assert report.is_ml_prediction is False


def test_evidence_entries_name_their_source():
    st = _state_with_status(
        water={"available": True, "overall_risk": "LOW",
               "key_metrics": {"potable_sales_latest_mm3": 515.5}, "limitations": [],
               "generated_at": "2026-10-11T00:00:00+08:00"},
    )
    st.source_reports["water"] = {"subdomain": "water"}
    report = normalize(st).report
    water = next(e for e in report.evidence if e["source"] == "water")
    assert water["key_metrics"]["potable_sales_latest_mm3"] == 515.5
    assert water["subdomain"] == "water"
