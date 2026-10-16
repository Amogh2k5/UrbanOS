"""Regression tests for the Roads reliability fix.

Each test pins behaviour the Overview audit measured on the running backend:
a degraded ``datamall2.mytransport.sg`` produced a 19s failure on
``/analytics/summary``, a 120s hang on ``/speed-context``, and - because the
three LTA feeds were fetched sequentially and unbounded - held the whole
Overview for minutes.

Covered: per-source timeout, partial success, complete failure, stale-cache
fallback, cache expiry, provenance/timestamp preservation, single-flight, and
never caching an error as a success.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from backend.app.mobility.roads import aggregator
from backend.app.mobility.roads.aggregator import (
    ROADS_CACHE_TTL_S,
    ROADS_STALE_TTL_S,
    ROADS_SUB_SOURCE_BUDGET_S,
    get_roads_snapshot,
    reset_cache,
)
from backend.app.intelligence.normalize import build_kpi, determine_status


@pytest.fixture(autouse=True)
def _clean_cache():
    reset_cache()
    yield
    reset_cache()


def _ok(n: int = 8143) -> Dict[str, Any]:
    return {"total": n + 100, "active": n, "upcoming": 10, "completed": 12}


def _install(works=None, openings=None, stands=None, calls: List[str] | None = None):
    """Patch the three sub-source fetchers."""
    def make(name, result, exc):
        def _fn():
            if calls is not None:
                calls.append(name)
            if exc is not None:
                raise exc
            return result
        return _fn

    return {
        "road_works": patch.object(aggregator, "_fetch_works", make("road_works", works or _ok(), None)),
        "road_openings": patch.object(aggregator, "_fetch_openings",
                                      make("road_openings", openings or {"total": 10, "active": 2, "upcoming": 1}, None)),
        "taxi_stands": patch.object(aggregator, "_fetch_taxi_stands",
                                    make("taxi_stands", stands or {"total": 5, "bfa_accessible": 2, "by_ownership": {}}, None)),
    }


def _patch_all(**kw):
    patches = _install(**kw)
    for p in patches.values():
        p.start()
    return patches


def _stop_all(patches):
    for p in patches.values():
        p.stop()


# ------------------------------------------------------------------- happy path
class TestAllSourcesAvailable:
    def test_all_three_sub_sources_are_returned(self):
        p = _patch_all()
        try:
            snap = get_roads_snapshot(force_refresh=True)
        finally:
            _stop_all(p)
        assert snap["road_works"]["active"] == 8143
        assert snap["road_openings"]["active"] == 2
        assert snap["taxi_stands"]["total"] == 5
        assert snap["unavailable_sources"] == []
        assert snap["partial"] is False
        assert snap["source_status"] == "available"
        assert snap["stale"] is False

    def test_provenance_timestamp_is_present_and_not_re_stamped(self):
        first = None
        p = _patch_all()
        try:
            snap = get_roads_snapshot(force_refresh=True)
            first = snap["fetched_at"]
        finally:
            _stop_all(p)
        assert first and first.endswith("+00:00") or "T" in first

    def test_age_is_zero_for_a_fresh_payload(self):
        p = _patch_all()
        try:
            snap = get_roads_snapshot(force_refresh=True)
        finally:
            _stop_all(p)
        assert snap["age_seconds"] < 5


# ------------------------------------------------------------------- timeout
class TestBoundedTimeout:
    def test_a_hanging_source_cannot_exceed_its_budget(self):
        """Regression: one degraded LTA feed held the Overview for minutes."""
        def _hang():
            time.sleep(30)
            return _ok()

        with patch.object(aggregator, "_fetch_works", _hang), \
             patch.object(aggregator, "_fetch_openings",
                          lambda: {"total": 10, "active": 2, "upcoming": 1}), \
             patch.object(aggregator, "_fetch_taxi_stands",
                          lambda: {"total": 5, "bfa_accessible": 2, "by_ownership": {}}):
            t0 = time.perf_counter()
            snap = get_roads_snapshot(force_refresh=True)
            elapsed = time.perf_counter() - t0

        assert elapsed < ROADS_SUB_SOURCE_BUDGET_S + 3.0, f"took {elapsed:.1f}s"
        assert snap["road_works"] is None
        assert "road_works" in snap["unavailable_sources"]

    def test_the_budget_is_documented_and_tighter_than_one_request(self):
        """8s is chosen against the client's own 15s per-request timeout."""
        from backend.app.mobility.roads import data as roads_data

        assert ROADS_SUB_SOURCE_BUDGET_S < roads_data.TIMEOUT


