"""Traffic data models, collection, and storage."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from pydantic import BaseModel, Field
from typing import Literal

from backend.app.mobility.traffic.geo_zones import get_zone

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))
_DEFAULT_DB_PATH = Path("data/traffic_observations.db")

# Below this row count, exact DISTINCT scans used by get_stats() are cheap
# enough to run synchronously on every call.
_EXACT_SCAN_ROW_LIMIT = 200_000

_stats_refresh_lock = threading.Lock()
_stats_refresh_thread: Optional[threading.Thread] = None


# ============================================================
# MODELS (from models.py)
# ============================================================

class TrafficReport(BaseModel):
    """Structured traffic report combining ML predictions and live incidents."""
    generated_at: datetime
    prediction_horizon_minutes: int = 10
    overall_status: Literal["normal", "elevated", "disrupted", "unknown"] = "unknown"
    overall_average_speed: Optional[float] = None
    overall_predicted_speed: Optional[float] = None
    overall_speed_change_percent: Optional[float] = None
    overall_congestion_level: Literal["free_flow", "moderate", "heavy", "severe", "unknown"] = "unknown"
    zones: List[ZoneReport] = Field(default_factory=list)
    incidents: List[IncidentReport] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class ZoneReport(BaseModel):
    """Zone-level traffic summary."""
    zone_id: str
    zone_name: str
    is_demo_zone: bool = True
    current_average_speed: Optional[float] = None
    predicted_average_speed: Optional[float] = None
    speed_change: Optional[float] = None
    speed_change_percent: Optional[float] = None
    congestion_level: Literal["free_flow", "moderate", "heavy", "severe", "unknown"] = "unknown"
    segment_count: int = 0
    incident_count: int = 0


class IncidentReport(BaseModel):
    """Live traffic incident."""
    type: str
    message: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None


# ============================================================
# COLLECTOR (from collector.py)
# ============================================================

@dataclass
class CollectionResult:
    """Result of a single collection run."""
    timestamp: str
    records_received: int
    records_stored: int
    records_updated: int
    zones_mapped: int
    zones_unmapped: int
    errors: list[str]


class TrafficCollector:
    """Service for collecting and storing LTA Traffic Speed Bands v2 data."""

    def __init__(
        self,
        api_client: Optional["TrafficSpeedBandsV2ApiClient"] = None,
        store: Optional["TrafficObservationStore"] = None,
    ) -> None:
        # Import here to avoid circular import
        from backend.app.mobility.traffic.api import TrafficSpeedBandsV2ApiClient
        from backend.app.mobility.traffic.data import TrafficObservationStore
        
        self.api_client = api_client or TrafficSpeedBandsV2ApiClient()
        self.store = store or TrafficObservationStore()

    def collect_once(self) -> CollectionResult:
        """Perform one collection run: fetch, map zones, store."""
        errors: list[str] = []
        timestamp = datetime.now(SG_OFFSET).isoformat()

        try:
            # Import here to avoid circular import
            from backend.app.mobility.traffic.api import TrafficSpeedBandsV2Snapshot
            snapshot: TrafficSpeedBandsV2Snapshot = self.api_client.fetch_all_pages()
        except Exception as e:
            error_msg = f"API fetch failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)
            return CollectionResult(
                timestamp=timestamp,
                records_received=0,
                records_stored=0,
                records_updated=0,
                zones_mapped=0,
                zones_unmapped=0,
                errors=errors,
            )

        records_received = len(snapshot.segments)

        # Convert to storage observations
        observations = snapshot_to_observations(snapshot)

        # Count zone mappings
        zones_mapped = sum(1 for o in observations if o.zone_id is not None)
        zones_unmapped = records_received - zones_mapped

        # Store observations
        try:
            inserted, updated = self.store.upsert_observations(observations)
            records_stored = inserted + updated
        except Exception as e:
            error_msg = f"Storage upsert failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)
            return CollectionResult(
                timestamp=timestamp,
                records_received=records_received,
                records_stored=0,
                records_updated=0,
                zones_mapped=zones_mapped,
                zones_unmapped=zones_unmapped,
                errors=errors,
            )

        # Feed the successful snapshot into the shared traffic prediction
        # service: updates the rolling per-link history (deque maxlen=7) and
        # triggers a single-flight background PredictionBundle refresh.
        # A failure here must never break collection.
        try:
            from backend.app.mobility.traffic.prediction_service import (
                get_traffic_prediction_service,
            )
            get_traffic_prediction_service().on_new_snapshot(observations)
        except Exception:
            log.exception("Traffic prediction service hook failed")

        log.info(
            "Collection complete: received=%d, stored=%d (inserted=%d, updated=%d), "
            "zones_mapped=%d, zones_unmapped=%d",
            records_received, records_stored, inserted, updated, zones_mapped, zones_unmapped
        )

        return CollectionResult(
            timestamp=timestamp,
            records_received=records_received,
            records_stored=records_stored,
            records_updated=updated,
            zones_mapped=zones_mapped,
            zones_unmapped=zones_unmapped,
            errors=errors,
        )


def collect_traffic_once() -> CollectionResult:
    """Convenience function for scheduled collection runs."""
    collector = TrafficCollector()
    return collector.collect_once()


def get_collection_stats() -> Dict[str, Any]:
    """Get storage statistics."""
    store = TrafficObservationStore()
    return store.get_stats()


# ============================================================
# STORAGE (from storage.py)
# ============================================================

@dataclass
class TrafficObservation:
    """Stored traffic observation record."""
    observed_at: str
    link_id: str
    road_name: str
    road_category: str
    speed_band: int
    minimum_speed: Optional[float]
    maximum_speed: Optional[float]
    speed_midpoint: float
    start_latitude: Optional[float]
    start_longitude: Optional[float]
    end_latitude: Optional[float]
    end_longitude: Optional[float]
    zone_id: Optional[str]
    zone_name: Optional[str]
    created_at: str


class TrafficObservationStore:
    """SQLite-backed storage for traffic speed band observations."""

    def __init__(self, db_path: Path = _DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS traffic_observations (
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
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_traffic_obs_timestamp
                ON traffic_observations (observed_at DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_traffic_obs_link_id
                ON traffic_observations (link_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_traffic_obs_zone
                ON traffic_observations (zone_id)
            """)
            conn.commit()
        log.info("Traffic observation store initialized at %s", self.db_path)

    @contextmanager
    def _conn(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def upsert_observations(self, observations: List[TrafficObservation]) -> Tuple[int, int]:
        """Insert or update observations. Returns (inserted_count, updated_count)."""
        if not observations:
            return 0, 0

        inserted = 0
        updated = 0
        created_at = datetime.now(SG_OFFSET).isoformat()

        with self._conn() as conn:
            for obs in observations:
                # Check if exists
                existing = conn.execute(
                    "SELECT 1 FROM traffic_observations WHERE observed_at = ? AND link_id = ?",
                    (obs.observed_at, obs.link_id),
                ).fetchone()

                if existing:
                    conn.execute("""
                        UPDATE traffic_observations SET
                            road_name = ?,
                            road_category = ?,
                            speed_band = ?,
                            minimum_speed = ?,
                            maximum_speed = ?,
                            speed_midpoint = ?,
                            start_latitude = ?,
                            start_longitude = ?,
                            end_latitude = ?,
                            end_longitude = ?,
                            zone_id = ?,
                            zone_name = ?,
                            created_at = ?
                        WHERE observed_at = ? AND link_id = ?
                    """, (
                        obs.road_name, obs.road_category, obs.speed_band,
                        obs.minimum_speed, obs.maximum_speed, obs.speed_midpoint,
                        obs.start_latitude, obs.start_longitude,
                        obs.end_latitude, obs.end_longitude,
                        obs.zone_id, obs.zone_name, created_at,
                        obs.observed_at, obs.link_id,
                    ))
                    updated += 1
                else:
                    conn.execute("""
                        INSERT INTO traffic_observations (
                            observed_at, link_id, road_name, road_category,
                            speed_band, minimum_speed, maximum_speed, speed_midpoint,
                            start_latitude, start_longitude, end_latitude, end_longitude,
                            zone_id, zone_name, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        obs.observed_at, obs.link_id, obs.road_name, obs.road_category,
                        obs.speed_band, obs.minimum_speed, obs.maximum_speed, obs.speed_midpoint,
                        obs.start_latitude, obs.start_longitude,
                        obs.end_latitude, obs.end_longitude,
                        obs.zone_id, obs.zone_name, created_at,
                    ))
                    inserted += 1
            conn.commit()

        log.info("Upserted %d observations (%d inserted, %d updated)", len(observations), inserted, updated)
        return inserted, updated

    def query_by_timerange(
        self,
        start_time: str,
        end_time: str,
        link_id: Optional[str] = None,
        zone_id: Optional[str] = None,
        limit: int = 10000,
    ) -> List[TrafficObservation]:
        """Query observations within a time range."""
        sql = """
            SELECT * FROM traffic_observations
            WHERE observed_at >= ? AND observed_at <= ?
        """
        params: List[Any] = [start_time, end_time]

        if link_id:
            sql += " AND link_id = ?"
            params.append(link_id)
        if zone_id:
            sql += " AND zone_id = ?"
            params.append(zone_id)

        sql += " ORDER BY observed_at DESC LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_obs(row) for row in rows]

    def query_by_link_id(
        self,
        link_id: str,
        limit: int = 1000,
    ) -> List[TrafficObservation]:
        """Query all observations for a specific link_id."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM traffic_observations WHERE link_id = ? ORDER BY observed_at DESC LIMIT ?",
                (link_id, limit),
            ).fetchall()
            return [self._row_to_obs(row) for row in rows]

    def get_latest_snapshot(self, limit: int = 1000) -> List[TrafficObservation]:
        """Get the most recent observations (latest snapshot)."""
        with self._conn() as conn:
            # Get the latest timestamp
            latest_ts = conn.execute(
                "SELECT MAX(observed_at) FROM traffic_observations"
            ).fetchone()

            if not latest_ts or not latest_ts[0]:
                return []

            rows = conn.execute(
                "SELECT * FROM traffic_observations WHERE observed_at = ? LIMIT ?",
                (latest_ts[0], limit),
            ).fetchall()
            return [self._row_to_obs(row) for row in rows]

    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics.

        Performance notes (the table is large; currently ~51 GB / >100M rows):
        - ``COUNT(*)`` is replaced by ``MAX(rowid)``: the table is strictly
          append-only (nothing ever deletes from it), so they are equal.
          ``MAX(rowid)`` is an O(1) b-tree leaf lookup; ``COUNT(*)`` requires
          a full table scan (minutes at this size).
        - ``MIN(observed_at)`` / ``MAX(observed_at)`` are issued as two
          separate single-aggregate queries so SQLite uses
          ``idx_traffic_obs_timestamp`` for both. A combined
          ``SELECT MIN(...), MAX(...)`` disables SQLite's MIN/MAX index
          optimization and forces a full table scan.
        - The distinct-count queries require index scans that take minutes
          on a large table, so for large tables they are computed once and
          cached in a sidecar JSON file next to the DB, refreshed in a
          background thread whenever the row count changes.
        """
        with self._conn() as conn:
            total = conn.execute(
                "SELECT MAX(rowid) FROM traffic_observations"
            ).fetchone()[0] or 0
            earliest = conn.execute(
                "SELECT MIN(observed_at) FROM traffic_observations"
            ).fetchone()[0]
            latest = conn.execute(
                "SELECT MAX(observed_at) FROM traffic_observations"
            ).fetchone()[0]

        if total == 0:
            unique_links = 0
            unique_zones = 0
        elif total <= _EXACT_SCAN_ROW_LIMIT:
            unique_links, unique_zones = self._compute_distinct_counts()
        else:
            unique_links, unique_zones = self._get_cached_distinct_counts(total)

        return {
            "total_observations": total,
            "unique_link_ids": unique_links,
            "unique_zones_mapped": unique_zones,
            "earliest_observation": earliest,
            "latest_observation": latest,
        }

    def _compute_distinct_counts(self) -> Tuple[int, int]:
        """Exact distinct counts. Requires full index scans (slow on large tables)."""
        with self._conn() as conn:
            unique_links = conn.execute(
                "SELECT COUNT(DISTINCT link_id) FROM traffic_observations"
            ).fetchone()[0]
            unique_zones = conn.execute(
                "SELECT COUNT(DISTINCT zone_id) FROM traffic_observations WHERE zone_id IS NOT NULL"
            ).fetchone()[0]
        return unique_links, unique_zones

    def _stats_cache_path(self) -> Path:
        return Path(str(self.db_path) + ".stats_cache.json")

    def _get_cached_distinct_counts(self, total: int) -> Tuple[int, int]:
        """Serve exact distinct counts from the sidecar cache.

        The cache is keyed on the table's total row count: this table is
        strictly append-only, so a matching row count proves the cache is
        still exact for the current data.
        """
        cache_path = self._stats_cache_path()

        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                if data.get("total_observations") == total:
                    return int(data["unique_link_ids"]), int(data["unique_zones_mapped"])
                last_known = (int(data["unique_link_ids"]), int(data["unique_zones_mapped"]))
            except Exception:
                log.warning("Invalid traffic stats cache at %s; recomputing", cache_path)
                last_known = None
        else:
            last_known = None
            data = {}

        # Cache is missing or stale: recompute in the background (once).
        self._start_stats_refresh(cache_path, total)

        if last_known is not None:
            # Serve last known values while the refresh runs.
            return last_known

        # First-ever call on a large table with no cache: one synchronous
        # computation (minutes), after which all calls are instant.
        log.info(
            "Traffic stats cache missing; computing distinct counts synchronously (one-off)."
        )
        return self._compute_distinct_counts()

    def _start_stats_refresh(self, cache_path: Path, total: int) -> None:
        """Refresh the distinct-count stats cache in a background thread."""
        global _stats_refresh_thread

        with _stats_refresh_lock:
            if _stats_refresh_thread is not None and _stats_refresh_thread.is_alive():
                return

            def _refresh() -> None:
                try:
                    unique_links, unique_zones = self._compute_distinct_counts()
                    tmp_path = cache_path.with_suffix(".tmp")
                    tmp_path.write_text(
                        json.dumps({
                            "total_observations": total,
                            "unique_link_ids": unique_links,
                            "unique_zones_mapped": unique_zones,
                        }),
                        encoding="utf-8",
                    )
                    os.replace(tmp_path, cache_path)
                    log.info(
                        "Refreshed traffic stats cache: unique_links=%d unique_zones=%d",
                        unique_links, unique_zones,
                    )
                except Exception:
                    log.exception("Failed to refresh traffic stats cache")

            _stats_refresh_thread = threading.Thread(
                target=_refresh, name="traffic-stats-refresh", daemon=True
            )
            _stats_refresh_thread.start()

    def _row_to_obs(self, row: sqlite3.Row) -> TrafficObservation:
        return TrafficObservation(
            observed_at=row["observed_at"],
            link_id=row["link_id"],
            road_name=row["road_name"],
            road_category=row["road_category"],
            speed_band=row["speed_band"],
            minimum_speed=row["minimum_speed"],
            maximum_speed=row["maximum_speed"],
            speed_midpoint=row["speed_midpoint"],
            start_latitude=row["start_latitude"],
            start_longitude=row["start_longitude"],
            end_latitude=row["end_latitude"],
            end_longitude=row["end_longitude"],
            zone_id=row["zone_id"],
            zone_name=row["zone_name"],
            created_at=row["created_at"],
        )

    def get_link_history(
        self,
        link_ids: List[str],
        limit_per_link: int = 7,
    ) -> List[TrafficObservation]:
        """Get last N observations for each link_id (replaces raw SQL window function)."""
        if not link_ids:
            return []
        placeholders = ','.join('?' for _ in link_ids)
        query = f"""
            WITH ranked AS (
                SELECT observed_at, link_id, road_name, road_category, speed_band,
                       minimum_speed, maximum_speed, speed_midpoint,
                       start_latitude, start_longitude, end_latitude, end_longitude,
                       zone_id, zone_name, created_at,
                       ROW_NUMBER() OVER (PARTITION BY link_id ORDER BY observed_at DESC) as rn
                FROM traffic_observations
                WHERE link_id IN ({placeholders})
            )
            SELECT observed_at, link_id, road_name, road_category, speed_band,
                   minimum_speed, maximum_speed, speed_midpoint,
                   start_latitude, start_longitude, end_latitude, end_longitude,
                   zone_id, zone_name, created_at
            FROM ranked WHERE rn <= ?
            ORDER BY link_id, observed_at DESC
        """
        params = link_ids + [limit_per_link]
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_obs(row) for row in rows]

    def export_latest_seven_per_link(self, csv_path: Path) -> None:
        """
        Export the latest 7 real observations for EVERY link_id
        from the SQLite table into a CSV that matches the exact
        schema expected by TrafficObservationCSVStore.
        The query uses a window function and streams rows
        without ever materialising the full result set.
        The CSV is written atomically via a temporary file.
        """
        import csv
        import os
        from pathlib import Path

        tmp_path = Path(str(csv_path) + ".tmp")
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        sql = """
            WITH ranked AS (
                SELECT
                    observed_at,
                    link_id,
                    road_name,
                    road_category,
                    speed_band,
                    minimum_speed,
                    maximum_speed,
                    speed_midpoint,
                    start_latitude,
                    start_longitude,
                    end_latitude,
                    end_longitude,
                    zone_id,
                    zone_name,
                    ROW_NUMBER() OVER (
                        PARTITION BY link_id
                        ORDER BY observed_at DESC
                    ) AS rn
                FROM traffic_observations
            )
            SELECT
                observed_at,
                link_id,
                road_name,
                road_category,
                speed_band,
                minimum_speed,
                maximum_speed,
                speed_midpoint,
                start_latitude,
                start_longitude,
                end_latitude,
                end_longitude,
                zone_id,
                zone_name
            FROM ranked
            WHERE rn <= 7
            ORDER BY observed_at, link_id;
        """

        total_rows = 0
        with self._conn() as con, open(tmp_path, "w", newline="", encoding="utf-8") as tmp_f:
            writer = csv.writer(tmp_f)
            writer.writerow([
                "observed_at", "link_id", "road_name", "road_category", "speed_band",
                "minimum_speed", "maximum_speed", "speed_midpoint",
                "start_latitude", "start_longitude",
                "end_latitude", "end_longitude",
                "zone_id", "zone_name"
            ])

            cur = con.execute(sql)

            for row in cur:
                writer.writerow(row)
                total_rows += 1

        # Atomic replace only after successful write
        os.replace(str(csv_path) + ".tmp", csv_path)
        log.info("CSV cache rebuilt – %d rows written", total_rows)

    def export_to_csv(self, csv_path: Path) -> None:
        """Export all observations to CSV for prediction cache."""
        query = """
            SELECT observed_at, link_id, road_name, road_category, speed_band,
                   minimum_speed, maximum_speed, speed_midpoint,
                   start_latitude, start_longitude, end_latitude, end_longitude,
                   zone_id, zone_name
            FROM traffic_observations
            ORDER BY observed_at, link_id
        """
        with self._conn() as conn:
            rows = conn.execute(query).fetchall()
        # Convert to DataFrame
        df = pd.DataFrame([dict(row) for row in rows])
        # Ensure column order matches CSV store expectations
        cols = [
            "observed_at", "link_id", "road_name", "road_category", "speed_band",
            "minimum_speed", "maximum_speed", "speed_midpoint",
            "start_latitude", "start_longitude", "end_latitude", "end_longitude",
            "zone_id", "zone_name"
        ]
        df = df[cols]
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(csv_path, index=False)
        log.info("Exported %d observations to CSV: %s", len(df), csv_path)


_DEFAULT_CSV_PATH = Path("data/traffic/traffic_observations.csv")


class TrafficObservationCSVStore:
    """CSV-backed storage for traffic speed band observations (read-only, for fast prediction)."""

    def __init__(self, csv_path: Path = _DEFAULT_CSV_PATH) -> None:
        self.csv_path = csv_path
        self._df: Optional[pd.DataFrame] = None
        self._load_csv()

    def _load_csv(self) -> None:
        """Load CSV into memory."""
        if not self.csv_path.exists():
            log.warning("Traffic CSV not found at %s, will use empty DataFrame", self.csv_path)
            self._df = pd.DataFrame(columns=[
                "observed_at", "link_id", "road_name", "road_category", "speed_band",
                "minimum_speed", "maximum_speed", "speed_midpoint",
                "start_latitude", "start_longitude", "end_latitude", "end_longitude",
                "zone_id", "zone_name"
            ])
            return
        
        log.info("Loading traffic observations from CSV: %s", self.csv_path)
        self._df = pd.read_csv(self.csv_path, dtype={"link_id": str})
        # Ensure observed_at is string (already ISO format from export)
        if "observed_at" in self._df.columns:
            self._df["observed_at"] = self._df["observed_at"].astype(str)
        # Ensure link_id is string
        if "link_id" in self._df.columns:
            self._df["link_id"] = self._df["link_id"].astype(str)
        log.info("Loaded %d observations for %d unique links from CSV",
                 len(self._df), self._df["link_id"].nunique() if "link_id" in self._df.columns else 0)

    def _row_to_obs(self, row: pd.Series) -> TrafficObservation:
        return TrafficObservation(
            observed_at=row["observed_at"],
            link_id=str(row["link_id"]),
            road_name=str(row["road_name"]),
            road_category=str(row["road_category"]),
            speed_band=int(row["speed_band"]),
            minimum_speed=float(row["minimum_speed"]) if pd.notna(row["minimum_speed"]) else None,
            maximum_speed=float(row["maximum_speed"]) if pd.notna(row["maximum_speed"]) else None,
            speed_midpoint=float(row["speed_midpoint"]),
            start_latitude=float(row["start_latitude"]) if pd.notna(row["start_latitude"]) else None,
            start_longitude=float(row["start_longitude"]) if pd.notna(row["start_longitude"]) else None,
            end_latitude=float(row["end_latitude"]) if pd.notna(row["end_latitude"]) else None,
            end_longitude=float(row["end_longitude"]) if pd.notna(row["end_longitude"]) else None,
            zone_id=str(row["zone_id"]) if pd.notna(row["zone_id"]) else None,
            zone_name=str(row["zone_name"]) if pd.notna(row["zone_name"]) else None,
            created_at=row["observed_at"],  # Use observed_at as created_at for CSV data
        )

    def get_latest_snapshot(self, limit: int = 1000) -> List[TrafficObservation]:
        """Get the most recent observations (latest snapshot)."""
        if self._df is None or self._df.empty:
            return []
        
        latest_ts = self._df["observed_at"].max()
        latest_rows = self._df[self._df["observed_at"] == latest_ts].head(limit)
        return [self._row_to_obs(row) for _, row in latest_rows.iterrows()]

    def get_link_history(
        self,
        link_ids: List[str],
        limit_per_link: int = 7,
    ) -> List[TrafficObservation]:
        """Get last N observations for each link_id (fast in-memory operation)."""
        if self._df is None or self._df.empty or not link_ids:
            return []
        
        # Filter for requested link_ids
        mask = self._df["link_id"].isin(link_ids)
        filtered = self._df[mask].copy()
        
        if filtered.empty:
            return []
        
        # Sort by link_id, observed_at DESC and take first N per link
        filtered = filtered.sort_values(["link_id", "observed_at"], ascending=[True, False])
        filtered = filtered.groupby("link_id").head(limit_per_link)
        
        return [self._row_to_obs(row) for _, row in filtered.iterrows()]

    # Stub methods for compatibility (not used by predictor)
    def upsert_observations(self, observations: List[TrafficObservation]) -> Tuple[int, int]:
        raise NotImplementedError("CSV store is read-only")

    def query_by_timerange(self, *args, **kwargs) -> List[TrafficObservation]:
        raise NotImplementedError("Use get_link_history for prediction")

    def query_by_link_id(self, *args, **kwargs) -> List[TrafficObservation]:
        raise NotImplementedError("Use get_link_history for prediction")

    def get_stats(self) -> Dict[str, Any]:
        if self._df is None or self._df.empty:
            return {"total_observations": 0, "unique_link_ids": 0, "unique_zones_mapped": 0}
        return {
            "total_observations": len(self._df),
            "unique_link_ids": self._df["link_id"].nunique(),
            "unique_zones_mapped": self._df["zone_id"].nunique() if "zone_id" in self._df.columns else 0,
            "earliest_observation": self._df["observed_at"].min(),
            "latest_observation": self._df["observed_at"].max(),
        }


def snapshot_to_observations(snapshot) -> List[TrafficObservation]:
    """Convert a TrafficSpeedBandsV2Snapshot to a list of TrafficObservation."""
    return [
        TrafficObservation(
            observed_at=s.observed_at,
            link_id=s.link_id,
            road_name=s.road_name,
            road_category=s.road_category,
            speed_band=s.speed_band,
            minimum_speed=s.minimum_speed,
            maximum_speed=s.maximum_speed,
            speed_midpoint=s.speed_midpoint,
            start_latitude=s.start_latitude,
            start_longitude=s.start_longitude,
            end_latitude=s.end_latitude,
            end_longitude=s.end_longitude,
            zone_id=s.zone_id,
            zone_name=s.zone_name,
            created_at=datetime.now(SG_OFFSET).isoformat(),
        )
        for s in snapshot.segments
    ]