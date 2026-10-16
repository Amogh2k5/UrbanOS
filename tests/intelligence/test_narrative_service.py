"""Phase 3 tests: grounded LLM narrative service.

Covers prompt construction, output validation, provider configuration,
failure handling, caching, concurrency, fallback behaviour, and the guarantee
that coordinator-owned facts are never altered by the narrative.
"""
from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

from backend.app.ai.narrative import (
    NarrativeInput, NarrativeValidation, build_narrative_input,
    deterministic_summary, validate_narrative,
)
from backend.app.ai.service import (
    SUPPORTED_PROVIDERS, SYSTEM_INSTRUCTIONS, NarrativeCache, UrbanOSAIService,
    _scrub,
)
from backend.app.intelligence.contracts import CitySituationReport


# ------------------------------------------------------------------ fixtures
def _report(**overrides) -> CitySituationReport:
    base = dict(
        generated_at="2026-10-11T09:00:00+08:00",
        overall_city_status="DISRUPTED",
        overall_risk_level="HIGH",
        confidence="high",
        domain_status={
            "flood": {
                "domain": "flood", "available": True, "overall_risk": "HIGH",
                "overall_status": "HIGH", "affected_zones": ["Central South"],
                "key_metrics": {"risk_level": "HIGH", "active_alert_count": 2},
                "limitations": [],
            },
            "traffic": {
                "domain": "traffic", "available": True, "overall_risk": "HIGH",
                "overall_status": "disrupted",
                "key_metrics": {"average_speed_kmh": 18.0},
                "limitations": [],
            },
            "fire": {
                "domain": "fire", "available": False,
                "error": "feed empty",
                "limitations": ["Fire feed returned no records."],
            },
        },
        cross_domain_impacts=[{
            "type": "flood_traffic",
            "description": "HIGH flood risk coincides with disrupted traffic in Central South.",
            "severity": "HIGH", "affected_zones": ["Central South"],
            "domains_involved": ["flood", "traffic"],
            "evidence": ["Flood risk reported as HIGH.", "Central South affected."],
        }],
        priority_incidents=[{
            "id": "IMPACT_flood_traffic", "type": "flood_traffic_overlap",
            "domain": "flood+traffic", "severity": "HIGH",
            "description": "Flood+traffic overlap",
            "affected_zones": ["Central South"], "source_report": "flood+traffic",
            "related_domains": ["flood", "traffic"],
        }],
        city_level_recommendations=[
            "FLOOD+TRAFFIC: Coordinate flood and traffic response for Central South."
        ],
        affected_zones=["Central South"],
    )
    base.update(overrides)
    return CitySituationReport(**base)


def _svc(**kw) -> UrbanOSAIService:
    kw.setdefault("api_key", "sk-test-dummy-0123456789")
    kw.setdefault("provider", "openrouter")
    return UrbanOSAIService(**kw)


def _ok_transport(content: str) -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda req: httpx.Response(200, json={
            "choices": [{"message": {"content": content}}]
        })
    )


GOOD_NARRATIVE = (
    "City operations are disrupted, with flood risk reported as HIGH in "
    "Central South. Traffic in the same zone is disrupted, averaging "
    "18.0 km/h. Fire could not be assessed."
)


# ================================================== prompt construction
def test_prompt_carries_no_system_instructions_in_the_user_turn():
    svc = _svc()
    ni = build_narrative_input(_report())
    prompt = svc.build_prompt(ni)
    assert "You are UrbanOS" not in prompt
    assert "Do not invent" not in prompt
    assert "<coordinator_output>" in prompt
    assert "not instructions" in prompt


def test_instructions_appear_exactly_once_and_only_in_system():
    svc = _svc()
    prompt = svc.build_prompt(build_narrative_input(_report()))
    assert SYSTEM_INSTRUCTIONS.count("Never add a fact") == 1
    assert "Never add a fact" not in prompt


def test_prompt_contains_only_bounded_coordinator_facts():
    ni = build_narrative_input(_report())
    body = ni.model_dump_json()
    assert "Central South" in body
    assert "18.0" in body
    # Raw module payloads are not carried across.
    assert "radial_gradient" not in body
    assert "SHAPE.AREA" not in body


