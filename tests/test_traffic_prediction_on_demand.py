"""Focused tests for the on-demand Traffic prediction pipeline.

Covers the regression where /api/traffic/predict and /api/traffic/report
returned HTTP 500 after app startup stopped launching the prediction
service: the service must now be initialized on demand (idempotent
start), seed rolling history from the real SQLite store (resolved from
the repository root, not the process CWD), and both endpoints must
degrade honestly instead of raising.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backend.app.mobility.traffic import prediction_service as ps_module
from backend.app.mobility.traffic.data import TrafficObservation
from backend.app.mobility.traffic.predictor import LinkPrediction
from backend.app.mobility.traffic.prediction_service import (
    _DEFAULT_DB_PATH,
    TrafficPredictionService,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _observed_at(minutes: int) -> str:
    # ISO strings sort lexicographically like timestamps with the same prefix.
    return f"2026-10-24T08:{minutes:02d}:00+08:00"


def _observation(link_id: str, observed_at: str, speed: float) -> TrafficObservation:
    return TrafficObservation(
        observed_at=observed_at,
        link_id=link_id,
        road_name=f"Road {link_id}",
        road_category="1",
        speed_band=4,
        minimum_speed=speed - 5.0,
        maximum_speed=speed + 5.0,
        speed_midpoint=speed,
        start_latitude=1.30,
        start_longitude=103.80,
        end_latitude=1.31,
        end_longitude=103.81,
        zone_id="SG_NORTH",
        zone_name="North",
        created_at=observed_at,
    )


def _create_temp_db(path: Path, snapshots: int, links: int = 3) -> None:
    """Create a small observation store the seed walk-back can consume."""
    con = sqlite3.connect(path)
    try:
        con.execute(
            """
            CREATE TABLE traffic_observations (
                observed_at TEXT NOT NULL,
                link_id TEXT NOT NULL,
                road_name TEXT NOT NULL,
                road_category TEXT NOT NULL,
                speed_band INTEGER NOT NULL,
                minimum_speed REAL,
                maximum_speed REAL,
                speed_midpoint REAL NOT NULL,
                start_latitude REAL,
                start_longitude REAL,
                end_latitude REAL,
                end_longitude REAL,
                zone_id TEXT,
                zone_name TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (observed_at, link_id)
            )
            """
        )
        rows = []
        for snap in range(snapshots):
            ts = _observed_at(snap)
            for link in range(links):
                obs = _observation(str(link), ts, 40.0 + link + snap)
                rows.append((
                    obs.observed_at, obs.link_id, obs.road_name,
                    obs.road_category, obs.speed_band, obs.minimum_speed,
                    obs.maximum_speed, obs.speed_midpoint, obs.start_latitude,
                    obs.start_longitude, obs.end_latitude, obs.end_longitude,
                    obs.zone_id, obs.zone_name, obs.created_at,
                ))
        con.executemany(
            "INSERT INTO traffic_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        con.commit()
    finally:
        con.close()


class _FakePredictor:
    """Stands in for the XGBoost predictor: no model file, no compute cost."""

    def __init__(self, link_preds=None, error=None):
        self._link_preds = link_preds or []
        self._error = error
        self._booster = SimpleNamespace(predict=lambda data, *a, **k: [], _urbanos_timed=True)

    def _load_artifacts(self):
        if self._error is not None:
            raise self._error

    def predict_latest(self, store):
        if self._error is not None:
            raise self._error
        diagnostics = {
            "links_predicted": len(self._link_preds),
            "latest_observation_timestamp": "2026-10-24T08:09:00+08:00",
            "model": "xgboost",
            "feature_count": 34,
        }
        return pd.DataFrame(), list(self._link_preds), diagnostics


def _fake_link(link_id: str = "1") -> LinkPrediction:
    return LinkPrediction(
        link_id=link_id,
        road_name="Road",
        road_category="1",
        zone_id="SG_NORTH",
        zone_name="North",
        current_speed=50.0,
        predicted_speed=52.0,
        speed_change=2.0,
        prediction_timestamp="2026-10-24T08:09:00+08:00",
        target_timestamp="2026-10-24T08:14:00+08:00",
    )


def _wait_for_bundle(service: TrafficPredictionService, timeout_s: float = 15.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        bundle = service.get_bundle()
        if bundle is not None:
            return bundle
        time.sleep(0.05)
    return None


@pytest.fixture()
def no_live_fetch(monkeypatch):
    monkeypatch.setenv("URBANOS_TRAFFIC_PREDICTION_LIVE_FETCH", "0")


# ---------------------------------------------------------------------------
# artifact path resolution
# ---------------------------------------------------------------------------

class TestDefaultDbPath:
    def test_default_db_path_is_cwd_independent(self):
        """The seed store must resolve from the repo root, not the CWD.

        A server started from backend/ previously seeded from an empty
        look-alike DB created at backend/data/traffic_observations.db.
        """
        assert _DEFAULT_DB_PATH.is_absolute()
        repo_root = Path(__file__).resolve().parents[1]
        assert _DEFAULT_DB_PATH == repo_root / "data" / "traffic_observations.db"

    def test_default_db_path_matches_predictor_repo_root(self):
        """Model artifacts and the seed store resolve from the same repo root."""
        from backend.app.mobility.traffic.predictor import (
            MODEL_PATH, REPO_ROOT,
        )

        assert _DEFAULT_DB_PATH.parents[1] == REPO_ROOT
        assert MODEL_PATH.parents[4] == REPO_ROOT


# ---------------------------------------------------------------------------
# on-demand lifecycle
# ---------------------------------------------------------------------------

class TestOnDemandStart:
    def test_start_is_idempotent_under_concurrent_calls(self, tmp_path, no_live_fetch):
        """Concurrent first requests must spawn exactly one worker."""
        service = TrafficPredictionService(db_path=tmp_path / "missing.db")

        barrier = threading.Barrier(8)

        def _caller():
            barrier.wait()
            service.start()

        threads = [threading.Thread(target=_caller) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert service._worker is not None and service._worker.is_alive()
        # Second round of starts must not replace the live worker.
        first_worker = service._worker
        service.start()
        assert service._worker is first_worker
        service.stop()
        service._worker.join(timeout=5)

    def test_get_bundle_returns_none_while_seeding(self, tmp_path, monkeypatch, no_live_fetch):
        """No bundle may be served (or computed) from a partial seed."""
        db = tmp_path / "obs.db"
        _create_temp_db(db, snapshots=2, links=3)
        monkeypatch.setattr(ps_module, "_COMPLETE_SNAPSHOT_ROWS", 3)

        entered = threading.Event()
        release = threading.Event()

        original = TrafficPredictionService._seed_walk_back

        def blocking_seed(self):
            entered.set()
            release.wait(timeout=10)
            original(self)

        service = TrafficPredictionService(db_path=db)
        with patch.object(TrafficPredictionService, "_seed_walk_back", blocking_seed), \
             patch("backend.app.mobility.traffic.predictor.TrafficPredictor",
                   lambda *a, **k: _FakePredictor([_fake_link()])):
            service.start()
            assert entered.wait(timeout=5), "seed must have started"
            assert service._seeding is True
            # Cold-start request during seeding: honest None, no partial compute.
            assert service.get_bundle() is None
            release.set()
            bundle = _wait_for_bundle(service)
            assert bundle is not None and bundle.link_preds

        service.stop()
        service._worker.join(timeout=5)

    def test_seed_from_db_populates_history_and_computes_bundle(
        self, tmp_path, monkeypatch, no_live_fetch
    ):
        """The on-demand worker seeds from the SQLite store and computes the
        shared bundle exactly once, reusing it for subsequent reads."""
        db = tmp_path / "obs.db"
        _create_temp_db(db, snapshots=2, links=3)
        # Treat a 3-row snapshot as complete for this small fixture.
        monkeypatch.setattr(ps_module, "_COMPLETE_SNAPSHOT_ROWS", 3)

        service = TrafficPredictionService(db_path=db)
        fake = _FakePredictor([_fake_link(str(i)) for i in range(3)])
        with patch("backend.app.mobility.traffic.predictor.TrafficPredictor", lambda *a, **k: fake):
            service.start()
            bundle = _wait_for_bundle(service)

        assert bundle is not None, "worker must compute the initial bundle after seeding"
        assert service._seeded is True
        assert len(bundle.link_preds) == 3
        assert bundle.observed_at == "2026-10-24T08:09:00+08:00"
        stats = service.history_stats()
        assert stats["links_tracked"] == 3
        assert stats["observations_per_link_max"] == 2
        # The bundle is reused, not recomputed per request.
        assert service.get_bundle() is bundle
        assert service.compute_count == 1

        service.stop()
        service._worker.join(timeout=5)

    def test_compute_failure_is_logged_and_keeps_bundle_none(
        self, tmp_path, monkeypatch, no_live_fetch
    ):
        """An invalid/failed prediction computation must not fabricate a
        bundle: last_error is set and callers keep the honest None."""
        db = tmp_path / "obs.db"
        _create_temp_db(db, snapshots=2, links=3)
        monkeypatch.setattr(ps_module, "_COMPLETE_SNAPSHOT_ROWS", 3)

        service = TrafficPredictionService(db_path=db)
        broken = _FakePredictor(error=ValueError("No traffic observations available"))
        with patch("backend.app.mobility.traffic.predictor.TrafficPredictor", lambda *a, **k: broken):
            service.start()
            deadline = time.time() + 10
            while time.time() < deadline and service.last_error is None:
                time.sleep(0.05)

        assert service.last_error is not None
        assert "No traffic observations available" in service.last_error
        assert service.bundle is None
        assert service.get_bundle() is None

        service.stop()
        service._worker.join(timeout=5)

    def test_missing_db_starts_unseeded_and_reports_honestly(self, tmp_path, no_live_fetch):
        """No SQLite store: the service reports unseeded instead of inventing data."""
        service = TrafficPredictionService(db_path=tmp_path / "missing.db")
        service.start()

        deadline = time.time() + 5
        while time.time() < deadline and not service._seeded:
            time.sleep(0.05)

        assert service._seeded is True
        assert service.history_stats()["links_tracked"] == 0
        assert service.get_bundle() is None
        status = service.status()
        assert status["seeded"] is True
        assert status["worker_running"] is True

        service.stop()
        service._worker.join(timeout=5)


# ---------------------------------------------------------------------------
# endpoint contract
# ---------------------------------------------------------------------------

class _StubService:
    def __init__(self, bundle):
        self._bundle = bundle
        self.started = 0

    def start(self):
        self.started += 1

    def get_bundle(self):
        return self._bundle

    def status(self):
        return {
            "seeded": False,
            "seeding": False,
            "worker_running": False,
            "fetch_enabled": False,
            "db_path": "stub",
            "compute_count": 0,
            "fetch_count": 0,
            "bundle": None,
            "history": {"links_tracked": 0},
            "last_stage_times": {},
            "last_error": None,
        }


class TestTrafficPredictEndpoint:
    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from backend.app.main import _build_app

        app = _build_app()
        return TestClient(app)

    def test_503_with_structured_detail_when_bundle_missing(self, client):
        """Cold start: no bundle yet -> honest 503, never a 500."""
        stub = _StubService(bundle=None)
        with patch("backend.app.main.get_traffic_prediction_service", return_value=stub):
            resp = client.get("/api/traffic/predict")

        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert detail["reason"] == "prediction_bundle_unavailable"
        assert detail["message"]
        assert "service_status" in detail
        # On-demand initialization happened inside the request.
        assert stub.started == 1

    def test_503_when_bundle_has_no_link_predictions(self, client):
        """An empty bundle is unavailable, not a success with no content."""
        stub = _StubService(bundle=ps_module.PredictionBundle(
            observed_at="2026-10-24T08:09:00+08:00",
            features_df=pd.DataFrame(),
            link_preds=[],
            diagnostics={},
            computed_at_epoch=0.0,
            compute_seconds=0.0,
        ))
        with patch("backend.app.main.get_traffic_prediction_service", return_value=stub):
            resp = client.get("/api/traffic/predict")

        assert resp.status_code == 503
        assert resp.json()["detail"]["reason"] == "prediction_bundle_unavailable"

    def test_valid_bundle_serves_full_schema(self, client):
        """Warm service: the full prediction payload is served unchanged."""
        bundle = ps_module.PredictionBundle(
            observed_at="2026-10-24T08:09:00+08:00",
            features_df=pd.DataFrame(),
            link_preds=[
                _fake_link("1"),
                LinkPrediction(
                    link_id="2", road_name="Road", road_category="1",
                    zone_id="SG_EAST", zone_name="East",
                    current_speed=60.0, predicted_speed=58.0, speed_change=-2.0,
                    prediction_timestamp="2026-10-24T08:09:00+08:00",
                    target_timestamp="2026-10-24T08:14:00+08:00",
                ),
            ],
            diagnostics={"links_predicted": 2, "model": "xgboost"},
            computed_at_epoch=0.0,
            compute_seconds=0.0,
        )
        stub = _StubService(bundle=bundle)
        with patch("backend.app.main.get_traffic_prediction_service", return_value=stub):
            resp = client.get("/api/traffic/predict")

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["is_ml_model"] is True
        assert payload["prediction_horizon_minutes"] == 5
        assert len(payload["link_predictions"]) == 2
        divisions = {d["division"] for d in payload["divisions"]}
        assert divisions == {"Central", "East", "North", "North-East", "West"}
        north = next(d for d in payload["divisions"] if d["division"] == "North")
        east = next(d for d in payload["divisions"] if d["division"] == "East")
        assert north["segment_count"] == 1 and east["segment_count"] == 1
        central = next(d for d in payload["divisions"] if d["division"] == "Central")
        assert central["segment_count"] == 0 and central["congestion_level"] == "unknown"


class TestTrafficReportEndpoint:
    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from backend.app.main import _build_app

        app = _build_app()
        return TestClient(app)

    def test_report_served_when_agent_produces_one(self, client):
        from datetime import datetime

        from backend.app.mobility.traffic.data import TrafficReport

        report = TrafficReport(
            generated_at=datetime.now(),
            overall_status="unknown",
            overall_congestion_level="unknown",
        )
        with patch("backend.app.mobility.traffic.agent.run_traffic_agent", return_value=report):
            resp = client.get("/api/traffic/report")

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["overall_status"] == "unknown"
        assert payload["zones"] == [] and payload["incidents"] == []

    def test_report_endpoint_500_only_on_unexpected_crash(self, client):
        with patch(
            "backend.app.mobility.traffic.agent.run_traffic_agent",
            side_effect=RuntimeError("agent crashed"),
        ):
            resp = client.get("/api/traffic/report")

        assert resp.status_code == 500
        assert "agent crashed" in resp.json()["detail"]
