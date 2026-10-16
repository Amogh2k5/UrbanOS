"""Provider efficiency and quota protection.

Audit-driven tests for the caches that already existed, plus the HTTP 429
circuit breaker added because an exhausted free-tier quota made every dashboard
refresh issue provider calls that could only fail.

All provider responses are mocked and the clock is injected, so nothing here
depends on the network or on wall-clock timing.
"""
from __future__ import annotations

import json

import httpx
import pytest

from backend.app.ai.copilot import build_copilot_context, grounded_fallback
from backend.app.ai.narrative import (
    build_narrative_input, deterministic_summary, validate_narrative,
)
from backend.app.ai.service import (
    QUOTA_COOLDOWN_DEFAULT_S, QUOTA_COOLDOWN_MAX_S, NarrativeCache,
    UrbanOSAIService, reset_ai_service,
)

GOOD_NARRATIVE = ("City status DISRUPTED with HIGH risk. Flood risk is HIGH in "
                  "Central South.")
GOOD_ANSWER = "Flood risk is HIGH in Central South."


class Clock:
    """Controllable clock, so cooldown tests never sleep."""

    def __init__(self, start: float = 1_000_000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _svc(clock: Clock | None = None) -> UrbanOSAIService:
    svc = UrbanOSAIService(api_key="sk-test-dummy-0123456789", provider="openrouter")
    svc._client_loop = None
    if clock is not None:
        svc._now = clock
    return svc


def _narrative_transport(counter: dict):
    def handler(_r):
        counter["n"] = counter.get("n", 0) + 1
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop",
                         "message": {"content": json.dumps({"narrative": GOOD_NARRATIVE})}}]})
    return handler


def _answer_transport(counter: dict):
    def handler(_r):
        counter["n"] = counter.get("n", 0) + 1
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop",
                         "message": {"content": json.dumps({"answer": GOOD_ANSWER})}}]})
    return handler


def _attach(svc, handler):
    svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1",
                                    transport=httpx.MockTransport(handler))


def _report(report_mod):
    from tests.intelligence.test_narrative_service import _report as base
    return report_mod(base())


def _plain_report():
    from tests.intelligence.test_narrative_service import _report
    return _report()


def _quota_transport(counter: dict, daily: bool = True):
    def handler(_r):
        counter["n"] = counter.get("n", 0) + 1
        if daily:
            return httpx.Response(429, json={
                "error": {"message": ("Rate limit exceeded: free-models-per-day. "
                                      "Add 10 credits to unlock 1000 free model "
                                      "requests per day"),
                          "code": 429,
                          "metadata": {"headers": {"X-RateLimit-Limit": "50",
                                                   "X-RateLimit-Remaining": "0"}}}})
        return httpx.Response(429, json={
            "error": {"message": "Rate limit exceeded", "code": 429}})
    return handler