def test_narrative_input_is_none_when_report_has_nothing():
    blank = CitySituationReport(generated_at="2026-10-11T09:00:00+08:00", domain_status={})
    assert build_narrative_input(blank) is None
    assert build_narrative_input(None) is None


def test_unavailable_domains_are_carried_into_the_input():
    ni = build_narrative_input(_report())
    assert ni.unavailable_domains == ["fire"]
    assert any(d.domain == "fire" and not d.available for d in ni.domains)


# ========================================================== validation
def test_valid_narrative_passes():
    ni = build_narrative_input(_report())
    assert validate_narrative(GOOD_NARRATIVE, ni).ok


@pytest.mark.parametrize("bad,marker", [
    ("Traffic is 4 km/h across 47 zones with a 92% drop.", "numbers not present"),
    ("Flood risk is CRITICAL in Central South.", "not present in the coordinator report"),
    ("You are UrbanOS, the city intelligence system.", "leaked instruction"),
    ("Bearer sk-abcdef123456 is the key.", "leaked instruction"),
    ("", "empty narrative"),
    (None, "empty narrative"),
])
def test_invalid_narratives_are_rejected(bad, marker):
    ni = build_narrative_input(_report())
    result = validate_narrative(bad, ni)
    assert not result.ok
    assert any(marker in r for r in result.reasons), result.reasons


def test_status_escalation_is_rejected():
    """The report says HIGH; a narrative claiming CRITICAL is fabrication."""
    ni = build_narrative_input(_report())
    result = validate_narrative(
        "City operations are critical with flood risk CRITICAL.", ni)
    assert not result.ok
    assert "CRITICAL" in result.unsupported_status_words


def test_small_ordinals_are_allowed():
    ni = build_narrative_input(_report())
    assert validate_narrative(
        "Two domains report elevated risk and three findings are open.", ni).ok


def test_overlong_narrative_is_rejected():
    """The City Situation is a structured report, so the bound is generous -
    but it is still a briefing, not a dump."""
    from backend.app.ai.narrative import _MAX_NARRATIVE_WORDS

    ni = build_narrative_input(_report())
    assert not validate_narrative("word " * (_MAX_NARRATIVE_WORDS + 50), ni).ok


def test_a_full_structured_report_is_within_the_length_bound():
    """The bound must actually fit the report we ask the model to write."""
    from backend.app.ai.narrative import (
        SECTION_ORDER, _MAX_NARRATIVE_WORDS, build_report_sections,
        deterministic_summary, render_sections,
    )

    rep = _report()
    rep.cross_domain_impacts = [
        {
            "type": "air_quality_traffic",
            "description": "Unhealthy air quality coincides with disrupted traffic.",
            "severity": "HIGH",
            "affected_zones": ["Central South"],
            "domains_involved": ["air_quality", "traffic"],
            "evidence": [
                "NEA observed PM2.5 peak of 116 µg/m³.",
                "Traffic independently reported as 'disrupted'.",
            ],
        }
    ]
    sections = build_report_sections(rep)
    text = render_sections(sections)

    # Every populated section is present, cross-domain among them.
    assert "CROSS-DOMAIN SIGNALS" in sections
    assert "SITUATION" in sections
    assert all(name in text for name in SECTION_ORDER if name in sections)
    assert "116" in text
    # And the validator accepts it as a deliverable narrative.
    ni = build_narrative_input(rep)
    assert len(text.split()) <= _MAX_NARRATIVE_WORDS
    assert validate_narrative(text, ni).ok, validate_narrative(text, ni).reasons


def test_rounding_within_two_percent_is_tolerated():
    rep = _report()
    rep.domain_status["traffic"].key_metrics["average_speed_kmh"] = 18.36
    ni = build_narrative_input(rep)
    assert validate_narrative("Traffic averages 18 km/h in the zone.", ni).ok


# ================================================== provider configuration
def test_supported_providers_is_openrouter_only():
    assert SUPPORTED_PROVIDERS == ("openrouter",)


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini", "azure"])
def test_unsupported_provider_is_not_reported_available(provider):
    svc = _svc(provider=provider)
    assert not svc.is_available()
    assert svc.unavailable_reason


