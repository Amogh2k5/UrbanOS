"""Bounded, failure-isolated aggregation for the LTA Roads sources.

Why this module exists
----------------------
The three LTA Roads feeds are independent of each other but were always fetched
*sequentially* and with no bound on total time. During the Overview audit the
upstream (``datamall2.mytransport.sg``) was intermittently unreachable and a
single road-works page routinely took 24-32s to fail. Because
``RoadWorksApiClient.fetch_all()`` pages with a 15s per-request timeout and ~8000
works span ~17 pages, one degraded feed held the whole Overview for minutes.

What this does, and nothing more:

* Runs the three sub-sources **concurrently**, so total time is the slowest one
  rather than their sum.
* Gives each sub-source a **total wall-clock budget**, not just a per-request
  timeout. A per-request timeout cannot bound a paged fetch.
* **Isolates failures**. A source that fails is recorded by name; the others
  still contribute. The result is marked ``partial`` rather than invented.
* **Caches the last successful payload** with its provenance and fetch time.
  On upstream failure the cache is served only while still meaningful, flagged
  ``stale`` with its ``age_seconds``. A stale value is never presented as live.
* **Single-flights** refreshes so concurrent Overview requests cannot trigger
  duplicate upstream work or a retry storm.
* Never caches a failure as if it were a success.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

#: Wall-clock budget for ONE sub-source, covering all its pages.
#:
#: Chosen from the existing client behaviour: ``roads/data.py`` already sets
#: ``TIMEOUT = 15.0`` and passes ``timeout=15.0`` per request. A single request
#: alone can therefore legitimately take up to 15s, and road works need ~17
#: pages, so a per-request limit cannot bound the fetch. 8s is deliberately
#: *tighter* than one request's own limit: if a single feed cannot produce a
#: first page within 8s it is degraded, and the cache or an honest "unavailable"
#: is better than making an operator wait. The whole Overview therefore settles
#: in roughly one budget (~8s) instead of minutes.
ROADS_SUB_SOURCE_BUDGET_S = 8.0

#: A cached payload younger than this is served without contacting LTA at all.
ROADS_CACHE_TTL_S = 300.0

#: Beyond this age a cached payload is not served even when upstream is down.
#: Road works change daily; a payload many hours old is no longer a meaningful
#: substitute for a failed fetch, so we report unavailable instead.
ROADS_STALE_TTL_S = 3600.0

_SUB_SOURCES = ("road_works", "road_openings", "taxi_stands")

_lock = threading.Lock()
_last_good: Optional[Dict[str, Any]] = None
_last_good_at: float = 0.0


# --------------------------------------------------------------------- fetchers
def _fetch_works() -> Dict[str, Any]:
    from backend.app.mobility.roads.data import RoadDataProcessor, RoadWorksApiClient

    works = RoadDataProcessor.process_road_works(list(RoadWorksApiClient().fetch_all()))
    active = [w for w in works if w.is_active]
    upcoming = [w for w in works if w.is_upcoming]
    return {
        "total": len(works),
        "active": len(active),
        "upcoming": len(upcoming),
        "completed": len(works) - len(active) - len(upcoming),
    }


def _fetch_openings() -> Dict[str, Any]:
    from backend.app.mobility.roads.data import RoadOpeningsApiClient, RoadDataProcessor

    openings = RoadDataProcessor.process_road_openings(
        list(RoadOpeningsApiClient().fetch_all())
    )
    return {
        "total": len(openings),
        "active": len([o for o in openings if o.is_active]),
        "upcoming": len([o for o in openings if o.is_upcoming]),
    }


def _fetch_taxi_stands() -> Dict[str, Any]:
    from backend.app.mobility.roads.data import RoadDataProcessor, TaxiStandsApiClient

    stands = RoadDataProcessor.process_taxi_stands(TaxiStandsApiClient().fetch())
    ownership: Dict[str, int] = {}
    for s in stands:
        ownership[s.ownership] = ownership.get(s.ownership, 0) + 1
    return {
        "total": len(stands),
        "bfa_accessible": len([s for s in stands if s.is_bfa_accessible]),
        "by_ownership": ownership,
    }


#: Sub-source name -> module-level function *name*.
#:
#: Resolved through ``globals()`` at call time rather than captured here, so a
#: test (or a future override) that replaces a fetcher actually takes effect.
_SOURCE_FNS: Dict[str, str] = {
    "road_works": "_fetch_works",
    "road_openings": "_fetch_openings",
    "taxi_stands": "_fetch_taxi_stands",
}


def _run_bounded(name: str, budget_s: float) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Run one sub-source under a wall-clock budget.

    Returns ``(result, error)``. A timeout is an ordinary failure here: the
    worker may still finish in the background, but nothing waits for it, so the
    event loop and the caller both stay responsive.
    """
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"roads-{name}")
    try:
        future = pool.submit(globals()[_SOURCE_FNS[name]])
        try:
            return future.result(timeout=budget_s), None
        except TimeoutError:
            log.warning("Roads sub-source %s exceeded its %.1fs budget.", name, budget_s)
            # Abandon the worker rather than block. It is a daemon-style thread
            # with its own per-request timeouts and cannot hold anything open.
            future.cancel()
            return None, f"timeout after {budget_s:.0f}s"
        except Exception as exc:  # noqa: BLE001 - isolation is the point
            log.warning("Roads sub-source %s failed: %s", name, exc)
            return None, str(exc)
    finally:
        pool.shutdown(wait=False)


