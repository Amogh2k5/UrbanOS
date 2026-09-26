"""Live traffic prediction service.

Replaces per-request rebuilds of the 1M-row CSV pipeline with:
  - a rolling in-process per-link history (dict[link_id] -> deque(maxlen=7)):
    the current live LTA observation plus up to 6 previous observations —
    exactly what the production XGBoost feature contract needs (6 lags);
  - a single immutable PredictionBundle computed ONCE per new snapshot by a
    background thread (never inside an API request), reused by both
    /api/mobility/traffic/predict and /api/traffic/report;

The trained model, its 34-feature contract, the feature formulas, the
clipping/guards and the delta->speed math all live in TrafficPredictor and
are used UNCHANGED: this service only feeds predict_latest() from in-memory
rolling history via the same store facade (get_latest_snapshot /
get_link_history) instead of from the 1,006,509-row CSV.

Fallback behaviour is explicit and logged, never silent:
  - no bundle yet (cold start)            -> callers keep their existing
                                             "No traffic observations available"
                                             error behaviour; nothing is fabricated.
  - stale bundle                          -> served with its real observed_at
                                             timestamp (never re-stamped as current).
  - live fetch / seed / compute failures  -> logged, last good bundle retained.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

import pandas as pd

from backend.app.mobility.traffic.data import TrafficObservation

log = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/traffic_observations.db")

# Complete-snapshot row count: same constant used by ml/traffic/train.py
# (load_complete_snapshots) and verified live: 143,787 unique LinkIDs.
_COMPLETE_SNAPSHOT_ROWS = 143787

# Model contract: speed_lag_1..6 + current observation => 7 rows per link.
_HISTORY_PER_LINK = 7

# Live refresh cadence: aligned with the collector interval (5 minutes).
_REFRESH_INTERVAL_S = 300.0

# Upper bound for the startup walk-back over distinct timestamps.
_SEED_SCAN_LIMIT = 2000


@dataclass(frozen=True)
class PredictionBundle:
    """Immutable result of one prediction computation for one snapshot.

    Identical semantics to a single TrafficPredictor.predict_latest() call:
    both HTTP endpoints must read this instead of computing their own.
    """

    observed_at: str                       # real snapshot timestamp (never re-stamped)
    features_df: pd.DataFrame
    link_preds: List                       # List[LinkPrediction]
    diagnostics: Dict[str, Any]
    computed_at_epoch: float
    compute_seconds: float
    stage_times: Dict[str, float] = field(default_factory=dict)


class RollingObservationStore:
    """In-memory store exposing the API subset TrafficPredictor.predict_latest uses.

    Same facade contract as TrafficObservationCSVStore, backed by the rolling
    per-link deque history instead of the 1M-row CSV.
    """

    def __init__(self, service: "TrafficPredictionService") -> None:
        self._svc = service

    def get_latest_snapshot(self, limit: int = 1000) -> List[TrafficObservation]:
        return self._svc.latest_snapshot(limit)

    def get_link_history(
        self, link_ids: List[str], limit_per_link: int = 7
    ) -> List[TrafficObservation]:
        return self._svc.link_history(link_ids, limit_per_link)

    # ---- stubs for API parity (not used by the predictor; same as CSV store)
    def upsert_observations(self, observations):
        raise NotImplementedError("Rolling store is read-only")

    def query_by_timerange(self, *args, **kwargs):
        raise NotImplementedError("Rolling store only serves prediction inputs")

    def query_by_link_id(self, *args, **kwargs):
        raise NotImplementedError("Rolling store only serves prediction inputs")

    def get_stats(self) -> Dict[str, Any]:
        return self._svc.history_stats()


class TrafficPredictionService:
    """Owns rolling per-link history and the shared PredictionBundle.

    Threading model:
      - _history_lock  guards the deques (short critical sections only).
      - _compute_lock  is the single-flight gate: at most ONE prediction
        computation (feature build + Booster.predict) runs process-wide;
        concurrent cold-start requests and refresh triggers coalesce onto it.
      - the background worker thread (started by start()) seeds history from
        SQLite, computes the initial bundle, then on each refresh interval
        performs the live fetch_all_pages() cycle and recomputes. The slow
        LTA fetch and the ~2-minute CPU-bound computation NEVER run on a
        request thread.
    """

    def __init__(
        self,
        db_path: Path = _DEFAULT_DB_PATH,
        refresh_interval_s: float = _REFRESH_INTERVAL_S,
    ) -> None:
        self.db_path = Path(db_path)
        self.refresh_interval_s = refresh_interval_s
        # Live fetching can be disabled (tests/offline dev):
        self.fetch_enabled = os.getenv("URBANOS_TRAFFIC_PREDICTION_LIVE_FETCH", "1") != "0"

        self._history: Dict[str, Deque[TrafficObservation]] = {}
        self._history_lock = threading.Lock()
        self._compute_lock = threading.Lock()
        self._bundle: Optional[PredictionBundle] = None

        self._refresh_event = threading.Event()
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None

        self._predictor = None  # backend TrafficPredictor, created on first compute
        self._seeded = False
        self._latest_observed_at: Optional[str] = None

        # Observability (all real measurements, used by /internal status + tests)
        self.compute_count: int = 0
        self.fetch_count: int = 0
        self.last_stage_times: Dict[str, float] = {}
        self.last_error: Optional[str] = None

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Start the background seed+refresh worker (idempotent)."""
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(
            target=self._worker_main, name="traffic-prediction-service", daemon=True
        )
        self._worker.start()
        log.info("Traffic prediction service started (live fetch: %s)", self.fetch_enabled)

    def stop(self) -> None:
        self._stop_event.set()
        self._refresh_event.set()

    def _worker_main(self) -> None:
        try:
            self._seed_from_db()
        except Exception as e:
            self.last_error = f"seed failed: {e}"
            log.exception("Traffic prediction service: seeding from SQLite failed")

        while not self._stop_event.is_set():
            try:
                if self._seeded and self._bundle is None:
                    # Initial compute from seeded history (background).
                    self._recompute()

                triggered = self._refresh_event.wait(timeout=self.refresh_interval_s)
                self._refresh_event.clear()
                if self._stop_event.is_set():
                    break

                if triggered:
                    # A collector cycle already pushed a fresh snapshot.
                    self._recompute()
                elif self.fetch_enabled:
                    # No in-process collection happened: fetch live snapshot here,
                    # in this background thread (never in a request path).
                    self._live_fetch_cycle()
            except Exception as e:
                self.last_error = f"worker cycle failed: {e}"
                log.exception("Traffic prediction service worker cycle failed")

    # ------------------------------------------------------------------ live cycle

    def _live_fetch_cycle(self) -> None:
        """Fetch the complete live LTA snapshot, update history, recompute bundle."""
        from backend.app.mobility.traffic.api import TrafficSpeedBandsV2ApiClient
        from backend.app.mobility.traffic.data import snapshot_to_observations

        t0 = time.perf_counter()
        try:
            snapshot = TrafficSpeedBandsV2ApiClient().fetch_all_pages()
            fetch_s = time.perf_counter() - t0
            self.fetch_count += 1
            self.last_stage_times["lta_fetch_all_pages_s"] = fetch_s
            log.info(
                "Live LTA fetch_all_pages complete: %d segments in %.1fs",
                len(snapshot.segments), fetch_s,
            )
            observations = snapshot_to_observations(snapshot)
        except Exception as e:
            # Explicit, logged degradation: keep serving the stale bundle.
            self.last_error = f"live fetch failed: {e}"
            log.exception(
                "Traffic prediction service: live fetch failed; keeping previous bundle"
            )
            return

        self._update_history(observations)
        self._recompute()

    def on_new_snapshot(self, observations: List[TrafficObservation]) -> None:
        """Called after a successful collector cycle (any process component)."""
        try:
            self._update_history(observations)
            self._refresh_event.set()
        except Exception as e:
            self.last_error = f"history update failed: {e}"
            log.exception("Traffic prediction service: failed to ingest collector snapshot")

    # ------------------------------------------------------------------ history

    def _update_history(self, observations: List[TrafficObservation]) -> None:
        t0 = time.perf_counter()
        newest: Optional[str] = None
        updated = 0
        with self._history_lock:
            for obs in observations:
                dq = self._history.get(obs.link_id)
                if dq is None:
                    dq = self._history[obs.link_id] = deque(maxlen=_HISTORY_PER_LINK)
                # Skip duplicate / out-of-order rows for the same link.
                if dq and dq[-1].observed_at >= obs.observed_at:
                    continue
                dq.append(obs)
                updated += 1
                if newest is None or obs.observed_at > newest:
                    newest = obs.observed_at
            if newest is not None and (
                self._latest_observed_at is None or newest > self._latest_observed_at
            ):
                self._latest_observed_at = newest
        self.last_stage_times["history_update_s"] = time.perf_counter() - t0
        log.info(
            "Rolling history updated: %d observations appended, %d links tracked, latest=%s",
            updated, len(self._history), self._latest_observed_at,
        )

    def latest_snapshot(self, limit: int) -> List[TrafficObservation]:
        ts = self._latest_observed_at
        if ts is None:
            return []
        with self._history_lock:
            rows = [
                dq[-1]
                for dq in self._history.values()
                if dq and dq[-1].observed_at == ts
            ]
        return rows[:limit]

    def link_history(
        self, link_ids: List[str], limit_per_link: int
    ) -> List[TrafficObservation]:
        with self._history_lock:
            out: List[TrafficObservation] = []
            for lid in link_ids:
                dq = self._history.get(lid)
                if dq:
                    out.extend(list(dq)[-limit_per_link:])
        return out

    def history_stats(self) -> Dict[str, Any]:
        with self._history_lock:
            sizes = [len(dq) for dq in self._history.values()]
        return {
            "links_tracked": len(sizes),
            "observations_per_link_min": min(sizes) if sizes else 0,
            "observations_per_link_max": max(sizes) if sizes else 0,
            "latest_observed_at": self._latest_observed_at,
        }

    # ------------------------------------------------------------------ seeding

    def _seed_from_db(self) -> None:
        """Seed rolling history from the latest 7 COMPLETE snapshots in SQLite.

        Uses the verified indexed path only:
          - skip-scan timestamps via MAX(observed_at) seeks (idx_traffic_obs_timestamp),
          - per-candidate completeness via PK (observed_at=?) range count,
          - per-snapshot row fetch via PK range scan.
        No full-table scans, no window functions, read-only connection.
        """
        if not self.db_path.exists():
            log.warning("Traffic DB not found at %s; starting unseeded", self.db_path)
            self._seeded = True  # seeded with nothing; live fetches will populate
            return

        t0 = time.perf_counter()
        con = sqlite3.connect(
            f"file:{self.db_path.as_posix()}?mode=ro", uri=True
        )
        try:
            selected: List[str] = []
            checked = 0
            ts = con.execute(
                "SELECT MAX(observed_at) FROM traffic_observations"
            ).fetchone()[0]
            while ts is not None and len(selected) < _HISTORY_PER_LINK and checked < _SEED_SCAN_LIMIT:
                checked += 1
                cnt = con.execute(
                    "SELECT COUNT(*) FROM traffic_observations WHERE observed_at = ?",
                    (ts,),
                ).fetchone()[0]
                if cnt == _COMPLETE_SNAPSHOT_ROWS:
                    selected.append(ts)
                ts = con.execute(
                    "SELECT MAX(observed_at) FROM traffic_observations WHERE observed_at < ?",
                    (ts,),
                ).fetchone()[0]

            log.info(
                "Seed walk-back: %d timestamps checked, %d complete snapshots selected",
                checked, len(selected),
            )

            cols = (
                "observed_at, link_id, road_name, road_category, speed_band, "
                "minimum_speed, maximum_speed, speed_midpoint, "
                "start_latitude, start_longitude, end_latitude, end_longitude, "
                "zone_id, zone_name, created_at"
            )
            for snap_ts in reversed(selected):  # oldest-first for deque order
                rows = con.execute(
                    f"SELECT {cols} FROM traffic_observations WHERE observed_at = ?",
                    (snap_ts,),
                ).fetchall()
                observations = [
                    TrafficObservation(
                        observed_at=r[0], link_id=r[1], road_name=r[2],
                        road_category=r[3], speed_band=r[4], minimum_speed=r[5],
                        maximum_speed=r[6], speed_midpoint=r[7],
                        start_latitude=r[8], start_longitude=r[9],
                        end_latitude=r[10], end_longitude=r[11],
                        zone_id=r[12], zone_name=r[13], created_at=r[14],
                    )
                    for r in rows
                ]
                self._update_history(observations)
        finally:
            con.close()

        self._seeded = True
        self.last_stage_times["seed_from_db_s"] = time.perf_counter() - t0
        log.info(
            "Traffic prediction service seeded from SQLite in %.1fs: %s",
            time.perf_counter() - t0, self.history_stats(),
        )

    # ------------------------------------------------------------------ bundle

    def get_bundle(self) -> Optional[PredictionBundle]:
        """Return the latest bundle; on cold start compute it exactly once.

        Single-flight: concurrent callers block on _compute_lock and then share
        the one computed bundle. Returns None (existing no-data behaviour) when
        no history exists at all.
        """
        bundle = self._bundle
        if bundle is not None:
            return bundle
        if not self._seeded and not self._history:
            return None
        with self._compute_lock:
            # Re-check: another caller may have produced the bundle while we waited.
            if self._bundle is None:
                self._compute_locked()
            return self._bundle

    @property
    def bundle(self) -> Optional[PredictionBundle]:
        """Non-blocking read of the latest bundle (may be None)."""
        return self._bundle

    def _recompute(self) -> None:
        """Recompute the bundle after a fresh snapshot (single-flight)."""
        with self._compute_lock:
            self._compute_locked()

    def _compute_locked(self) -> None:
        """Run the prediction pipeline once. Caller must hold _compute_lock."""
        if not self._history:
            log.warning("Traffic prediction service: no history; nothing to compute")
            return

        stage: Dict[str, float] = {}
        t0 = time.perf_counter()
        try:
            if self._predictor is None:
                from backend.app.mobility.traffic.predictor import TrafficPredictor

                self._predictor = TrafficPredictor()

            store = RollingObservationStore(self)

            # Stage timers on the store facade (invoked inside predict_latest).
            orig_snapshot = store.get_latest_snapshot

            def timed_snapshot(limit: int = 1000):
                s = time.perf_counter()
                rows = orig_snapshot(limit)
                stage["store_latest_snapshot_s"] = time.perf_counter() - s
                return rows

            orig_history = store.get_link_history

            def timed_history(link_ids, limit_per_link: int = 7):
                s = time.perf_counter()
                rows = orig_history(link_ids, limit_per_link)
                stage["store_link_history_s"] = time.perf_counter() - s
                return rows

            store.get_latest_snapshot = timed_snapshot
            store.get_link_history = timed_history

            # Booster-load + inference timers (wrap the loaded Booster once).
            self._predictor._load_artifacts()
            booster = self._predictor._booster
            if not getattr(booster, "_urbanos_timed", False):
                orig_predict = booster.predict
                # Write directly into last_stage_times (not the per-compute
                # `stage` closure) so the timing stays correct on every pass.
                svc = self

                def timed_predict(data, *args, **kwargs):
                    s = time.perf_counter()
                    preds = orig_predict(data, *args, **kwargs)
                    svc.last_stage_times["xgb_inference_s"] = time.perf_counter() - s
                    return preds

                booster.predict = timed_predict
                booster._urbanos_timed = True

            features_df, link_preds, diagnostics = self._predictor.predict_latest(store)

            compute_s = time.perf_counter() - t0
            stage["predict_total_s"] = compute_s
            self.last_stage_times.update(stage)
            self.compute_count += 1

            self._bundle = PredictionBundle(
                observed_at=diagnostics["latest_observation_timestamp"],
                features_df=features_df,
                link_preds=link_preds,
                diagnostics=diagnostics,
                computed_at_epoch=time.time(),
                compute_seconds=compute_s,
                stage_times=dict(self.last_stage_times),
            )
            log.info(
                "PredictionBundle #%d computed in %.1fs (links=%d, observed_at=%s, stages=%s)",
                self.compute_count, compute_s, len(link_preds),
                diagnostics["latest_observation_timestamp"], stage,
            )
        except ValueError as e:
            # E.g. "No traffic observations available" — retain previous bundle.
            self.last_error = f"compute failed: {e}"
            log.warning("Traffic prediction service: %s; keeping previous bundle", e)
        except Exception as e:
            self.last_error = f"compute failed: {e}"
            log.exception("Traffic prediction service: bundle computation failed")

    # ------------------------------------------------------------------ status

    def status(self) -> Dict[str, Any]:
        bundle = self._bundle
        return {
            "seeded": self._seeded,
            "fetch_enabled": self.fetch_enabled,
            "compute_count": self.compute_count,
            "fetch_count": self.fetch_count,
            "bundle": None
            if bundle is None
            else {
                "observed_at": bundle.observed_at,
                "links_predicted": len(bundle.link_preds),
                "computed_at_epoch": bundle.computed_at_epoch,
                "age_seconds": round(time.time() - bundle.computed_at_epoch, 1),
                "compute_seconds": round(bundle.compute_seconds, 1),
            },
            "history": self.history_stats(),
            "last_stage_times": self.last_stage_times,
            "last_error": self.last_error,
        }


_SERVICE: Optional[TrafficPredictionService] = None
_SERVICE_LOCK = threading.Lock()


def get_traffic_prediction_service() -> TrafficPredictionService:
    """Process-wide singleton (lazy)."""
    global _SERVICE
    if _SERVICE is None:
        with _SERVICE_LOCK:
            if _SERVICE is None:
                _SERVICE = TrafficPredictionService()
    return _SERVICE