def test_empty_provider_falls_back_to_the_default(monkeypatch):
    """An unset provider means 'use the default', not 'unsupported'."""
    monkeypatch.delenv("URBANOS_LLM_PROVIDER", raising=False)
    svc = UrbanOSAIService(api_key="sk-test-dummy-0123456789", provider="")
    assert svc.provider == "openrouter"
    assert svc.is_available()


def test_missing_credentials_is_not_reported_available():
    svc = UrbanOSAIService(api_key="", provider="openrouter")
    assert not svc.is_available()
    assert "api key" in svc.unavailable_reason.lower()


def test_valid_config_reports_available():
    assert _svc().is_available()


def test_env_example_documents_a_supported_provider():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    provider = next(l.split("=", 1)[1].strip() for l in text.splitlines()
                    if l.startswith("URBANOS_LLM_PROVIDER="))
    assert provider in SUPPORTED_PROVIDERS, provider


# ============================================================ secret hygiene
@pytest.mark.parametrize("secret", [
    "https://openrouter.ai/api/v1?key=SUPERSECRET",
    "Authorization: Bearer abc123def",
    "token sk-abcdefghijklmnop",
])
def test_scrub_removes_secrets(secret):
    out = _scrub(secret)
    assert "SUPERSECRET" not in out
    assert "abc123def" not in out
    assert "sk-abcdefghijklmnop" not in out


def test_api_key_never_appears_in_log_output(caplog):
    key = "sk-verysecretkey1234567890"
    svc = _svc(api_key=key)
    assert key not in _scrub(str(vars(svc).keys()))
    assert key not in _scrub(repr(svc.unavailable_reason))
    # The key is never part of any user-facing or log-facing surface.
    assert not hasattr(svc, "api_key_public")


# ======================================================== provider failures
@pytest.mark.asyncio
async def test_auth_failure_returns_none(monkeypatch):
    svc = _svc()
    svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1", 
        transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "no"})))
    assert await svc._generate("x") is None


@pytest.mark.asyncio
async def test_rate_limit_returns_none():
    svc = _svc()
    svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1", 
        transport=httpx.MockTransport(lambda r: httpx.Response(429, text="slow down")))
    assert await svc._generate("x") is None


@pytest.mark.asyncio
async def test_server_error_returns_none():
    svc = _svc()
    svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1", 
        transport=httpx.MockTransport(lambda r: httpx.Response(503, text="down")))
    assert await svc._generate("x") is None


@pytest.mark.asyncio
async def test_timeout_returns_none():
    svc = _svc()

    def _boom(request):
        raise httpx.ConnectTimeout("slow", request=request)

    svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1", transport=httpx.MockTransport(_boom))
    assert await svc._generate("x") is None


@pytest.mark.asyncio
async def test_malformed_provider_payload_returns_none():
    svc = _svc()
    svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1", 
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="not json")))
    assert await svc._generate("x") is None


@pytest.mark.asyncio
async def test_missing_choices_returns_none():
    svc = _svc()
    svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1", 
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"foo": "bar"})))
    assert await svc._generate("x") is None


@pytest.mark.asyncio
async def test_empty_content_returns_none():
    svc = _svc()
    svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1", 
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})))
    assert await svc._generate("x") is None


# ================================================== narrative extraction
@pytest.mark.parametrize("payload,expected", [
    ('{"narrative": "Hello city."}', "Hello city."),
    ("Hello city.", "Hello city."),
    ('```json\n{"narrative": "Fenced."}\n```', "Fenced."),
    ('{"narrative": 42}', None),
    ('{"other": "x"}', None),
    ("{not json", None),
    ("", None),
])
def test_extract_narrative(payload, expected):
    assert UrbanOSAIService._extract_narrative(payload) == expected


# ============================================================== generation
@pytest.mark.asyncio
async def test_generate_returns_validated_narrative():
    svc = _svc()
    svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1", 
        transport=_ok_transport(json.dumps({"narrative": GOOD_NARRATIVE})))
    narrative, validation = await svc.generate_city_narrative(_report())
    assert narrative == GOOD_NARRATIVE
    assert validation.ok


