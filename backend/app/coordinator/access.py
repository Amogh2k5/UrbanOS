"""Cached access to the deterministic City Coordinator report.

The coordinator run is expensive - measured at ~74s on this machine - so both
``/api/city/report`` and the Overview city endpoint go through this one
accessor. They therefore share a single run and a single narrative cache entry
instead of duplicating work on every dashboard refresh.

Two access modes, because the two callers want opposite things:

``block=True`` (default)
    Used by ``/api/city/report``, which exists precisely to return the full
    report. The caller is willing to wait for the whole run.

``block=False``
    Used by the dashboard. A measured coordinator run (~74s) is far longer than
    any acceptable page load, so this mode never waits: it returns a fresh
    cached report if one exists, and otherwise starts **at most one** background
    run and returns ``None`` straight away. The caller degrades to its own
    deterministic evidence. This is what keeps ``ai_brief`` populated during a
    cold start instead of ``null``.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger(__name__)

# Single-flight lock + short TTL cache.
_city_report_lock = threading.Lock()
_cache: Dict[str, Any] = {"report": None, "payload": None, "expires_at": 0.0}
CITY_REPORT_CACHE_TTL_S = 120.0

# Guards the *background* run bookkeeping only. It is held for microseconds and
# is never held across a coordinator run, so nothing can queue behind it.
_run_lock = threading.Lock()
_in_flight = False

# Bumped by invalidate_city_report_cache() so a run that was already under way
# when the cache was cleared does not repopulate it with the superseded result.
_generation = 0

#: Whether a cold read may start a background coordinator run. Turning this off
#: is a test hook: it keeps the suite from launching real ~74s runs.
#:
#: Defaults from the environment so a process that must not reach live sources
#: (the test session) can opt out before this module is even imported, which a
#: runtime setter could not guarantee.
_background_enabled = os.getenv("URBANOS_COORDINATOR_BACKGROUND", "1") != "0"


def set_background_runs_enabled(enabled: bool) -> None:
    """Test hook. Disables/enables starting coordinator runs in the background."""
    global _background_enabled
    _background_enabled = bool(enabled)


def _run_coordinator() -> Any:
    """Execute the coordinator graph and return its report.

    Isolated so tests can substitute it without patching the lazily-imported
    symbol inside :func:`city_report_cached`.
    """
    _ensure_repo_root_on_path()
    from coordinator.city_agent import run_city_coordinator
    return run_city_coordinator()


def _ensure_repo_root_on_path() -> None:
    """Make the top-level ``coordinator`` alias package importable."""
    root = str(Path(__file__).resolve().parents[3])
    if root not in sys.path:
        sys.path.insert(0, root)


def _fresh_cache_hit() -> Optional[Tuple[Any, Dict[str, Any]]]:
    """Return the cached report if it is still inside its TTL, else ``None``."""
    cached = _cache["report"]
    if cached is not None and time.time() < _cache["expires_at"]:
        return cached, _cache["payload"]
    return None


def city_report_cached(
    force_refresh: bool = False,
    *,
    block: bool = True,
) -> Optional[Tuple[Any, Dict[str, Any]]]:
    """Return ``(report_object, json_payload)``, coalesced and cached.

    Returns ``None`` if the coordinator could not produce a report; callers
    must degrade rather than invent.

    With ``block=False`` this never waits for a run: a fresh cached report is
    returned if there is one, otherwise a single background run is started (if
    none is already in flight) and ``None`` is returned immediately.
    """
    if not force_refresh:
        hit = _fresh_cache_hit()
        if hit is not None:
            return hit
        if not block:
            _start_background_run()
            return None

    with _city_report_lock:
        # Re-check after acquiring the lock: the previous holder may have
        # produced a fresh report we can share.
        if not force_refresh:
            hit = _fresh_cache_hit()
            if hit is not None:
                return hit

        with _run_lock:
            generation = _generation

        started = time.time()
        report = _run_coordinator()
        payload = report.model_dump(mode="json")

        # Only publish if the cache was not invalidated while this ran.
        with _run_lock:
            stale = generation != _generation
        if stale:
            log.info("Discarding city coordinator result: cache was invalidated mid-run.")
            return None

        _cache["report"] = report
        _cache["payload"] = payload
        _cache["expires_at"] = time.time() + CITY_REPORT_CACHE_TTL_S
        log.info("City coordinator run completed in %.1fs", time.time() - started)
        return report, payload


def _start_background_run() -> bool:
    """Start at most one coordinator run. Returns True if this call started it.

    Concurrent dashboard refreshes collapse onto the single in-flight run instead
    of queueing behind it or each launching their own.
    """
    global _in_flight
    with _run_lock:
        if not _background_enabled or _in_flight:
            return False
        _in_flight = True

    def _run() -> None:
        global _in_flight
        try:
            city_report_cached()
        except Exception:
            log.exception("Background city coordinator run failed.")
        finally:
            with _run_lock:
                _in_flight = False

    threading.Thread(target=_run, name="urbanos-city-coordinator", daemon=True).start()
    log.info("City coordinator background run started.")
    return True


def start_coordinator_warmup() -> None:
    """Begin one coordinator run at startup so the cache is warm.

    A measured run takes ~74s. Without this, the first dashboard request after a
    restart always finds a cold cache and can only show per-domain evidence,
    leaving the City Situation pending until the run finishes. Prewarming closes
    that window, and mirrors the warm-up Water and Land already perform.

    Honours :data:`_background_enabled`, so a process that must not reach live
    sources simply skips it. Fire and forget either way: a failed run is logged,
    the cache stays empty, and the next request starts another through the
    normal accessor.
    """
    with _run_lock:
        if not _background_enabled:
            log.info("City coordinator warm-up skipped: background runs disabled.")
            return

    def _run() -> None:
        try:
            city_report_cached()
        except Exception:
            log.exception("City coordinator warm-up failed.")

    threading.Thread(target=_run, name="urbanos-city-coordinator-warmup",
                     daemon=True).start()
    log.info("City coordinator warm-up started.")


def coordinator_run_in_flight() -> bool:
    """Test/diagnostic hook: is a coordinator run currently executing?"""
    with _run_lock:
        return _in_flight


def invalidate_city_report_cache() -> None:
    """Test hook.

    Deliberately does not take ``_city_report_lock``: that lock is held for the
    whole (~74s) coordinator run, and blocking here would hang the caller for
    the duration of an unrelated run.
    """
    global _generation
    with _run_lock:
        _generation += 1
        _cache["report"] = None
        _cache["payload"] = None
        _cache["expires_at"] = 0.0