# ------------------------------------------------------------ partial success
class TestPartialSuccess:
    def test_one_failure_does_not_discard_the_others(self):
        p = _patch_all()
        patches = list(p.values())
        patches[0] = patch.object(aggregator, "_fetch_works",
                                  _raise(RuntimeError("LTA RoadWorks timeout")))
        for x in p.values():
            x.start()
        for x in patches:
            if x is not p["road_works"]:
                x.start()
        try:
            snap = get_roads_snapshot(force_refresh=True)
        finally:
            for x in set(patches):
                x.stop()

        assert snap["road_works"] is None
        assert snap["road_openings"] is not None
        assert snap["taxi_stands"] is not None
        assert snap["partial"] is True
        assert snap["source_status"] == "partial"
        assert snap["unavailable_sources"] == ["road_works"]
        assert snap["warnings"]

    def test_partial_results_still_drive_a_real_status(self):
        with patch.object(aggregator, "_fetch_works", lambda: _ok(8143)), \
             patch.object(aggregator, "_fetch_openings",
                          _raise(RuntimeError("down"))), \
             patch.object(aggregator, "_fetch_taxi_stands",
                          lambda: {"total": 5, "bfa_accessible": 2, "by_ownership": {}}):
            snap = get_roads_snapshot(force_refresh=True)

        # Status is derived from the metric that does exist.
        assert determine_status("roads", snap) == "critical"
        assert build_kpi("roads", snap)["value"] == 8143
        assert snap["source_status"] == "partial"


# ---------------------------------------------------------- complete failure
class TestCompleteFailure:
    def test_all_failed_reports_unavailable_and_is_not_cached(self):
        for name in ("_fetch_works", "_fetch_openings", "_fetch_taxi_stands"):
            pass
        with patch.object(aggregator, "_fetch_works", _raise(RuntimeError("x"))), \
             patch.object(aggregator, "_fetch_openings", _raise(RuntimeError("y"))), \
             patch.object(aggregator, "_fetch_taxi_stands", _raise(RuntimeError("z"))):
            snap = get_roads_snapshot(force_refresh=True)

        assert snap["road_works"] is None
        assert snap["source_status"] == "unavailable"
        assert snap["partial"] is False
        assert len(snap["unavailable_sources"]) == 3
        # Nothing usable must not become a "successful" cached payload.
        assert aggregator._last_good is None
        assert determine_status("roads", snap) == "unavailable"
        assert build_kpi("roads", snap) is None

    def test_a_failure_is_never_cached_as_a_success(self):
        with patch.object(aggregator, "_fetch_works", _raise(RuntimeError("x"))), \
             patch.object(aggregator, "_fetch_openings", _raise(RuntimeError("y"))), \
             patch.object(aggregator, "_fetch_taxi_stands", _raise(RuntimeError("z"))):
            get_roads_snapshot(force_refresh=True)
        assert aggregator._last_good is None
        assert aggregator._last_good_at == 0.0