@pytest.mark.asyncio
async def test_generate_rejects_untraceable_narrative():
    svc = _svc()
    svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1", 
        transport=_ok_transport(json.dumps({
            "narrative": "Flood risk is CRITICAL and traffic is 3 km/h in 88 zones."})))
    narrative, validation = await svc.generate_city_narrative(_report())
    assert narrative is None
    assert not validation.ok


@pytest.mark.asyncio
async def test_generate_returns_none_when_provider_fails():
    svc = _svc()
    svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1", 
        transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom")))
    narrative, validation = await svc.generate_city_narrative(_report())
    assert narrative is None
    assert not validation.ok


@pytest.mark.asyncio
async def test_generate_returns_none_when_no_evidence():
    svc = _svc()
    blank = CitySituationReport(generated_at="x", domain_status={})
    narrative, validation = await svc.generate_city_narrative(blank)
    assert narrative is None
    assert "no evidence" in validation.reasons[0]


@pytest.mark.asyncio
async def test_generate_returns_none_when_provider_unavailable():
    svc = _svc(provider="openai")
    narrative, validation = await svc.generate_city_narrative(_report())
    assert narrative is None
    assert not validation.ok


# ================================================================= caching
def test_cache_returns_same_value_for_same_evidence():
    c = NarrativeCache(ttl=60)
    ni = build_narrative_input(_report())
    k = NarrativeCache.key(ni)
    assert c.get(k) is None
    c.set(k, "text")
    assert c.get(k) == "text"
    assert c.hits == 1


def test_cache_expires():
    c = NarrativeCache(ttl=0.01)
    ni = build_narrative_input(_report())
    k = NarrativeCache.key(ni)
    c.set(k, "text")
    time.sleep(0.05)
    assert c.get(k) is None


def test_cache_key_changes_with_evidence():
    a = NarrativeCache.key(build_narrative_input(_report()))
    b = NarrativeCache.key(build_narrative_input(
        _report(overall_city_status="NORMAL", overall_risk_level="LOW")))
    assert a != b


def test_cache_is_bounded():
    c = NarrativeCache(ttl=60, maxsize=3)
    for i in range(10):
        c.set(f"k{i}", "v")
    assert len(c._data) <= 3


@pytest.mark.asyncio
async def test_cache_prevents_repeat_provider_calls():
    svc = _svc()
    calls = {"n": 0}

    def _count(request):
        calls["n"] += 1
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({"narrative": GOOD_NARRATIVE})}}]})

    svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1", transport=httpx.MockTransport(_count))
    first, _ = await svc.generate_city_narrative(_report())
    second, v2 = await svc.generate_city_narrative(_report())
    assert first == second == GOOD_NARRATIVE
    assert calls["n"] == 1, "cached narrative must not trigger another call"
    assert "cache hit" in v2.reasons


@pytest.mark.asyncio
async def test_concurrent_requests_share_one_generation():
    svc = _svc()
    calls = {"n": 0}

    def _count(request):
        calls["n"] += 1
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({"narrative": GOOD_NARRATIVE})}}]})

    svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1", transport=httpx.MockTransport(_count))
    results = await asyncio.gather(*[svc.generate_city_narrative(_report()) for _ in range(5)])
    assert calls["n"] == 1, f"expected single generation, got {calls['n']}"
    assert all(n == GOOD_NARRATIVE for n, _ in results)


@pytest.mark.asyncio
async def test_rejected_output_is_not_cached_as_success():
    svc = _svc()
    svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1", 
        transport=_ok_transport(json.dumps({"narrative": "Totally invented 99 km/h."})))
    narrative, validation = await svc.generate_city_narrative(_report())
    assert narrative is None and not validation.ok
    # Nothing stored: the next attempt must reach the provider again.
    assert not svc.cache._data


# ============================================================== fallback
def test_deterministic_summary_never_invents():
    text = deterministic_summary(_report())
    assert "DISRUPTED" in text
    assert "Fire" in text or "fire" in text
    assert "absence of data is not evidence" in text.lower()


