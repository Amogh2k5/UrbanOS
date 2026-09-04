"""SQLite storage for NEA PM2.5 hourly observations.

Supports:
- Hourly observation queries
- LinkID equivalent (region) queries
- Duplicate prevention via upsert on (observed_at, region)
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

_DEFAULT_DB_PATH = Path("data/pm25_observations.db")


@dataclass
class Pm25Observation:
    """Stored PM2.5 observation record."""
    observed_at: str              # ISO +08:00 — NEA observation timestamp
    region: str                   # north/south/east/west/central
    value: float                  # µg/m3
    unit: str                     # µg/m3
    source: str                   # "live_api:NEA_pm25"
    created_at: str               # ISO +08:00 — when we stored it


class Pm25ObservationStore:
    """SQLite-backed storage for PM2.5 observations."""

    def __init__(self, db_path: Path = _DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pm25_observations (
                    observed_at TEXT NOT NULL,
                    region TEXT NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (observed_at, region)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pm25_obs_timestamp
                ON pm25_observations (observed_at DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pm25_obs_region
                ON pm25_observations (region)
            """)
            conn.commit()
        log.info("PM2.5 observation store initialized at %s", self.db_path)

    @contextmanager
    def _conn(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def upsert_observations(self, observations: List[Pm25Observation]) -> Tuple[int, int]:
        """Insert or update observations. Returns (inserted_count, updated_count)."""
        if not observations:
            return 0, 0

        inserted = 0
        updated = 0

        with self._conn() as conn:
            for obs in observations:
                existing = conn.execute(
                    "SELECT 1 FROM pm25_observations WHERE observed_at = ? AND region = ?",
                    (obs.observed_at, obs.region),
                ).fetchone()

                if existing:
                    conn.execute("""
                        UPDATE pm25_observations SET
                            value = ?,
                            unit = ?,
                            source = ?,
                            created_at = ?
                        WHERE observed_at = ? AND region = ?
                    """, (
                        obs.value, obs.unit, obs.source, obs.created_at,
                        obs.observed_at, obs.region,
                    ))
                    updated += 1
                else:
                    conn.execute("""
                        INSERT INTO pm25_observations (
                            observed_at, region, value, unit, source, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        obs.observed_at, obs.region, obs.value, obs.unit,
                        obs.source, obs.created_at,
                    ))
                    inserted += 1
            conn.commit()

        log.info("Upserted %d PM2.5 observations (%d inserted, %d updated)", len(observations), inserted, updated)
        return inserted, updated

    def query_by_timerange(
        self,
        start_time: str,
        end_time: str,
        region: Optional[str] = None,
        limit: int = 10000,
    ) -> List[Pm25Observation]:
        """Query observations within a time range."""
        sql = """
            SELECT * FROM pm25_observations
            WHERE observed_at >= ? AND observed_at <= ?
        """
        params: List[Any] = [start_time, end_time]

        if region:
            sql += " AND region = ?"
            params.append(region)

        sql += " ORDER BY observed_at DESC LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_obs(row) for row in rows]

    def query_by_region(
        self,
        region: str,
        limit: int = 1000,
    ) -> List[Pm25Observation]:
        """Query all observations for a specific region."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM pm25_observations WHERE region = ? ORDER BY observed_at DESC LIMIT ?",
                (region, limit),
            ).fetchall()
            return [self._row_to_obs(row) for row in rows]

    def get_latest_snapshot(self) -> Dict[str, Any]:
        """Get the most recent observations (latest complete hour snapshot)."""
        with self._conn() as conn:
            latest_ts = conn.execute(
                "SELECT MAX(observed_at) FROM pm25_observations"
            ).fetchone()

            if not latest_ts or not latest_ts[0]:
                return {}

            rows = conn.execute(
                "SELECT * FROM pm25_observations WHERE observed_at = ?",
                (latest_ts[0],),
            ).fetchall()
            return {row["region"]: dict(row) for row in rows}

    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM pm25_observations").fetchone()[0]
            unique_regions = conn.execute("SELECT COUNT(DISTINCT region) FROM pm25_observations").fetchone()[0]
            date_range = conn.execute(
                "SELECT MIN(observed_at), MAX(observed_at) FROM pm25_observations"
            ).fetchone()
            regions = [r[0] for r in conn.execute("SELECT DISTINCT region FROM pm25_observations ORDER BY region").fetchall()]
            return {
                "total_observations": total,
                "unique_regions": unique_regions,
                "regions": regions,
                "earliest_observation": date_range[0],
                "latest_observation": date_range[1],
            }

    def _row_to_obs(self, row: sqlite3.Row) -> Pm25Observation:
        return Pm25Observation(
            observed_at=row["observed_at"],
            region=row["region"],
            value=row["value"],
            unit=row["unit"],
            source=row["source"],
            created_at=row["created_at"],
        )


def live_snapshot_to_observations(snapshot, created_at: str) -> List[Pm25Observation]:
    """Convert a Pm25LiveSnapshot to a list of Pm25Observation."""
    return [
        Pm25Observation(
            observed_at=reading.observed_at,
            region=reading.region,
            value=reading.value,
            unit=snapshot.unit,
            source=reading.source,
            created_at=created_at,
        )
        for reading in snapshot.regions.values()
    ]