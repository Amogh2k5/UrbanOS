"""PM2.5 data models, collection, and storage."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from backend.app.environment.pm25.api import Pm25ApiClient, Pm25LiveSnapshot

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))
_DEFAULT_DB_PATH = Path("data/pm25_observations.db")


# ============================================================
# MODELS
# ============================================================

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

    def upsert_observations(self, observations: List["Pm25Observation"]) -> Tuple[int, int]:
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
    ) -> List["Pm25Observation"]:
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
    ) -> List["Pm25Observation"]:
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

    def _row_to_obs(self, row: sqlite3.Row) -> "Pm25Observation":
        return Pm25Observation(
            observed_at=row["observed_at"],
            region=row["region"],
            value=row["value"],
            unit=row["unit"],
            source=row["source"],
            created_at=row["created_at"],
        )

    def get_latest_observation_timestamp(self) -> Optional[str]:
        """Return the latest observation timestamp across all regions."""
        with self._conn() as conn:
            row = conn.execute("SELECT MAX(observed_at) FROM pm25_observations").fetchone()
            return row[0] if row and row[0] else None

    def to_long_dataframe(self, regions: tuple) -> pd.DataFrame:
        """Return a long-format DataFrame with columns observed_at, region, pm25_value for given regions."""
        placeholders = ",".join("?" for _ in regions)
        sql = f"""
            SELECT observed_at, region, value as pm25_value
            FROM pm25_observations
            WHERE region IN ({placeholders})
            ORDER BY observed_at
        """
        with self._conn() as conn:
            df = pd.read_sql_query(sql, conn, params=list(regions))
        if not df.empty:
            df["observed_at"] = pd.to_datetime(df["observed_at"])
            if df["observed_at"].dt.tz is None:
                df["observed_at"] = df["observed_at"].dt.tz_localize("Asia/Singapore")
            else:
                df["observed_at"] = df["observed_at"].dt.tz_convert("Asia/Singapore")
        return df


def live_snapshot_to_observations(snapshot, created_at: str) -> List["Pm25Observation"]:
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


# ============================================================
# COLLECTOR (from collector.py)
# ============================================================

from backend.app.environment.pm25.api import Pm25ApiClient, Pm25LiveSnapshot
from backend.app.environment.pm25.data import (
    Pm25ObservationStore,
    Pm25Observation,
    live_snapshot_to_observations,
)

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))


@dataclass
class Pm25CollectionResult:
    """Result of a single collection run."""
    timestamp: str
    records_received: int
    records_stored: int
    records_updated: int
    regions_received: List[str]
    api_failed: bool
    errors: List[str]


class Pm25Collector:
    """Service for collecting and storing NEA PM2.5 observations."""

    def __init__(
        self,
        api_client: Optional[Pm25ApiClient] = None,
        store: Optional["Pm25ObservationStore"] = None,
    ) -> None:
        from backend.app.environment.pm25.api import Pm25ApiClient
        from backend.app.environment.pm25.data import Pm25ObservationStore

        self.api_client = api_client or Pm25ApiClient()
        self.store = store or Pm25ObservationStore()

    def collect_once(self) -> "Pm25CollectionResult":
        """Perform one collection run: fetch, normalize, store."""
        errors: List[str] = []
        timestamp = datetime.now(SG_OFFSET).isoformat()
        api_failed = False

        try:
            # Force live mode for production collection
            snapshot: Pm25LiveSnapshot = self.api_client.fetch()
        except Exception as e:
            error_msg = f"API fetch failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)
            api_failed = True
            return Pm25CollectionResult(
                timestamp=timestamp,
                records_received=0,
                records_stored=0,
                records_updated=0,
                regions_received=[],
                api_failed=True,
                errors=errors,
            )

        if not snapshot.is_live:
            error_msg = "API returned fixture data instead of live data; not storing fixture in production database"
            log.warning(error_msg)
            errors.append(error_msg)
            api_failed = True
            return Pm25CollectionResult(
                timestamp=timestamp,
                records_received=0,
                records_stored=0,
                records_updated=0,
                regions_received=[],
                api_failed=True,
                errors=errors,
            )

        # Validate we have all 5 regions
        regions = list(snapshot.regions.keys())
        expected_regions = {"north", "south", "east", "west", "central"}
        missing = expected_regions - set(regions)
        if missing:
            error_msg = f"Missing regions in API response: {missing}"
            log.error(error_msg)
            errors.append(error_msg)
            # Still store what we have, but flag it
            # Note: This is a data quality check, not a hard failure

        # Convert to storage objects
        created_at = timestamp
        observations = live_snapshot_to_observations(snapshot, created_at)
        records_received = len(observations)

        # Store observations
        records_stored = 0
        records_updated = 0
        try:
            inserted, updated = self.store.upsert_observations(observations)
            records_stored = inserted + updated
            records_updated = updated
        except Exception as e:
            error_msg = f"Storage upsert failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)
            return Pm25CollectionResult(
                timestamp=timestamp,
                records_received=records_received,
                records_stored=0,
                records_updated=0,
                regions_received=regions,
                api_failed=api_failed,
                errors=errors,
            )

        log.info(
            "PM2.5 collection complete: received=%d, stored=%d (inserted=%d, updated=%d), "
            "regions=%s, api_failed=%s",
            records_received, records_stored, records_stored - records_updated, records_updated,
            regions, api_failed
        )

        return Pm25CollectionResult(
            timestamp=timestamp,
            records_received=records_received,
            records_stored=records_stored,
            records_updated=records_updated,
            regions_received=regions,
            api_failed=api_failed,
            errors=errors,
        )


def collect_pm25_once(
    api_client: Optional["Pm25ApiClient"] = None,
    store: Optional["Pm25ObservationStore"] = None,
) -> "Pm25CollectionResult":
    """Convenience function for scheduled collection runs."""
    from backend.app.environment.pm25.data import Pm25Collector
    collector = Pm25Collector(api_client=api_client, store=store)
    return collector.collect_once()


def get_pm25_collection_stats() -> Dict[str, Any]:
    """Get PM2.5 observation storage statistics."""
    from backend.app.environment.pm25.data import Pm25ObservationStore
    store = Pm25ObservationStore()
    return store.get_stats()