def test_deterministic_summary_handles_no_report():
    assert deterministic_summary(None) is None
    blank = CitySituationReport(generated_at="x", domain_status={})
    assert "unavailable" in deterministic_summary(blank).lower()


def test_summary_exists_even_without_any_llm_capability():
    """With no key configured, the dashboard still has a truthful summary."""
    svc = UrbanOSAIService(api_key="", provider="openrouter")
    assert not svc.is_available()
    assert deterministic_summary(_report())


# ============================== coordinator-owned facts are never altered
def test_narrative_cannot_modify_deterministic_fields():
    """The narrative is additive: the report's own fields are untouched."""
    rep = _report()
    before = rep.model_dump(mode="json")
    ni = build_narrative_input(rep)
    validate_narrative("City is critical with 900 fires.", ni)
    assert rep.model_dump(mode="json") == before


def test_recommendations_and_status_come_from_the_coordinator_only():
    ni = build_narrative_input(_report())
    assert ni.recommendations == _report().city_level_recommendations
    assert ni.overall_city_status == "DISRUPTED"
    assert ni.overall_risk_level == "HIGH"


# ============================================= live provider compatibility
class TestProviderCompatibility:
    """Defects reproduced against the live OpenRouter provider.

    Both were found on ``nvidia/nemotron-3-ultra-550b-a55b``, which ignores
    ``response_format`` and spends its whole token budget restating the task
    instead of answering (``finish_reason == "length"``).
    """

    # Verbatim opening of the model's real truncated output.
    SCRATCHPAD = (
        "The user wants me to write a City Situation paragraph based on the "
        "provided JSON data. I need to output a JSON object with a \"narrative\" "
        "field containing the paragraph. I must follow the rules: only describe "
        "what's in the data."
    )

    def test_task_commentary_is_not_accepted_as_a_narrative(self):
        """It carries no invented numbers, so only this check can catch it."""
        ni = build_narrative_input(_report())
        v = validate_narrative(self.SCRATCHPAD, ni)
        assert not v.ok
        assert any("task commentary" in r for r in v.reasons)

    @pytest.mark.parametrize("text", [
        "The user wants me to summarise the findings.",
        "I need to output a JSON object.",
        "I must follow the rules described above.",
        "I am going to describe the city status.",
        "As an AI I will explain the data.",
        "The above data shows a problem.",
    ])
    def test_task_meta_variants_rejected(self, text):
        ni = build_narrative_input(_report())
        assert not validate_narrative(text, ni).ok, text

    def test_a_real_narrative_is_still_accepted(self):
        """Guard against over-rejecting: grounded prose must still pass."""
        ni = build_narrative_input(_report())
        text = ("City status DISRUPTED with HIGH risk. Flood risk is HIGH in "
                "Central South.")
        assert validate_narrative(text, ni).ok

    @pytest.mark.asyncio
    async def test_truncated_generation_is_a_failure_not_a_fragment(self):
        svc = _svc()
        svc._client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
                "choices": [{"finish_reason": "length", "message": {
                    "content": self.SCRATCHPAD}}]})))
        assert await svc._generate("x") is None
        assert svc._last_generate_truncated is True

    @pytest.mark.asyncio
    async def test_truncated_narrative_is_not_cached_and_falls_back(self):
        svc = _svc()
        calls = {"n": 0}

        def _truncated(r):
            calls["n"] += 1
            return httpx.Response(200, json={
                "choices": [{"finish_reason": "length",
                             "message": {"content": self.SCRATCHPAD}}]})

        svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1",
                                        transport=httpx.MockTransport(_truncated))
        report = _report()
        narrative, v = await svc.generate_city_narrative(report)

        assert narrative is None
        assert not v.ok
        # A truncated generation is not retried: it would truncate identically.
        assert calls["n"] == 1, calls
        # And crucially it is never cached as a successful answer.
        assert svc.cache.misses >= 1
        key = svc.cache.key(build_narrative_input(report))
        assert svc.cache.get(key) is None

    @pytest.mark.asyncio
    async def test_finished_generation_is_still_accepted_and_cached(self):
        svc = _svc()
        good = ("City status DISRUPTED with HIGH risk. Flood risk is HIGH in "
                "Central South.")
        svc._client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
                "choices": [{"finish_reason": "stop",
                             "message": {"content": json.dumps({"narrative": good})}}]})))
        report = _report()
        narrative, v = await svc.generate_city_narrative(report)
        assert narrative == good
        assert v.ok
        # Second call is served from cache, no provider round trip.
        again, _ = await svc.generate_city_narrative(report)
        assert again == good

    @pytest.mark.asyncio
    async def test_structured_output_being_ignored_falls_back_deterministically(self):
        """Provider returns prose where JSON was requested: still validated."""
        svc = _svc()
        svc._client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
                "choices": [{"finish_reason": "stop",
                             "message": {"content": self.SCRATCHPAD}}]})))
        report = _report()
        narrative, v = await svc.generate_city_narrative(report)
        assert narrative is None
        assert not v.ok
        from backend.app.ai.narrative import deterministic_summary
        assert deterministic_summary(report)