def _refresh(budget_s: float = ROADS_SUB_SOURCE_BUDGET_S) -> Tuple[Dict[str, Any], bool]:
    """Fetch all three sub-sources concurrently. Returns (payload, any_ok)."""
    results: Dict[str, Optional[Dict[str, Any]]] = {}
    errors: Dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=len(_SUB_SOURCES),
                            thread_name_prefix="roads-sources") as pool:
        futures = {
            pool.submit(_run_bounded, name, budget_s): name for name in _SUB_SOURCES
        }
        for future, name in futures.items():
            value, error = future.result()
            results[name] = value
            if error:
                errors[name] = error

    payload: Dict[str, Any] = {name: results[name] for name in _SUB_SOURCES}
    payload["unavailable_sources"] = sorted(errors)
    payload["partial"] = bool(errors) and any(v is not None for v in results.values())
    payload["fetched_at"] = datetime.now(timezone.utc).isoformat()
    payload["source_status"] = (
        "available" if not errors
        else "partial" if payload["partial"]
        else "unavailable"
    )
    payload["stale"] = False
    payload["age_seconds"] = 0.0
    payload["warnings"] = [
        f"{name}: {msg}" for name, msg in sorted(errors.items())
    ]
    return payload, payload["partial"] or not errors


def _acceptable(payload: Dict[str, Any]) -> bool:
    """A payload is worth caching only if at least one sub-source succeeded.

    An all-failed payload is never promoted to the cache: caching it would turn
    a transient outage into a permanently blank card.
    """
    return any(payload.get(name) is not None for name in _SUB_SOURCES)


def get_roads_snapshot(force_refresh: bool = False) -> Dict[str, Any]:
    """Roads aggregation with bounded time, failure isolation and a stale cache.

    Concurrency: refreshes are single-flighted behind ``_lock``. A second caller
    arriving during a refresh waits for it and then reads the cache, rather than
    starting a second set of upstream requests.
    """
    global _last_good, _last_good_at

    now = time.time()
    if not force_refresh and _last_good is not None and now - _last_good_at < ROADS_CACHE_TTL_S:
        return _with_age(dict(_last_good), _last_good_at)

    with _lock:
        # Another caller may have refreshed while we waited for the lock.
        now = time.time()
        if (not force_refresh and _last_good is not None
                and now - _last_good_at < ROADS_CACHE_TTL_S):
            return _with_age(dict(_last_good), _last_good_at)

        payload, any_ok = _refresh()
        now = time.time()

        if any_ok and _acceptable(payload):
            _last_good = {k: payload[k] for k in payload}
            _last_good_at = now
            return _with_age(dict(_last_good), _last_good_at)

        # Upstream failed. Serve the last good payload only while it is still
        # meaningful, clearly marked stale with its age.
        if _last_good is not None and (now - _last_good_at) < ROADS_STALE_TTL_S:
            fallback = dict(_last_good)
            fallback["unavailable_sources"] = payload["unavailable_sources"]
            fallback["warnings"] = payload["warnings"]
            log.warning(
                "Roads upstream unavailable; serving cached payload %.0fs old.",
                now - _last_good_at,
            )
            return _with_age(fallback, _last_good_at, stale=True)

        # Nothing usable. Report honestly rather than inventing zeros.
        return payload


def _with_age(payload: Dict[str, Any], fetched_at_epoch: float,
              stale: Optional[bool] = None) -> Dict[str, Any]:
    """Attach age/freshness without altering the preserved fetch timestamp."""
    age = max(0.0, time.time() - fetched_at_epoch)
    out = dict(payload)
    out["age_seconds"] = round(age, 1)
    if stale is None:
        out["stale"] = age >= ROADS_CACHE_TTL_S
        if out["stale"] and out.get("source_status") == "available":
            out["source_status"] = "stale"
    else:
        out["stale"] = stale
        if stale:
            out["source_status"] = "stale"
    out.setdefault("warnings", [])
    if out["stale"]:
        out["warnings"] = list(out["warnings"]) + [
            f"Cached LTA payload {age / 60:.0f} min old; upstream did not respond."
        ]
    return out


def reset_cache() -> None:
    """Test hook: drop the cached payload."""
    global _last_good, _last_good_at
    with _lock:
        _last_good = None
        _last_good_at = 0.0