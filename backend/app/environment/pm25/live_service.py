"""PM2.5 live snapshot service.

Shared latest-PM2.5-snapshot cache (same pattern as the traffic prediction
service, but simpler because the NEA API already returns proper region-wise
readings: north/south/east/west/central).

Flow:
    live NEA PM2.5 API (via the existing Pm25ApiClient adapter)
        -> background refresh thread (hourly; single-flight; never in a request)
        -> immutable latest Pm25LiveSnapshot (REAL timestamps from the API)
        -> read by /kpi/live/pm25 and /internal/environment/pm25/status
        -> successful live fetches are also upserted into Pm25ObservationStore
           so the ML feature pipeline's PM2.5 freshness gate keeps passing.

Failure behaviour is explicit, never silent:
    - startup   : loads the latest stored snapshot from SQLite (indexed reads
                  only) so a valid snapshot is served immediately;
    - API failure: retains the last valid snapshot, logs the failure, and the
                  status endpoint exposes the real snapshot age + last error.
    - no fake timestamps, no fabricated values: readings come from the API or
                  from the observation store, verbatim.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from backend.app.environment.pm25.api import (
    Pm25ApiClient,
    Pm25LiveSnapshot,
    Pm25Reading,
    _now_iso,
)

log = logging.getLogger(__name__)

# NEA publishes PM2.5 hourly; refresh at that cadence by default.
_REFRESH_INTERVAL_S = float(os.getenv("URBANOS_PM25_REFRESH_INTERVAL_S", "3600"))
_PM25_REGIONS = {"north", "south", "east", "west", "central"}


class Pm25LiveSnapshotService:
    """Owns the latest shared Pm25LiveSnapshot.

    Threading model:
      - _refresh_lock   single-flight gate for refreshes (no duplicate
                        concurrent live fetches, ever; extra triggers while a
                        refresh is running return immediately);
      - the snapshot reference itself is swapped atomically (plain attribute
                        assignment is atomic under the GIL); readers never block.
    """

    def __init__(
        self,
        api_client: Optional[Pm25ApiClient] = None,
        refresh_interval_s: float = _REFRESH_INTERVAL_S,
    ) -> None:
        self._client = api_client or Pm25ApiClient(offline=False, allow_fallback_fixture=False)
        self.refresh_interval_s = refresh_interval_s

        self._snapshot: Optional[Pm25LiveSnapshot] = None
        self._refresh_lock = threading.Lock()
        self._store_seed_lock = threading.Lock()
        self._store_seed_attempted = False
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None

        # Observability (all real measurements)
        self.initialized: bool = False
        self.refresh_count: int = 0
        self.fetch_count: int = 0
        self.failure_count: int = 0
        self.last_refresh_started_epoch: Optional[float] = None
        self.last_refresh_seconds: Optional[float] = None
        self.last_success_epoch: Optional[float] = None
        self.last_error: Optional[str] = None

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Start the background worker: seed from store, then hourly refresh."""
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(
            target=self._worker_main, name="pm25-live-snapshot-service", daemon=True
        )
        self._worker.start()
        log.info("PM2.5 live snapshot service started (interval=%.0fs)", self.refresh_interval_s)

    def stop(self) -> None:
        self._stop_event.set()

    def _worker_main(self) -> None:
        try:
            self._ensure_store_seeded()
        except Exception as e:
            self.last_error = f"seed from store failed: {e}"
            log.exception("PM2.5 live service: failed to load stored snapshot")
        self.initialized = True

        while not self._stop_event.is_set():
            try:
                self._refresh()
            except Exception as e:
                # _refresh() itself never raises; belt-and-braces.
                self.last_error = f"refresh crashed: {e}"
                log.exception("PM2.5 live service: unexpected refresh failure")
            self._stop_event.wait(timeout=self.refresh_interval_s)

    # ------------------------------------------------------------------ seeding

    def _ensure_store_seeded(self) -> None:
        """Read the persisted snapshot at most once, without an API refresh."""
        if self._store_seed_attempted:
            return
        with self._store_seed_lock:
            if self._store_seed_attempted:
                return
            self._store_seed_attempted = True
            self._load_from_store()

    def _load_from_store(self) -> None:
        """Load the latest stored snapshot from the observation store.

        Cheap indexed reads only (MAX(observed_at) + one PK range read).
        Source rows are marked is_live=False: this is stored data, not a fresh
        API fetch — timestamps are the real NEA observation timestamps.
        """
        from backend.app.environment.pm25.data import Pm25ObservationStore

        store = Pm25ObservationStore()
        latest = store.get_latest_observation_timestamp()
        if not latest:
            log.warning("PM2.5 live service: no stored observations; waiting for first live fetch")
            return
        rows = store.get_latest_snapshot()  # {region: row-dict} at latest ts
        if not rows or set(rows) != _PM25_REGIONS:
            if rows:
                log.warning("PM2.5 store snapshot is incomplete; not exposing it as current")
            return

        observations = {row.get("observed_at") for row in rows.values()}
        if observations != {latest}:
            log.warning("PM2.5 store snapshot has inconsistent observation timestamps")
            return

        try:
            datetime.fromisoformat(str(latest).replace("Z", "+00:00"))
            readings = {}
            for region, row in rows.items():
                value = float(row["value"])
                if not math.isfinite(value) or value < 0:
                    raise ValueError("invalid stored PM2.5 value")
                readings[region] = Pm25Reading(
                    region=region,
                    value=value,
                    observed_at=str(row["observed_at"]),
                    source=str(row["source"]),
                )
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("PM2.5 stored snapshot failed validation: %s", exc)
            return

        snapshot = Pm25LiveSnapshot(
            snapshot_at=_now_iso(),
            source="stored_snapshot:pm25_observations_db",
            unit=str(next(iter(rows.values())).get("unit") or "µg/m3"),
            regions=readings,
            raw_issue_timestamp=latest,
            raw_updated_timestamp=None,
            is_live=False,
        )
        self._snapshot = snapshot
        log.info(
            "PM2.5 live service: seeded from store (regions=%s, observed_at=%s)",
            sorted(snapshot.regions), latest,
        )

    # ------------------------------------------------------------------ refresh

    def _refresh(self) -> None:
        """Single-flight live refresh: fetch API, swap snapshot, upsert store."""
        if not self._refresh_lock.acquire(blocking=False):
            # Another refresh is already running: coalesce onto it.
            log.debug("PM2.5 live service: refresh already in progress; skipped")
            return
        try:
            self.last_refresh_started_epoch = time.time()
            t0 = time.perf_counter()
            snapshot = self._client.fetch()  # raises on any failure (no fixture)
            self.fetch_count += 1

            if not snapshot.is_live or not snapshot.regions:
                # Defensive: fixture/empty payloads are not stored, not served as live.
                self.failure_count += 1
                self.last_error = "live fetch returned non-live/empty snapshot"
                log.warning(
                    "PM2.5 live service: refresh rejected (is_live=%s, regions=%d); keeping previous snapshot",
                    snapshot.is_live, len(snapshot.regions),
                )
                return

            self._snapshot = snapshot
            self.refresh_count += 1
            self.last_success_epoch = time.time()
            self.last_refresh_seconds = time.perf_counter() - t0
            self.last_error = None
            log.info(
                "PM2.5 live service: snapshot refreshed in %.2fs (regions=%s, observed_at=%s)",
                self.last_refresh_seconds, sorted(snapshot.regions), snapshot.raw_issue_timestamp,
            )
            self._persist(snapshot)
        except Exception as e:
            self.failure_count += 1
            self.last_error = f"{type(e).__name__}: {e}"
            log.warning(
                "PM2.5 live fetch failed; retaining last valid snapshot (age available via status): %s",
                self.last_error,
            )
        finally:
            self._refresh_lock.release()

    def _persist(self, snapshot: Pm25LiveSnapshot) -> None:
        """Upsert the live snapshot into the observation store (keeps the ML
        feature pipeline's PM2.5 freshness gate fed). Never raises."""
        try:
            from backend.app.environment.pm25.data import (
                Pm25ObservationStore,
                live_snapshot_to_observations,
            )

            observations = live_snapshot_to_observations(snapshot, created_at=_now_iso())
            Pm25ObservationStore().upsert_observations(observations)
        except Exception as e:
            self.last_error = f"store upsert failed: {e}"
            log.exception("PM2.5 live service: failed to persist snapshot to observation store")

    def on_collected_snapshot(self, snapshot: Pm25LiveSnapshot) -> None:
        """Called by Pm25Collector after a successful manual/scheduled cycle."""
        if snapshot is None or not snapshot.is_live or not snapshot.regions:
            return
        self._snapshot = snapshot
        self.refresh_count += 1
        self.last_success_epoch = time.time()
        self.last_error = None
        log.info(
            "PM2.5 live service: snapshot updated from collector cycle (observed_at=%s)",
            snapshot.raw_issue_timestamp,
        )

    # ------------------------------------------------------------------ reads

    def snapshot(self) -> Optional[Pm25LiveSnapshot]:
        """Return memory data, or seed once from validated local storage.

        This read performs no upstream request. The stored values remain marked
        ``is_live=False`` and retain their original observation timestamp.
        """
        if self._snapshot is None:
            try:
                self._ensure_store_seeded()
            except Exception as exc:
                log.warning("PM2.5 store-only snapshot read failed: %s", exc)
        return self._snapshot

    def status(self) -> Dict[str, Any]:
        from datetime import datetime, timezone, timedelta

        snap = self._snapshot
        now = time.time()
        age_seconds: Optional[float] = None
        observed_at: Optional[str] = None
        if snap is not None:
            observed_at = snap.raw_issue_timestamp
            try:
                from datetime import datetime as _dt

                first = next(iter(snap.regions.values()))
                obs = _dt.fromisoformat(first.observed_at)
                age_seconds = round(now - obs.timestamp(), 1)
            except Exception:
                age_seconds = None
        return {
            "initialized": self.initialized,
            "snapshot_available": snap is not None,
            "observation_timestamp": observed_at,
            "snapshot_age_seconds": age_seconds,
            "region_count": len(snap.regions) if snap is not None else 0,
            "regions": sorted(snap.regions) if snap is not None else [],
            "is_live": snap.is_live if snap is not None else None,
            "source": snap.source if snap is not None else None,
            "refresh_count": self.refresh_count,
            "fetch_count": self.fetch_count,
            "failure_count": self.failure_count,
            "last_refresh_seconds": self.last_refresh_seconds,
            "last_success_age_seconds": (
                round(now - self.last_success_epoch, 1) if self.last_success_epoch else None
            ),
            "last_error": self.last_error,
            "refresh_interval_s": self.refresh_interval_s,
        }


_SERVICE: Optional[Pm25LiveSnapshotService] = None
_SERVICE_LOCK = threading.Lock()


def get_pm25_live_service() -> Pm25LiveSnapshotService:
    """Process-wide singleton (lazy)."""
    global _SERVICE
    if _SERVICE is None:
        with _SERVICE_LOCK:
            if _SERVICE is None:
                _SERVICE = Pm25LiveSnapshotService()
    return _SERVICE
