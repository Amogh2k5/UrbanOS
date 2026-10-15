"""Follow-up regression tests for the Issue 8 audit.

Each test pins a defect found by auditing the original fixes:

  * per-domain ``generated_at`` was still in the narrative cache key, so a real
    coordinator re-run re-stamped it and defeated the cache entirely;
  * the 900s ceiling was applied to confirmed daily quota exhaustion, producing
    ~96 guaranteed-to-fail provider probes per day;
  * a reset timestamp already in the past produced a **0 second** cooldown, i.e.
    no protection at all on the very response the breaker exists for.

Mocked provider, injected clock. No live calls.
"""
from __future__ import annotations

import json

import httpx
import pytest

from backend.app.ai.narrative import build_narrative_input
from backend.app.ai.service import (
    QUOTA_COOLDOWN_DEFAULT_S, QUOTA_COOLDOWN_MAX_S,
    QUOTA_DAILY_COOLDOWN_MAX_S, NarrativeCache, UrbanOSAIService,
)


class Clock:
    def __init__(self, start: float = 1_000_000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _svc(clock=None):
    s = UrbanOSAIService(api_key="sk-test-dummy-0123456789", provider="openrouter")
    if clock is not None:
        s._now = clock
    return s


def _report():
    from tests.intelligence.test_narrative_service import _report
    return _report()


def _rerun(report, stamp: str):
    """Simulate a real coordinator re-run: new report AND per-domain stamps."""
    report.generated_at = stamp
    for ds in report.domain_status.values():
        ds.generated_at = stamp
    return report


def _flood(n):
    """The available domain; ``domains`` is sorted, so index 0 is ``fire``."""
    return next(d for d in n.domains if d.domain == "flood")


class _Resp429:
    status_code = 429

    def __init__(self, body, headers=None):
        self._body = body
        self.headers = headers or {}

    def json(self):
        return self._body


# ============================================== Check 1: cache-key correctness
class TestCacheKeyExcludesAllTimestamps:
    def test_cache_key_drops_the_report_timestamp(self):
        ni = build_narrative_input(_report())
        assert "generated_at" not in json.loads(ni.cache_canonical())

    def test_cache_key_drops_per_domain_timestamps(self):
        report = _report()
        report.domain_status["flood"].generated_at = "2026-10-11T09:00:00+08:00"
        ni = build_narrative_input(report)
        payload = json.loads(ni.cache_canonical())
        assert all("generated_at" not in d for d in payload["domains"])

    def test_a_real_coordinator_rerun_reuses_the_cached_narrative(self):
        """The defect: per-domain stamps alone were enough to force a re-call."""
        a = _report()
        b = _rerun(_report(), "2026-10-11T09:02:00+08:00")
        assert a.generated_at != b.generated_at
        ka = NarrativeCache.key(build_narrative_input(a))
        kb = NarrativeCache.key(build_narrative_input(b))
        assert ka == kb

    @pytest.mark.asyncio
    async def test_rerun_makes_exactly_one_provider_call(self):
        svc = _svc()
        counter = {"n": 0}

        def handler(_r):
            counter["n"] += 1
            return httpx.Response(200, json={"choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps(
                    {"narrative": "City status DISRUPTED with HIGH risk."})}}]})

        svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1",
                                        transport=httpx.MockTransport(handler))
        a = _report()
        b = _rerun(_report(), "2026-10-11T09:02:00+08:00")
        await svc.generate_city_narrative(a)
        _, v = await svc.generate_city_narrative(b)
        assert counter["n"] == 1, counter
        assert v.reasons == ["cache hit"]

    @pytest.mark.parametrize("mutate", [
        pytest.param(lambda n: setattr(n, "overall_city_status", "CRITICAL"), id="status"),
        pytest.param(lambda n: setattr(n, "overall_risk_level", "LOW"), id="risk"),
        pytest.param(lambda n: setattr(n, "confidence", "low"), id="confidence"),
        pytest.param(lambda n: _flood(n).__setattr__("status", "MODERATE"), id="domain_status"),
        pytest.param(lambda n: _flood(n).__setattr__("risk", "LOW"), id="domain_risk"),
        pytest.param(lambda n: _flood(n).__setattr__(
            "key_metrics", {"active_alert_count": 99}), id="key_metrics"),
        pytest.param(lambda n: _flood(n).__setattr__(
            "affected_zones", ["Bukit Panjang"]), id="affected_zones"),
        pytest.param(lambda n: _flood(n).__setattr__(
            "limitations", ["Sensor offline."]), id="domain_limitations"),
        pytest.param(lambda n: _flood(n).__setattr__("available", False), id="available"),
        pytest.param(lambda n: n.findings.append("A new finding."), id="findings"),
        pytest.param(lambda n: n.cross_domain_impacts.append(
            {"type": "x", "description": "d", "severity": "HIGH"}), id="impacts"),
        pytest.param(lambda n: n.recommendations.append("FLOOD: act."), id="recommendations"),
        pytest.param(lambda n: n.affected_zones.append("Jurong West"), id="city_zones"),
        pytest.param(lambda n: n.limitations.append("New limitation."), id="limitations"),
        pytest.param(lambda n: n.unavailable_domains.append("fire"), id="unavailable"),
    ])
    def test_meaningful_change_always_changes_the_key(self, mutate):
        """Only timestamps may be excluded; nothing that changes the prose."""
        base = build_narrative_input(_report())
        mutated = base.model_copy(deep=True)
        assert _flood(base).available, "fixture sanity: flood starts available"
        mutate(mutated)
        assert NarrativeCache.key(base) != NarrativeCache.key(mutated)

    def test_prompt_still_receives_the_real_timestamps(self):
        """The key excludes them; the model must still see them."""
        from backend.app.ai.service import UrbanOSAIService as S
        report = _report()
        report.domain_status["flood"].generated_at = "2026-10-11T09:00:00+08:00"
        prompt = S(api_key="sk-test-dummy-0123456789",
                   provider="openrouter").build_prompt(build_narrative_input(report))
        assert report.generated_at in prompt
        assert "2026-10-11T09:00:00+08:00" in prompt
        assert "generated_at" in prompt


