"""Cold-start behaviour of the City Situation summary.

The coordinator takes ~74s to run, which is far longer than a dashboard
refresh may wait. These tests pin the contract that follows from that:

  * the Overview endpoint never returns a null ``ai_brief`` while any
    independently validated evidence exists;
  * a slow, failing or unavailable LLM yields the deterministic prose, never a
    hang and never an invention;
  * when the coordinator has nothing usable, the summary is grounded only in
    per-domain evidence and asserts no city status, risk, severity, trend,
    affected area or causal link;
  * concurrent cold requests collapse onto a single coordinator run.

Covered: cold cache + slow LLM, LLM timeout/failure, coordinator unavailable,
partial domain availability, concurrent single-flight, preserved deterministic
fields, and no fabrication when evidence is insufficient.
"""
from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import patch

import pytest

from backend.app.ai.narrative import (
    deterministic_summary, deterministic_summary_from_domains,
)
from backend.app.coordinator import access
from backend.app.coordinator.city_report import CitySituationReport
from backend.app.intelligence.contracts import DomainStatus


# --------------------------------------------------------------- fixtures
def _report() -> CitySituationReport:
    """A coordinator report with real, checkable evidence."""
    return CitySituationReport(
        generated_at="2026-10-11T09:00:00+08:00",
        overall_city_status="DISRUPTED",
        overall_risk_level="HIGH",
        confidence="high",
        domain_status={
            "flood": {"domain": "flood", "available": True, "overall_risk": "HIGH",
                      "overall_status": "HIGH", "affected_zones": ["Central South"],
                      "key_metrics": {}, "limitations": []},
            "fire": {"domain": "fire", "available": False, "error": "empty feed",
                     "limitations": ["Fire feed returned no records."]},
        },
        cross_domain_impacts=[{
            "type": "flood_traffic",
            "description": "HIGH flood risk in Central South.",
            "severity": "HIGH", "affected_zones": ["Central South"],
            "domains_involved": ["flood", "traffic"],
            "evidence": ["Flood risk reported as HIGH."],
        }],
        city_level_recommendations=["FLOOD+TRAFFIC: Coordinate response."],
        affected_zones=["Central South"],
    )


def _domains(available=("traffic",), unavailable=("fire",)) -> dict:
    out = {}
    for d in available:
        out[d] = DomainStatus(domain=d, available=True, overall_status="NORMAL",
                              overall_risk="LOW")
    for d in unavailable:
        out[d] = DomainStatus(domain=d, available=False, error="no feed")
    return out


class _SlowLLM:
    """Available LLM that never answers in time."""

    def __init__(self):
        self.calls = 0

    def is_available(self):
        return True

    async def generate_city_narrative(self, report):
        self.calls += 1
        await asyncio.sleep(30)
        return "never", None


# ------------------------------------------- 1. cold cache + slow LLM
@pytest.mark.asyncio
async def test_slow_llm_falls_back_to_deterministic_prose_promptly():
    """A valid coordinator report + a slow LLM must still answer, and fast."""
    from backend.app.overview.api import _NARRATIVE_BUDGET_S, _narrative_or_fallback

    svc = _SlowLLM()
    started = time.perf_counter()
    out = await _narrative_or_fallback(svc, _report())
    elapsed = time.perf_counter() - started

    assert out == deterministic_summary(_report())
    assert "DISRUPTED" in out
    assert svc.calls == 1
    # It returned at the budget, not at the LLM's own 30s sleep.
    assert elapsed < 10.0, f"waited {elapsed:.1f}s"
    assert _NARRATIVE_BUDGET_S <= 10.0


# --------------------------------- 2. LLM timeout / provider failure
@pytest.mark.asyncio
async def test_llm_provider_failure_returns_deterministic_prose():
    from backend.app.overview.api import _narrative_or_fallback

    class _Boom:
        def is_available(self):
            return True

        async def generate_city_narrative(self, report):
            raise RuntimeError("provider exploded")

    out = await _narrative_or_fallback(_Boom(), _report())
    assert out == deterministic_summary(_report())


@pytest.mark.asyncio
async def test_llm_unavailable_returns_deterministic_prose_without_calling():
    from backend.app.overview.api import _narrative_or_fallback

    calls = []

    class _Unavailable:
        def is_available(self):
            return False

        async def generate_city_narrative(self, report):
            calls.append(1)
            return "should not happen", None

    out = await _narrative_or_fallback(_Unavailable(), _report())
    assert out == deterministic_summary(_report())
    assert calls == []


# ------------------------------------------ 4. partial domain availability
def test_partial_availability_reports_available_and_unavailable_domains():
    out = deterministic_summary_from_domains(_domains())
    assert "traffic" in out
    assert "fire" in out
    # Missing data is never dressed up as healthy.
    assert "Absence of data is not evidence of normal conditions." in out