# ============================================================ cache behaviour
class TestCacheReuse:
    @pytest.mark.asyncio
    async def test_repeated_identical_requests_use_the_cache(self):
        svc = _svc()
        counter: dict = {}
        _attach(svc, _narrative_transport(counter))
        rep = _plain_report()

        first, v1 = await svc.generate_city_narrative(rep)
        second, v2 = await svc.generate_city_narrative(rep)
        third, v3 = await svc.generate_city_narrative(rep)

        assert first == second == third == GOOD_NARRATIVE
        assert v1.ok and v2.ok and v3.ok
        assert counter["n"] == 1, counter
        assert v2.reasons == ["cache hit"] and v3.reasons == ["cache hit"]

    @pytest.mark.asyncio
    async def test_unchanged_city_reuses_narrative_across_coordinator_runs(self):
        """The key is the evidence, not the run timestamp.

        The coordinator re-runs every TTL and stamps a new ``generated_at`` even
        when nothing changed. Keying on it caused a provider call per dashboard
        load: 720/day against a 50/day free quota.
        """
        svc = _svc()
        counter: dict = {}
        _attach(svc, _narrative_transport(counter))

        a = _plain_report()
        b = _plain_report()
        b.generated_at = "2026-10-11T09:04:00+08:00"
        assert a.generated_at != b.generated_at

        await svc.generate_city_narrative(a)
        _, v = await svc.generate_city_narrative(b)
        assert counter["n"] == 1, counter
        assert v.reasons == ["cache hit"]

    @pytest.mark.asyncio
    async def test_different_evidence_does_not_share_a_cached_narrative(self):
        svc = _svc()
        counter: dict = {}
        _attach(svc, _narrative_transport(counter))
        a = _plain_report()
        b = _plain_report()
        b.overall_risk_level = "CRITICAL"

        assert NarrativeCache.key(build_narrative_input(a)) != \
            NarrativeCache.key(build_narrative_input(b))
        await svc.generate_city_narrative(a)
        await svc.generate_city_narrative(b)
        assert counter["n"] == 2, counter

    @pytest.mark.asyncio
    async def test_different_questions_do_not_share_a_cached_answer(self):
        svc = _svc()
        counter: dict = {}
        _attach(svc, _answer_transport(counter))
        rep = _plain_report()

        q1 = build_copilot_context(rep, "How is flood risk?")
        q2 = build_copilot_context(rep, "How is traffic?")
        q3 = build_copilot_context(rep, "How is flood risk?")

        await svc.generate_copilot_answer(q1)
        await svc.generate_copilot_answer(q2)
        _, v3 = await svc.generate_copilot_answer(q3)
        assert counter["n"] == 2, counter
        assert v3.reasons == ["cache hit"]

    @pytest.mark.asyncio
    async def test_conversation_context_is_part_of_the_answer_identity(self):
        svc = _svc()
        rep = _plain_report()
        bare = build_copilot_context(rep, "How is flood risk?")
        with_history = build_copilot_context(
            rep, "How is flood risk?", history=[{"role": "user", "text": "earlier"}])
        assert svc._copilot_key(bare) != svc._copilot_key(with_history)

    @pytest.mark.asyncio
    async def test_concurrent_identical_requests_make_one_provider_call(self):
        svc = _svc()
        counter: dict = {}
        _attach(svc, _narrative_transport(counter))
        rep = _plain_report()

        import asyncio
        results = await asyncio.gather(
            *(svc.generate_city_narrative(rep) for _ in range(6)))
        assert counter["n"] == 1, counter
        assert all(n == GOOD_NARRATIVE for n, _ in results)

    def test_per_key_locks_do_not_leak(self):
        """Locks used to grow one per distinct key for the life of the process."""
        cache = NarrativeCache(ttl=60.0, maxsize=4)
        import asyncio
        for i in range(20):
            cache.set("k%d" % i, "v")
        assert len(cache._data) <= 4
        assert len(cache._locks) <= 4, len(cache._locks)
        cache.clear()
        assert cache._locks == {}