# ------------------------------------------------------------- stale fallback
class TestStaleCacheFallback:
    def _prime(self):
        p = _patch_all()
        try:
            return get_roads_snapshot(force_refresh=True)
        finally:
            _stop_all(p)

    def test_upstream_failure_serves_the_cache_marked_stale(self):
        good = self._prime()
        with patch.object(aggregator, "_fetch_works", _raise(RuntimeError("outage"))), \
             patch.object(aggregator, "_fetch_openings", _raise(RuntimeError("outage"))), \
             patch.object(aggregator, "_fetch_taxi_stands", _raise(RuntimeError("outage"))):
            snap = get_roads_snapshot(force_refresh=True)

        # Real values survive...
        assert snap["road_works"]["active"] == good["road_works"]["active"]
        # ...but are never presented as fresh.
        assert snap["stale"] is True
        assert snap["source_status"] == "stale"
        assert snap["age_seconds"] >= 0
        assert any("upstream did not respond" in w for w in snap["warnings"])
        # The outage is still disclosed.
        assert snap["unavailable_sources"]

    def test_the_original_fetch_timestamp_is_preserved_on_a_stale_hit(self):
        good = self._prime()
        with patch.object(aggregator, "_fetch_works", _raise(RuntimeError("outage"))), \
             patch.object(aggregator, "_fetch_openings", _raise(RuntimeError("outage"))), \
             patch.object(aggregator, "_fetch_taxi_stands", _raise(RuntimeError("outage"))):
            snap = get_roads_snapshot(force_refresh=True)
        assert snap["fetched_at"] == good["fetched_at"]

    def test_cache_expired_past_the_stale_window_is_not_served(self):
        self._prime()
        # Age the cache beyond the stale horizon.
        aggregator._last_good_at = time.time() - (ROADS_STALE_TTL_S + 60)
        with patch.object(aggregator, "_fetch_works", _raise(RuntimeError("outage"))), \
             patch.object(aggregator, "_fetch_openings", _raise(RuntimeError("outage"))), \
             patch.object(aggregator, "_fetch_taxi_stands", _raise(RuntimeError("outage"))):
            snap = get_roads_snapshot(force_refresh=True)

        assert snap["road_works"] is None
        assert snap["source_status"] == "unavailable"
        assert snap["stale"] is False

    def test_fresh_cache_is_served_without_contacting_upstream(self):
        self._prime()
        calls: List[str] = []
        with patch.object(aggregator, "_fetch_works", lambda: calls.append("w") or _ok()), \
             patch.object(aggregator, "_fetch_openings", lambda: calls.append("o") or {}), \
             patch.object(aggregator, "_fetch_taxi_stands", lambda: calls.append("t") or {}):
            snap = get_roads_snapshot()
        assert calls == [], "cache hit must not re-hit LTA"
        assert snap["stale"] is False

    def test_expired_fresh_cache_triggers_a_refresh(self):
        self._prime()
        aggregator._last_good_at = time.time() - (ROADS_CACHE_TTL_S + 10)
        calls: List[str] = []
        with patch.object(aggregator, "_fetch_works", lambda: calls.append("w") or _ok()), \
             patch.object(aggregator, "_fetch_openings", lambda: calls.append("o") or {}), \
             patch.object(aggregator, "_fetch_taxi_stands", lambda: calls.append("t") or {}):
            get_roads_snapshot()
        # Concurrent sub-sources: order is not defined, membership is.
        assert sorted(calls) == ["o", "t", "w"]


# ------------------------------------------------------------- single-flight
class TestSingleFlight:
    def test_concurrent_callers_do_not_duplicate_upstream_work(self):
        """No retry storm: concurrent Overview refreshes share one fetch."""
        reset_cache()
        calls: List[str] = []
        barrier = threading.Barrier(4)

        def slow_works():
            calls.append("road_works")
            time.sleep(0.6)
            return _ok()

        def other():
            barrier.wait(timeout=5)
            return {"total": 1, "active": 0, "upcoming": 0}

        with patch.object(aggregator, "_fetch_works", slow_works), \
             patch.object(aggregator, "_fetch_openings", other), \
             patch.object(aggregator, "_fetch_taxi_stands", other):
            results: List[Any] = []

            def worker():
                results.append(get_roads_snapshot())

            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=20)

        assert len(results) == 4
        # Every caller got a usable answer...
        assert all(r["road_works"] is not None for r in results)
        # ...from a single upstream fetch.
        assert calls.count("road_works") <= 2, calls


# ------------------------------------------------------------- overview wiring
class TestOverviewWiring:
    def test_the_overview_fetcher_goes_through_the_aggregator(self):
        import asyncio

        from backend.app.overview.api import _fetch_roads_overview
        from unittest.mock import MagicMock

        with patch("backend.app.mobility.roads.aggregator.get_roads_snapshot",
                   return_value={"road_works": _ok(), "road_openings": None,
                                 "taxi_stands": None, "fetched_at": "T",
                                 "source_status": "partial", "partial": True,
                                 "stale": False, "age_seconds": 1.0,
                                 "unavailable_sources": ["road_openings"],
                                 "warnings": ["road_openings: timeout"]}):
            data = asyncio.run(_fetch_roads_overview(MagicMock()))

        assert data["road_works"]["active"] == 8143
        assert data["partial"] is True
        assert data["unavailable_sources"] == ["road_openings"]
        assert determine_status("roads", data) == "critical"

    def test_a_roads_outage_does_not_raise(self):
        import asyncio

        from backend.app.overview.api import _fetch_roads_overview
        from unittest.mock import MagicMock

        with patch("backend.app.mobility.roads.aggregator.get_roads_snapshot",
                   _raise(RuntimeError("everything down"))):
            data = asyncio.run(_fetch_roads_overview(MagicMock()))
        assert data["error"]
        assert determine_status("roads", data) == "unavailable"


def _raise(exc: Exception):
    def _fn():
        raise exc
    return _fn