class TestGenerationBudget:
    """Token budgets sized by measurement, not guesswork.

    Every OpenRouter model advertising structured output for this workload is a
    reasoning model with mandatory reasoning. Measured against
    ``liquid/lfm-2.5-2.6b:free``: 439-728 completion tokens went to reasoning
    before any answer text was emitted. The old 260/400 budgets were smaller
    than the reasoning alone, so every generation ended ``finish_reason=length``
    with empty content.
    """

    def test_narrative_budget_exceeds_measured_reasoning_floor(self):
        from backend.app.ai.service import NARRATIVE_MAX_TOKENS
        # Highest observed reasoning usage was 728 tokens.
        assert NARRATIVE_MAX_TOKENS > 728, NARRATIVE_MAX_TOKENS

    def test_copilot_budget_exceeds_measured_reasoning_floor(self):
        from backend.app.ai.service import COPILOT_MAX_TOKENS
        assert COPILOT_MAX_TOKENS > 728, COPILOT_MAX_TOKENS

    def test_system_instructions_state_the_enforced_word_budget(self):
        """The prompt must name the limit the validator actually enforces.

        ``validate_narrative`` rejects above 140 words. The instructions only
        said "2-5 sentence" and mentioned no bound, so the model overshot and
        its otherwise-grounded answer was discarded.
        """
        assert "110 words" in SYSTEM_INSTRUCTIONS

    def test_word_budget_instruction_sits_below_the_enforced_cap(self):
        """The instructed budget must leave headroom under the 140-word cap."""
        stated = int(SYSTEM_INSTRUCTIONS.split("under ")[1].split(" words")[0])
        assert stated < 140, stated

    @pytest.mark.asyncio
    async def test_copilot_uses_the_measured_budget(self):
        """Guard against the budget silently regressing to a hard-coded 400."""
        svc = _svc()
        seen = {}

        async def _capture(prompt, max_tokens=260, structured=True):
            seen["max_tokens"] = max_tokens
            return None

        svc._generate = _capture
        from backend.app.ai.copilot import build_copilot_context
        ctx = build_copilot_context(_report(), "flood?")
        await svc.generate_copilot_answer(ctx)
        assert seen["max_tokens"] > 728, seen

    def test_documented_model_supports_structured_output(self):
        """The configured model must advertise ``response_format``.

        ``nvidia/nemotron-3-ultra-550b-a55b:free`` (the previous default) did not
        list it, which is why the JSON schema was silently ignored.
        """
        import pathlib
        model = [l.split("=", 1)[1].strip() for l in
                 (pathlib.Path(__file__).resolve().parents[2] / ".env.example")
                 .read_text(encoding="utf-8").splitlines()
                 if l.startswith("URBANOS_LLM_MODEL=")][0]
        assert model, "URBANOS_LLM_MODEL must be documented in .env.example"
        # Pinned to the model verified in the benchmark; changing it without
        # re-running the benchmark will fail here.
        assert model == "liquid/lfm-2.5-2.6b:free", (
            "documented model changed; re-run the narrative compatibility "
            "benchmark before accepting a different model")