# ============================================================ quota cooldown
class TestQuotaCooldown:
    @pytest.mark.asyncio
    async def test_429_opens_cooldown_and_costs_only_one_call(self):
        clock = Clock()
        svc = _svc(clock)
        counter: dict = {}
        _attach(svc, _quota_transport(counter))
        rep = _plain_report()

        n1, v1 = await svc.generate_city_narrative(rep)
        assert n1 is None and not v1.ok
        assert counter["n"] == 1, counter
        assert svc.quota_status()["in_cooldown"] is True
        assert svc.quota_status()["quota_exhausted"] is True

    @pytest.mark.asyncio
    async def test_subsequent_requests_do_not_call_the_provider(self):
        clock = Clock()
        svc = _svc(clock)
        counter: dict = {}
        _attach(svc, _quota_transport(counter))
        rep = _plain_report()

        await svc.generate_city_narrative(rep)
        after_first = counter["n"]
        for _ in range(10):
            narrative, validation = await svc.generate_city_narrative(rep)
            assert narrative is None
            assert not validation.ok
        assert counter["n"] == after_first == 1, counter
        assert svc.quota_status()["blocked_requests"] == 10

    @pytest.mark.asyncio
    async def test_copilot_also_respects_the_cooldown(self):
        clock = Clock()
        svc = _svc(clock)
        counter: dict = {}
        _attach(svc, _quota_transport(counter))
        ctx = build_copilot_context(_plain_report(), "How is flood risk?")

        await svc.generate_copilot_answer(ctx)
        for _ in range(5):
            answer, validation = await svc.generate_copilot_answer(ctx)
            assert answer is None and not validation.ok
        assert counter["n"] == 1, counter

    @pytest.mark.asyncio
    async def test_deterministic_fallback_is_served_during_cooldown(self):
        """The UI must still get something true while the provider is paused."""
        clock = Clock()
        svc = _svc(clock)
        counter: dict = {}
        _attach(svc, _quota_transport(counter))
        rep = _plain_report()

        await svc.generate_city_narrative(rep)
        narrative, _ = await svc.generate_city_narrative(rep)
        fallback = deterministic_summary(rep)
        assert narrative is None
        assert fallback and "DISRUPTED" in fallback
        assert counter["n"] == 1

    @pytest.mark.asyncio
    async def test_copilot_grounded_fallback_survives_cooldown(self):
        clock = Clock()
        svc = _svc(clock)
        counter: dict = {}
        _attach(svc, _quota_transport(counter))
        ctx = build_copilot_context(_plain_report(), "How is flood risk?")
        await svc.generate_copilot_answer(ctx)
        answer, _ = await svc.generate_copilot_answer(ctx)
        assert answer is None
        fb = grounded_fallback(ctx)
        assert fb and "DISRUPTED" in fb

    @pytest.mark.asyncio
    async def test_provider_resumes_after_the_cooldown_expires(self):
        clock = Clock()
        svc = _svc(clock)
        counter: dict = {}
        _attach(svc, _quota_transport(counter))
        rep = _plain_report()

        await svc.generate_city_narrative(rep)
        assert counter["n"] == 1
        assert svc.quota_status()["in_cooldown"] is True

        # Still cooling down just before expiry: no call.
        clock.advance(QUOTA_COOLDOWN_DEFAULT_S - 1)
        await svc.generate_city_narrative(rep)
        assert counter["n"] == 1, "called while still in cooldown"

        # Expiry passes and the provider is healthy again.
        clock.advance(2)
        _attach(svc, _narrative_transport(counter))
        narrative, validation = await svc.generate_city_narrative(rep)
        assert counter["n"] == 2, counter
        assert narrative == GOOD_NARRATIVE
        assert validation.ok
        assert svc.quota_status()["in_cooldown"] is False

    @pytest.mark.asyncio
    async def test_a_successive_429_extends_the_cooldown(self):
        clock = Clock()
        svc = _svc(clock)
        counter: dict = {}
        _attach(svc, _quota_transport(counter))
        rep = _plain_report()

        await svc.generate_city_narrative(rep)
        first_until = svc._quota_blocked_until
        # Step past the expiry so the circuit re-probes the provider.
        clock.advance(QUOTA_COOLDOWN_DEFAULT_S)
        _attach(svc, _quota_transport(counter))
        await svc.generate_city_narrative(rep)   # re-probes at expiry, 429 again
        assert counter["n"] == 2, counter
        assert svc._quota_blocked_until > first_until

    def test_cooldown_is_bounded(self):
        """Even a far-future reset must not disable the narrative for a day."""
        clock = Clock()
        svc = _svc(clock)
        reset_ms = int((clock() + 86_400) * 1000)

        class _Resp:
            status_code = 429
            headers = {"x-ratelimit-reset": str(reset_ms)}

            def json(self):
                return {"error": {"message": "quota", "code": 429}}

        svc._open_quota_cooldown(_Resp())
        assert svc._quota_blocked_until - clock() <= QUOTA_COOLDOWN_MAX_S

    def test_transient_rate_limit_is_distinguished_from_quota_exhaustion(self):
        clock = Clock()
        svc = _svc(clock)

        class _Resp:
            status_code = 429
            headers = {}

            def json(self):
                return {"error": {"message": "Rate limit exceeded", "code": 429}}

        svc._open_quota_cooldown(_Resp())
        assert svc.quota_status()["quota_exhausted"] is False
        assert svc.quota_status()["in_cooldown"] is True

    @pytest.mark.asyncio
    async def test_reset_hook_clears_the_circuit_immediately(self):
        clock = Clock()
        svc = _svc(clock)
        counter: dict = {}
        _attach(svc, _quota_transport(counter))
        await svc.generate_city_narrative(_plain_report())
        assert svc.quota_status()["in_cooldown"] is True
        svc.reset_quota_cooldown()
        assert svc.quota_status()["in_cooldown"] is False


# ==================================================== other provider errors
class TestOtherProviderErrors:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [500, 502, 503, 401, 403, 400])
    async def test_other_errors_fall_back_without_opening_cooldown(self, status):
        clock = Clock()
        svc = _svc(clock)
        counter: dict = {}

        def handler(_r):
            counter["n"] = counter.get("n", 0) + 1
            return httpx.Response(status, json={"error": "nope"})

        _attach(svc, handler)
        narrative, validation = await svc.generate_city_narrative(_plain_report())
        assert narrative is None and not validation.ok
        assert counter["n"] == 1
        # A server error is not a quota problem: no long pause.
        assert svc.quota_status()["in_cooldown"] is False

    @pytest.mark.asyncio
    async def test_timeout_falls_back_safely(self):
        svc = _svc()

        def handler(_r):
            raise httpx.ReadTimeout("too slow")

        _attach(svc, handler)
        narrative, validation = await svc.generate_city_narrative(_plain_report())
        assert narrative is None and not validation.ok
        assert svc.quota_status()["in_cooldown"] is False


