"""SQLite storage for LTA Traffic Speed Bands v2 historical observations.

Supports:
- Timestamp queries
- LinkID queries
- Historical observations
- Duplicate prevention via upsert on (observed_at, link_id)
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))

_DEFAULT_DB_PATH = Path("data/traffic_observations.db")


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
        conn = sqlite3.connect(self.db_path)
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
        """Get storage statistics."""
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM traffic_observations").fetchone()[0]
            unique_links = conn.execute("SELECT COUNT(DISTINCT link_id) FROM traffic_observations").fetchone()[0]
            unique_zones = conn.execute("SELECT COUNT(DISTINCT zone_id) FROM traffic_observations WHERE zone_id IS NOT NULL").fetchone()[0]
            date_range = conn.execute(
                "SELECT MIN(observed_at), MAX(observed_at) FROM traffic_observations"
            ).fetchone()
            return {
                "total_observations": total,
                "unique_link_ids": unique_links,
                "unique_zones_mapped": unique_zones,
                "earliest_observation": date_range[0],
                "latest_observation": date_range[1],
            }

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