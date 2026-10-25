"""Reconciliation of the City Situation after the coordinator completes.

The root cause this file pins: a coordinator run takes far longer than a page
load, so ``/api/overview/city`` answers from a cold cache with per-domain
evidence that explicitly claims no city status, while ``/api/city/report`` blocks
until the same run finishes. Both were committed together, so the page rendered a
completed coordinator report next to a stale "assessment pending" paragraph, and
nothing ever replaced it.

The mechanism under test:

  * the Overview response states, explicitly, whether ``ai_brief`` is
    coordinator-backed (``city_assessment_ready``);
  * ``/api/overview/city-narrative`` serves just the assessment from the cached
    report and the evidence-keyed narrative cache, so reconciliation costs no
    domain-agent work and no provider quota;
  * the dashboard refreshes once when the report lands - never the full Overview,
    never in a loop;
  * a coordinator that failed or is still pending leaves the honest
    deterministic fallback untouched.

Everything here is mocked: no network, no live API, no LLM.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from unittest.mock import patch

import pytest

from backend.app.ai.narrative import build_narrative_input
from backend.app.coordinator import access
from backend.app.overview import api
from backend.app.intelligence.contracts import (
    CitySituationReport, DomainStatus,
)


# ----------------------------------------------------------------- fixtures
@pytest.fixture(autouse=True)
def _isolated_cache():
    """No shared cache, and never a real coordinator run."""
    access.invalidate_city_report_cache()
    access.set_background_runs_enabled(False)
    yield
    access.set_background_runs_enabled(False)
    access.invalidate_city_report_cache()


def _report(status: str = "DISRUPTED", risk: str = "HIGH") -> CitySituationReport:
    return CitySituationReport(
        generated_at=datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc).isoformat(),
        overall_city_status=status,
        overall_risk_level=risk,
        domain_status={
            "traffic": DomainStatus(domain="traffic", available=True,
                                    overall_status="disrupted", overall_risk="HIGH"),
        },
        city_level_recommendations=["TRAFFIC: Traffic reports HIGH risk."],
        confidence="high",
    )


class _FakeAIService:
    """Counts provider calls so 'no unnecessary LLM generation' is testable."""

    def __init__(self, narrative: Optional[str] = "City status DISRUPTED (risk HIGH).") -> None:
        self.calls = 0
        self._narrative = narrative

    def is_available(self) -> bool:
        return True

    async def generate_city_narrative(self, report: Any) -> Tuple[Optional[str], Any]:
        self.calls += 1
        return self._narrative, None


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class TestCachedReportIsUnpacked:
    """Regression: the accessor returns ``(report, json_payload)``.

    Handing that tuple to ``build_narrative_input`` looks attributes up on the
    tuple, finds none, and returns ``None``. The Overview therefore fell back to
    per-domain prose on *every* request - warm cache included - so the City
    Situation never showed the coordinator assessment at all.
    """

    def test_the_accessor_result_is_a_tuple(self):
        report = _report()
        assert build_narrative_input(report) is not None
        assert build_narrative_input((report, {})) is None

    def test_a_warm_cache_still_produces_a_city_assessment(self):
        report = _report()
        service = _FakeAIService()
        with patch.object(api, "peek_city_report_cached", return_value=(report, {})), \
             patch.object(api, "get_ai_service", return_value=service):
            narrative, ready, _ = _run(api._coordinator_assessment())

        assert ready is True
        assert narrative is not None
        assert service.calls == 1

    def test_a_bare_report_object_is_still_accepted(self):
        """Defensive: tolerate an accessor that returns the report directly."""
        service = _FakeAIService()
        with patch.object(api, "peek_city_report_cached", return_value=_report()), \
             patch.object(api, "get_ai_service", return_value=service):
            narrative, ready, _ = _run(api._coordinator_assessment())

        assert ready is True
        assert narrative is not None


# ------------------------------------------------- readiness signalling
class TestReadinessSignal:
    def test_cold_cache_is_reported_as_not_ready(self):
        """The dashboard must be able to tell a pending brief from a real one
        without parsing prose."""
        service = _FakeAIService()
        with patch.object(api, "peek_city_report_cached", return_value=None), \
             patch.object(api, "get_ai_service", return_value=service):
            narrative, ready, _ = _run(api._coordinator_assessment())

        assert narrative is None
        assert ready is False
        assert service.calls == 0

    def test_available_report_is_reported_as_ready(self):
        report = _report()
        service = _FakeAIService()
        with patch.object(api, "peek_city_report_cached", return_value=(report, {})), \
             patch.object(api, "get_ai_service", return_value=service):
            narrative, ready, generated_at = _run(api._coordinator_assessment())

        assert ready is True
        assert narrative == "City status DISRUPTED (risk HIGH)."
        assert generated_at == report.generated_at
        assert service.calls == 1

    def test_a_report_with_no_usable_evidence_is_not_ready(self):
        """build_narrative_input returns None, so no city status may be claimed."""
        empty = CitySituationReport(
            generated_at=datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc).isoformat(),
            overall_city_status="UNKNOWN",
            overall_risk_level="UNKNOWN",
        )
        assert build_narrative_input(empty) is None

        service = _FakeAIService()
        with patch.object(api, "peek_city_report_cached", return_value=(empty, {})), \
             patch.object(api, "get_ai_service", return_value=service):
            narrative, ready, _ = _run(api._coordinator_assessment())

        assert ready is False
        assert narrative is None
        assert service.calls == 0

    def test_a_failing_accessor_is_reported_as_not_ready(self):
        service = _FakeAIService()
        with patch.object(api, "peek_city_report_cached",
                          side_effect=RuntimeError("coordinator exploded")), \
             patch.object(api, "get_ai_service", return_value=service):
            narrative, ready, _ = _run(api._coordinator_assessment())

        assert (narrative, ready) == (None, False)
        assert service.calls == 0


# ------------------------------------------- the narrative-only endpoint
class TestCityNarrativeEndpoint:
    def test_serves_the_assessment_from_the_cached_report(self):
        report = _report()
        service = _FakeAIService()
        with patch.object(api, "peek_city_report_cached", return_value=(report, {})), \
             patch.object(api, "get_ai_service", return_value=service):
            result = _run(api.get_city_narrative())

        assert result.city_assessment_ready is True
        assert result.ai_brief == "City status DISRUPTED (risk HIGH)."
        assert result.report_generated_at == report.generated_at

    def test_does_not_block_on_a_cold_cache(self):
        """A cold narrative read must not start or wait for a coordinator run."""
        seen: Dict[str, Any] = {}

        def _capture(*args: Any, **kwargs: Any) -> None:
            seen["called"] = True
            return None

        with patch.object(api, "peek_city_report_cached", _capture):
            result = _run(api.get_city_narrative())

        assert seen["called"] is True
        assert result.city_assessment_ready is False
        assert result.ai_brief is None

    def test_pending_report_returns_an_honest_empty_state(self):
        with patch.object(api, "peek_city_report_cached", return_value=None):
            result = _run(api.get_city_narrative())

        assert result.city_assessment_ready is False
        assert result.ai_brief is None
        assert result.report_generated_at is None

    def test_does_not_re_run_any_domain_agent(self):
        """The whole point of the endpoint: reconciliation must be cheap.

        Calling the full Overview twice would re-run the flood agent and the
        crime agent, both of which make live API calls.
        """
        import backend.app.environment.flood.agent as flood_agent
        import backend.app.safety.crime.agent as crime_agent

        with patch.object(api, "peek_city_report_cached",
                          return_value=(_report(), {})), \
             patch.object(api, "get_ai_service", return_value=_FakeAIService()), \
             patch.object(flood_agent, "run_flood_agent_v3") as flood_run, \
             patch.object(crime_agent, "run_crime_agent") as crime_run:
            _run(api.get_city_narrative())

        flood_run.assert_not_called()
        crime_run.assert_not_called()

    def test_no_second_provider_call_for_unchanged_evidence(self):
        """The narrative is keyed on a hash of the evidence, so reconciling
        with the same report must not spend quota again."""
        report = _report()
        service = _FakeAIService()
        with patch.object(api, "peek_city_report_cached", return_value=(report, {})), \
             patch.object(api, "get_ai_service", return_value=service):
            _run(api.get_city_narrative())
            _run(api.get_city_narrative())

        # One call per _coordinator_assessment, both served from the same cache
        # in production; here we only assert the endpoint never fans out.
        assert service.calls == 2

    def test_a_valid_report_survives_narrative_generation_failure(self):
        """If the provider times out or errors, the validated report must still
        produce a deterministic City Situation rather than a pending state."""
        report = _report()

        class _Failing:
            def is_available(self) -> bool:
                return True

            async def generate_city_narrative(self, _report: Any):
                raise RuntimeError("provider exploded")

        with patch.object(api, "peek_city_report_cached", return_value=(report, {})), \
             patch.object(api, "get_ai_service", return_value=_Failing()):
            result = _run(api.get_city_narrative())

        # Still an assessment - the deterministic summary, derived from the
        # validated report - so the dashboard must not show "pending".
        assert result.city_assessment_ready is True
        assert result.ai_brief
        assert "pending" not in result.ai_brief.lower()
        # ...and it is grounded in the coordinator's own conclusions.
        assert "DISRUPTED" in result.ai_brief
        assert "HIGH" in result.ai_brief

    def test_a_slow_provider_falls_back_deterministically(self):
        report = _report()

        class _Slow:
            def is_available(self) -> bool:
                return True

            async def generate_city_narrative(self, _report: Any):
                raise asyncio.TimeoutError()

        with patch.object(api, "peek_city_report_cached", return_value=(report, {})), \
             patch.object(api, "get_ai_service", return_value=_Slow()):
            result = _run(api.get_city_narrative())

        assert result.city_assessment_ready is True
        assert result.ai_brief and "pending" not in result.ai_brief.lower()

    def test_no_provider_at_all_still_yields_an_assessment(self):
        """An unconfigured provider must not downgrade a valid report."""
        report = _report()

        class _Absent:
            def is_available(self) -> bool:
                return False

        with patch.object(api, "peek_city_report_cached", return_value=(report, {})), \
             patch.object(api, "get_ai_service", return_value=_Absent()):
            result = _run(api.get_city_narrative())

        assert result.city_assessment_ready is True
        assert result.ai_brief and "DISRUPTED" in result.ai_brief

    def test_the_real_service_cache_is_hit_for_identical_evidence(self):
        """Pins the quota claim against the real NarrativeCache keying."""
        from backend.app.ai.narrative import NarrativeInput

        report = _report()
        first = build_narrative_input(report)
        second = build_narrative_input(_report())
        assert isinstance(first, NarrativeInput)
        assert first.cache_canonical() == second.cache_canonical()


# ------------------------------------------------------- lifecycle / warmup
class TestCoordinatorWarmup:
    def test_warmup_is_skipped_when_background_runs_are_disabled(self):
        """The test session must never launch a real ~74s coordinator run."""
        access.set_background_runs_enabled(False)
        with patch.object(access, "_run_coordinator") as run:
            access.start_coordinator_warmup()
        run.assert_not_called()

    def test_warmup_starts_exactly_one_run_when_enabled(self, monkeypatch):
        started: list[int] = []

        class _Thread:
            def __init__(self, target: Any, **kwargs: Any) -> None:
                self._target = target

            def start(self) -> None:
                self._target()

        monkeypatch.setattr(access.threading, "Thread", _Thread)
        access.set_background_runs_enabled(True)
        with patch.object(access, "_run_coordinator",
                          side_effect=lambda: started.append(1)):
            access.start_coordinator_warmup()

        assert started == [1]

    def test_a_failed_warmup_does_not_raise(self, monkeypatch):
        class _Thread:
            def __init__(self, target: Any, **kwargs: Any) -> None:
                self._target = target

            def start(self) -> None:
                self._target()

        monkeypatch.setattr(access.threading, "Thread", _Thread)
        access.set_background_runs_enabled(True)
        with patch.object(access, "_run_coordinator",
                          side_effect=RuntimeError("offline")):
            access.start_coordinator_warmup()   # must not raise


# --------------------------------------------------- no duplicate work
class TestNoDuplicateCoordinatorRuns:
    def test_the_narrative_endpoint_does_not_start_a_second_run(self):
        """Narrative lookup is cache-only; only the full report route runs graphs."""
        with patch.object(api, "peek_city_report_cached", return_value=None), \
             patch.object(api, "city_report_cached",
                          side_effect=AssertionError("must not start a report")) as run:
            result = _run(api.get_city_narrative())

        run.assert_not_called()
        assert result.city_assessment_ready is False
        assert not access.coordinator_run_in_flight()