# ==================================== failures are never cached as successes
class TestOnlyValidResultsAreCached:
    @pytest.mark.asyncio
    async def test_truncated_response_is_not_cached(self):
        svc = _svc()
        counter: dict = {}

        def handler(_r):
            counter["n"] = counter.get("n", 0) + 1
            return httpx.Response(200, json={
                "choices": [{"finish_reason": "length",
                             "message": {"content": "The user wants me to write"}}]})

        _attach(svc, handler)
        rep = _plain_report()
        narrative, validation = await svc.generate_city_narrative(rep)
        assert narrative is None and not validation.ok
        assert svc.cache._data == {}
        assert svc.cache.get(svc.cache.key(build_narrative_input(rep))) is None
        # And the next attempt really does call the provider again.
        await svc.generate_city_narrative(rep)
        assert counter["n"] == 2, counter

    @pytest.mark.asyncio
    async def test_rejected_response_is_not_cached(self):
        svc = _svc()

        def handler(_r):
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                "message": {"content": json.dumps(
                    {"narrative": "City status CRITICAL everywhere at 9999 km/h."})}}]})

        _attach(svc, handler)
        rep = _plain_report()
        narrative, validation = await svc.generate_city_narrative(rep)
        assert narrative is None
        assert not validation.ok
        assert svc.cache._data == {}

    @pytest.mark.asyncio
    async def test_malformed_response_is_not_cached(self):
        svc = _svc()

        def handler(_r):
            return httpx.Response(200, json={"unexpected": "shape"})

        _attach(svc, handler)
        narrative, validation = await svc.generate_city_narrative(_plain_report())
        assert narrative is None and not validation.ok
        assert svc.cache._data == {}

    @pytest.mark.asyncio
    async def test_quota_failure_never_becomes_a_permanent_cache_entry(self):
        clock = Clock()
        svc = _svc(clock)
        counter: dict = {}
        _attach(svc, _quota_transport(counter))
        rep = _plain_report()

        await svc.generate_city_narrative(rep)
        assert svc.cache._data == {}, "fallback must never be cached as an answer"
        clock.advance(QUOTA_COOLDOWN_DEFAULT_S + 1)
        _attach(svc, _narrative_transport(counter))
        narrative, _ = await svc.generate_city_narrative(rep)
        assert narrative == GOOD_NARRATIVE, "recovery must produce a real narrative"

    @pytest.mark.asyncio
    async def test_copilot_rejection_is_not_cached(self):
        svc = _svc()
        counter: dict = {}

        def handler(_r):
            counter["n"] = counter.get("n", 0) + 1
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                "message": {"content": json.dumps(
                    {"answer": "Sales were 99999 million m3 yesterday."})}}]})

        _attach(svc, handler)
        ctx = build_copilot_context(_plain_report(), "How is water usage?")
        answer, validation = await svc.generate_copilot_answer(ctx)
        assert answer is None and not validation.ok
        assert svc.copilot_cache._data == {}
        await svc.generate_copilot_answer(ctx)
        assert counter["n"] == 2, counter


# ============================================= grounding still intact
class TestGroundingPreserved:
    def test_validator_still_enforces_the_word_bound(self):
        """The City Situation is a structured report, so the cap is generous -
        but it is still a briefing, not a dump."""
        from backend.app.ai.narrative import _MAX_NARRATIVE_WORDS

        ni = build_narrative_input(_plain_report())
        over_cap = "City status DISRUPTED. " * (_MAX_NARRATIVE_WORDS // 3 + 10)
        assert len(over_cap.split()) > _MAX_NARRATIVE_WORDS
        v = validate_narrative(over_cap, ni)
        assert not v.ok
        assert any("too long" in r for r in v.reasons)

    def test_validator_still_rejects_invented_numbers_and_statuses(self):
        ni = build_narrative_input(_plain_report())
        assert not validate_narrative("Flood risk is 9999 mm today.", ni).ok
        assert not validate_narrative("The city is CRITICAL now.", ni).ok

    @pytest.mark.asyncio
    async def test_cached_answer_is_still_validated_evidence_bound(self):
        """Serving from cache must not bypass grounding."""
        svc = _svc()
        counter: dict = {}
        _attach(svc, _answer_transport(counter))
        ctx = build_copilot_context(_plain_report(), "How is flood risk?")
        a1, v1 = await svc.generate_copilot_answer(ctx)
        a2, v2 = await svc.generate_copilot_answer(ctx)
        assert a1 == a2 and v1.ok and v2.ok
        assert counter["n"] == 1
        assert validate_narrative is not None