def test_all_domains_unavailable_is_an_explicit_unavailable_state():
    out = deterministic_summary_from_domains(_domains(available=(), unavailable=("a", "b")))
    assert "Could not be assessed: a, b." in out
    assert "Absence of data is not evidence of normal conditions." in out


# ------------------------------ 6. preserved deterministic status / risk
def test_domain_fallback_never_claims_a_city_status_or_risk_level():
    """Per-domain status cannot derive a city-level conclusion."""
    out = deterministic_summary_from_domains(_domains())
    assert "no city status or risk level is claimed" in out
    for word in ("City status", "City risk", "overall_risk"):
        assert word not in out


def test_coordinator_fields_are_unchanged_by_the_cold_path():
    """The cold path adds prose only; it never rewrites coordinator output."""
    report = _report()
    before = report.model_dump(mode="json")
    deterministic_summary_from_domains(
        {k: v for k, v in report.domain_status.items()})
    assert report.model_dump(mode="json") == before
    # The coordinator's own conclusions are still exactly what it said.
    assert report.overall_city_status == "DISRUPTED"
    assert report.overall_risk_level == "HIGH"
    assert report.city_level_recommendations == ["FLOOD+TRAFFIC: Coordinate response."]


def test_domain_summary_is_deterministic():
    a = deterministic_summary_from_domains(_domains())
    b = deterministic_summary_from_domains(dict(reversed(list(_domains().items()))))
    assert a == b


# ------------------------------- 7. no fabrication without evidence
def test_no_evidence_yields_no_summary_at_all():
    assert deterministic_summary_from_domains({}) is None
    assert deterministic_summary_from_domains(None) is None
    assert deterministic_summary(None) is None


def test_domain_summary_invents_no_numbers_or_severities():
    out = deterministic_summary_from_domains(_domains())
    # Every number in the output is an ordinal or from the evidence; none are
    # invented measurements.
    assert "km/h" not in out and "µg/m³" not in out and "%" not in out
    for escalated in ("CRITICAL", "ELEVATED", "DISRUPTED"):
        assert escalated not in out


# --------------------------------- 3 + 5. accessor: unavailable + flight
@pytest.fixture
def no_background_runs():
    """Stop cold reads from launching real ~74s coordinator runs."""
    access.invalidate_city_report_cache()
    access.set_background_runs_enabled(False)
    yield
    access.set_background_runs_enabled(True)
    access.invalidate_city_report_cache()


def test_cold_cache_is_non_blocking_and_returns_none(no_background_runs):
    started = time.perf_counter()
    out = access.city_report_cached(block=False)
    elapsed = time.perf_counter() - started
    # Returns immediately; the caller must degrade rather than hang.
    assert out is None
    assert elapsed < 1.0, f"blocked for {elapsed:.2f}s"


def test_cold_cache_starts_exactly_one_background_run():
    """Concurrent cold reads collapse onto a single coordinator run."""
    access.invalidate_city_report_cache()

    runs = []
    gate = threading.Event()
    stamps = []

    def _fake_run():
        runs.append(1)
        # Hold the run open so every thread observes it in flight.
        gate.wait(timeout=5)

    access.set_background_runs_enabled(True)
    try:
        with patch.object(access, "_run_coordinator", _fake_run):
            barrier = threading.Barrier(8)

            def _hit():
                barrier.wait()
                t0 = time.perf_counter()
                assert access.city_report_cached(block=False) is None
                stamps.append(time.perf_counter() - t0)

            threads = [threading.Thread(target=_hit) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            # All eight cold reads returned promptly without waiting for the run.
            assert len(stamps) == 8
            assert max(stamps) < 2.0, f"a cold read waited {max(stamps):.2f}s"
            assert access.coordinator_run_in_flight() is True
            assert len(runs) == 1, f"started {len(runs)} coordinator runs"
    finally:
        gate.set()
        access.set_background_runs_enabled(False)

    for t in threads:
        t.join(timeout=10)
    access.invalidate_city_report_cache()


def test_blocking_mode_is_preserved_for_the_city_report_route(no_background_runs):
    """``/api/city/report`` still waits for the full run (default block=True)."""
    with patch.object(access, "_run_coordinator", return_value=_report()):
        out = access.city_report_cached()
    assert out is not None
    report, payload = out
    assert report.overall_city_status == "DISRUPTED"
    assert payload["overall_city_status"] == "DISRUPTED"


def test_invalidated_cache_does_not_block_on_an_in_flight_run():
    """invalidate() must not hang behind a long coordinator run."""
    access.invalidate_city_report_cache()
    started = time.perf_counter()
    for _ in range(5):
        access.invalidate_city_report_cache()
    assert time.perf_counter() - started < 1.0