# ================================= Check 2: daily quota vs transient limits
DAILY_BODY = {"error": {
    "message": ("Rate limit exceeded: free-models-per-day. Add 10 credits to "
                "unlock 1000 free model requests per day"),
    "code": 429,
    "metadata": {"headers": {"X-RateLimit-Limit": "50", "X-RateLimit-Remaining": "0"}}}}


class TestQuotaCooldownBounds:
    def test_real_daily_quota_response_is_classified_as_quota(self):
        clock = Clock()
        svc = _svc(clock)
        svc._open_quota_cooldown(_Resp429(DAILY_BODY))
        assert svc.quota_status()["quota_exhausted"] is True

    def test_transient_rate_limit_is_not_treated_as_daily(self):
        clock = Clock()
        svc = _svc(clock)
        svc._open_quota_cooldown(
            _Resp429({"error": {"message": "Rate limit exceeded", "code": 429}}))
        assert svc.quota_status()["quota_exhausted"] is False

    def test_daily_quota_honours_a_longer_provider_reset(self):
        """8h reset must not be truncated to the transient 15-minute ceiling."""
        clock = Clock()
        svc = _svc(clock)
        reset_ms = int((clock() + 8 * 3600) * 1000)
        svc._open_quota_cooldown(
            _Resp429({"error": {"message": "free-models-per-day", "code": 429}},
                     {"x-ratelimit-reset": str(reset_ms)}))
        cooldown = svc._quota_blocked_until - clock()
        assert cooldown == QUOTA_DAILY_COOLDOWN_MAX_S
        # Far fewer probes than the old 15-minute cap produced.
        assert 86400 / cooldown <= 5

    def test_daily_quota_is_still_bounded(self):
        clock = Clock()
        svc = _svc(clock)
        reset_ms = int((clock() + 3650 * 86400) * 1000)
        svc._open_quota_cooldown(
            _Resp429({"error": {"message": "free-models-per-day", "code": 429}},
                     {"x-ratelimit-reset": str(reset_ms)}))
        assert svc._quota_blocked_until - clock() <= QUOTA_DAILY_COOLDOWN_MAX_S

    def test_transient_still_uses_the_tight_ceiling(self):
        clock = Clock()
        svc = _svc(clock)
        reset_ms = int((clock() + 8 * 3600) * 1000)
        svc._open_quota_cooldown(
            _Resp429({"error": {"message": "Rate limit exceeded", "code": 429}},
                     {"x-ratelimit-reset": str(reset_ms)}))
        assert svc._quota_blocked_until - clock() <= QUOTA_COOLDOWN_MAX_S

    def test_stale_reset_in_the_past_still_protects(self):
        """The observed real reset was ~5h stale; it must not mean 0s."""
        clock = Clock()
        svc = _svc(clock)
        reset_ms = int((clock() - 5 * 3600) * 1000)
        svc._open_quota_cooldown(
            _Resp429(DAILY_BODY, {"x-ratelimit-reset": str(reset_ms)}))
        cooldown = svc._quota_blocked_until - clock()
        assert cooldown == QUOTA_COOLDOWN_MAX_S
        assert svc._in_quota_cooldown() is True

    def test_stale_reset_on_transient_uses_the_default(self):
        clock = Clock()
        svc = _svc(clock)
        reset_ms = int((clock() - 60) * 1000)
        svc._open_quota_cooldown(
            _Resp429({"error": {"message": "Rate limit exceeded", "code": 429}},
                     {"x-ratelimit-reset": str(reset_ms)}))
        assert svc._quota_blocked_until - clock() == QUOTA_COOLDOWN_DEFAULT_S

    def test_retry_after_is_still_honoured_for_transient_limits(self):
        clock = Clock()
        svc = _svc(clock)
        svc._open_quota_cooldown(
            _Resp429({"error": {"message": "Rate limit exceeded", "code": 429}},
                     {"retry-after": "45"}))
        assert svc._quota_blocked_until - clock() == 45.0

    @pytest.mark.parametrize("body,headers", [
        ({"error": {"message": "429"}}, {}),
        ({}, {}),
        ({"error": {"message": "slow down", "code": "n/a"}}, {}),
        ({"error": {"message": "x", "metadata": {"headers": "not-a-dict"}}}, {}),
        ({"error": {"message": "free-models-per-day", "code": 429}},
         {"x-ratelimit-reset": "not-a-number"}),
    ])
    def test_ambiguous_429_fails_safe_without_an_excessive_pause(self, body, headers):
        clock = Clock()
        svc = _svc(clock)
        svc._open_quota_cooldown(_Resp429(body, headers))
        cooldown = svc._quota_blocked_until - clock()
        assert cooldown > 0, "must never be 0"
        assert cooldown <= QUOTA_DAILY_COOLDOWN_MAX_S

    @pytest.mark.asyncio
    async def test_daily_cooldown_still_serves_the_fallback_without_calling(self):
        clock = Clock()
        svc = _svc(clock)
        counter = {"n": 0}

        def handler(_r):
            counter["n"] += 1
            reset_ms = int((clock() + 8 * 3600) * 1000)
            return httpx.Response(429, json=DAILY_BODY,
                                  headers={"x-ratelimit-reset": str(reset_ms)})

        svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1",
                                        transport=httpx.MockTransport(handler))
        rep = _report()
        await svc.generate_city_narrative(rep)
        assert counter["n"] == 1
        for _ in range(20):
            narrative, validation = await svc.generate_city_narrative(rep)
            assert narrative is None and not validation.ok
        assert counter["n"] == 1, counter

    @pytest.mark.asyncio
    async def test_recovery_after_the_daily_cooldown_expires(self):
        clock = Clock()
        svc = _svc(clock)
        counter = {"n": 0}
        good = "City status DISRUPTED with HIGH risk."

        def fail(_r):
            counter["n"] += 1
            return httpx.Response(429, json=DAILY_BODY, headers={
                "x-ratelimit-reset": str(int((clock() + 8 * 3600) * 1000))})

        def ok(_r):
            counter["n"] += 1
            return httpx.Response(200, json={"choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps({"narrative": good})}}]})

        svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1",
                                        transport=httpx.MockTransport(fail))
        rep = _report()
        await svc.generate_city_narrative(rep)
        assert svc.quota_status()["in_cooldown"] is True

        # Nothing may be attempted before expiry.
        clock.advance(QUOTA_DAILY_COOLDOWN_MAX_S - 1)
        await svc.generate_city_narrative(rep)
        assert counter["n"] == 1

        clock.advance(2)
        svc._client = httpx.AsyncClient(base_url="https://openrouter.ai/api/v1",
                                        transport=httpx.MockTransport(ok))
        narrative, validation = await svc.generate_city_narrative(rep)
        assert counter["n"] == 2
        assert narrative == good and validation.ok
        assert svc.quota_status()["in_cooldown"] is False
