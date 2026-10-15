"""Phase 3 integration: the Overview city endpoint and the narrative service.

Verifies that the ``ai_brief`` field is grounded in the deterministic
coordinator report, that it degrades safely when the LLM cannot be used, and
that the coordinator-owned fields are returned unchanged alongside it.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from backend.app.ai.narrative import build_narrative_input, deterministic_summary
from backend.app.coordinator.city_report import CitySituationReport
from backend.app.intelligence.contracts import validate_report


def _report() -> CitySituationReport:
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


class _FakeService:
    """Stands in for UrbanOSAIService without touching the network."""

    def __init__(self, narrative, available=True):
        self._narrative = narrative
        self._available = available
        self.calls = 0

    def is_available(self):
        return self._available

    async def generate_city_narrative(self, report):
        self.calls += 1
        if self._narrative is None:
            from backend.app.ai.narrative import NarrativeValidation
            return None, NarrativeValidation(ok=False, reasons=["stubbed"])
        return self._narrative, type("V", (), {"ok": True, "reasons": []})()


@pytest.mark.asyncio
async def test_narrative_used_when_available():
    from backend.app.overview.api import _narrative_or_fallback
    svc = _FakeService("Grounded narrative.")
    out = await _narrative_or_fallback(svc, _report())
    assert out == "Grounded narrative."
    assert svc.calls == 1


@pytest.mark.asyncio
async def test_falls_back_to_deterministic_summary_when_llm_unavailable():
    from backend.app.overview.api import _narrative_or_fallback
    svc = _FakeService("never used", available=False)
    out = await _narrative_or_fallback(svc, _report())
    assert svc.calls == 0
    assert out == deterministic_summary(_report())
    assert "DISRUPTED" in out


@pytest.mark.asyncio
async def test_falls_back_when_output_is_rejected():
    from backend.app.overview.api import _narrative_or_fallback
    svc = _FakeService(None)
    out = await _narrative_or_fallback(svc, _report())
    assert out == deterministic_summary(_report())


@pytest.mark.asyncio
async def test_falls_back_when_service_raises():
    from backend.app.overview.api import _narrative_or_fallback

    class _Boom:
        def is_available(self):
            return True

        async def generate_city_narrative(self, report):
            raise RuntimeError("provider exploded")

    out = await _narrative_or_fallback(_Boom(), _report())
    assert out == deterministic_summary(_report())


@pytest.mark.asyncio
async def test_falls_back_on_timeout():
    from backend.app.overview.api import _narrative_or_fallback

    class _Slow:
        """Plain method: wait_for is mocked, so no coroutine is ever created."""

        def is_available(self):
            return True

        def generate_city_narrative(self, report):
            return None

    with patch("backend.app.overview.api.asyncio.wait_for",
               side_effect=asyncio.TimeoutError):
        out = await _narrative_or_fallback(_Slow(), _report())
    assert out == deterministic_summary(_report())


def test_city_report_payload_satisfies_the_shared_contract():
    assert validate_report(_report()) == []


def test_narrative_input_reflects_unavailable_domains():
    ni = build_narrative_input(_report())
    assert ni.unavailable_domains == ["fire"]
    assert ni.overall_city_status == "DISRUPTED"


# ------------------------------------------------------------ API contract
def test_overview_city_response_still_contains_all_phase1_fields():
    """Phase 3 must not remove anything Phase 1 added."""
    from backend.app.overview.api import CityOverviewResponse
    fields = set(CityOverviewResponse.model_fields)
    for required in ("generated_at", "modules", "alerts", "ai_brief", "domain_status"):
        assert required in fields, required
    assert CityOverviewResponse.model_fields["ai_brief"].default is None


def test_ai_brief_is_optional_so_degradation_is_representable():
    from backend.app.overview.api import CityOverviewResponse
    r = CityOverviewResponse(generated_at="x", modules=[], alerts=[])
    assert r.ai_brief is None


# ------------------------------------------------------- shared cache wiring
def test_overview_and_city_routes_share_one_coordinator_cache():
    from backend.app.coordinator import access
    src = open(access.__file__, encoding="utf-8").read()
    assert "threading.Lock()" in src
    assert "CITY_REPORT_CACHE_TTL_S" in src
    # main.py and overview/api.py both use this one accessor.
    main_src = open(
        r"C:\projects\UrbanOS\backend\app\main.py", encoding="utf-8").read()
    ov_src = open(
        r"C:\projects\UrbanOS\backend\app\overview\api.py", encoding="utf-8").read()
    assert "city_report_cached" in main_src
    assert "city_report_cached" in ov_src
    assert "_city_report_lock" not in main_src, "cache must have a single owner"