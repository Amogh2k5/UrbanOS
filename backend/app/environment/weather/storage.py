"""SQLite storage for NEA 24-hour Weather Forecast historical data.

Supports:
- National forecast table (one row per issuance)
- Period forecast table (one row per issuance per time period per region)
- Duplicate prevention via upsert on natural keys
- Query by time range
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))

_DEFAULT_DB_PATH = Path("data/weather_forecasts.db")


def _get_default_db_path() -> Path:
    """Get the default database path (allows runtime override for testing)."""
    return _DEFAULT_DB_PATH


@dataclass
class WeatherNationalForecast:
    """Stored national weather forecast record."""
    date: str                    # YYYY-MM-DD (calendar date of forecast issuance)
    timestamp: str               # Issuance timestamp (ISO +08:00)
    update_timestamp: str        # NEA update timestamp (ISO +08:00)
    temperature_high: float
    temperature_low: float
    relative_humidity_high: float
    relative_humidity_low: float
    wind_speed_high: float
    wind_speed_low: float
    wind_speed_direction: str
    forecast_code: str
    forecast_text: str
    created_at: str


@dataclass
class WeatherPeriodForecast:
    """Stored period weather forecast record (regional sub-period)."""
    date: str                    # YYYY-MM-DD (calendar date of forecast issuance)
    timestamp: str               # Issuance timestamp (ISO +08:00)
    update_timestamp: str        # NEA update timestamp (ISO +08:00)
    valid_period_start: str      # Valid period start (ISO +08:00)
    valid_period_end: str        # Valid period end (ISO +08:00)
    time_period_start: str       # Sub-period start (ISO +08:00)
    time_period_end: str         # Sub-period end (ISO +08:00)
    time_period_text: str        # Human-readable period text
    region: str                  # north/south/east/west/central
    forecast_code: str           # Regional forecast code
    forecast_text: str           # Regional forecast text
    data_quality_flag: str       # ok | year_offset_repaired
    created_at: str


class WeatherForecastStore:
    """SQLite-backed storage for NEA 24h weather forecasts."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or _get_default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._conn() as conn:
            # National forecast table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS weather_national_forecast (
                    date TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    update_timestamp TEXT NOT NULL,
                    temperature_high REAL NOT NULL,
                    temperature_low REAL NOT NULL,
                    relative_humidity_high REAL NOT NULL,
                    relative_humidity_low REAL NOT NULL,
                    wind_speed_high REAL NOT NULL,
                    wind_speed_low REAL NOT NULL,
                    wind_speed_direction TEXT NOT NULL,
                    forecast_code TEXT NOT NULL,
                    forecast_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (date, timestamp)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_weather_nat_timestamp
                ON weather_national_forecast (timestamp DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_weather_nat_date
                ON weather_national_forecast (date)
            """)

            # Period forecast table (regional sub-periods)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS weather_period_forecast (
                    date TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    update_timestamp TEXT NOT NULL,
                    valid_period_start TEXT NOT NULL,
                    valid_period_end TEXT NOT NULL,
                    time_period_start TEXT NOT NULL,
                    time_period_end TEXT NOT NULL,
                    time_period_text TEXT NOT NULL,
                    region TEXT NOT NULL,
                    forecast_code TEXT NOT NULL,
                    forecast_text TEXT NOT NULL,
                    data_quality_flag TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (date, timestamp, time_period_start, region)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_weather_per_timestamp
                ON weather_period_forecast (timestamp DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_weather_per_region
                ON weather_period_forecast (region)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_weather_per_valid_period
                ON weather_period_forecast (valid_period_start, valid_period_end)
            """)
            conn.commit()
        log.info("Weather forecast store initialized at %s", self.db_path)

    @contextmanager
    def _conn(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def upsert_national_forecasts(self, forecasts: List[WeatherNationalForecast]) -> Tuple[int, int]:
        """Insert or update national forecasts. Returns (inserted_count, updated_count)."""
        if not forecasts:
            return 0, 0

        inserted = 0
        updated = 0

        with self._conn() as conn:
            for fc in forecasts:
                existing = conn.execute(
                    "SELECT 1 FROM weather_national_forecast WHERE date = ? AND timestamp = ?",
                    (fc.date, fc.timestamp),
                ).fetchone()

                if existing:
                    conn.execute("""
                        UPDATE weather_national_forecast SET
                            update_timestamp = ?,
                            temperature_high = ?,
                            temperature_low = ?,
                            relative_humidity_high = ?,
                            relative_humidity_low = ?,
                            wind_speed_high = ?,
                            wind_speed_low = ?,
                            wind_speed_direction = ?,
                            forecast_code = ?,
                            forecast_text = ?,
                            created_at = ?
                        WHERE date = ? AND timestamp = ?
                    """, (
                        fc.update_timestamp,
                        fc.temperature_high,
                        fc.temperature_low,
                        fc.relative_humidity_high,
                        fc.relative_humidity_low,
                        fc.wind_speed_high,
                        fc.wind_speed_low,
                        fc.wind_speed_direction,
                        fc.forecast_code,
                        fc.forecast_text,
                        fc.created_at,
                        fc.date,
                        fc.timestamp,
                    ))
                    updated += 1
                else:
                    conn.execute("""
                        INSERT INTO weather_national_forecast (
                            date, timestamp, update_timestamp,
                            temperature_high, temperature_low,
                            relative_humidity_high, relative_humidity_low,
                            wind_speed_high, wind_speed_low,
                            wind_speed_direction, forecast_code, forecast_text,
                            created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        fc.date, fc.timestamp, fc.update_timestamp,
                        fc.temperature_high, fc.temperature_low,
                        fc.relative_humidity_high, fc.relative_humidity_low,
                        fc.wind_speed_high, fc.wind_speed_low,
                        fc.wind_speed_direction, fc.forecast_code, fc.forecast_text,
                        fc.created_at,
                    ))
                    inserted += 1
            conn.commit()

        log.info("Upserted %d national forecasts (%d inserted, %d updated)", len(forecasts), inserted, updated)
        return inserted, updated

    def upsert_period_forecasts(self, forecasts: List[WeatherPeriodForecast]) -> Tuple[int, int]:
        """Insert or update period forecasts. Returns (inserted_count, updated_count)."""
        if not forecasts:
            return 0, 0

        inserted = 0
        updated = 0

        with self._conn() as conn:
            for fc in forecasts:
                existing = conn.execute(
                    "SELECT 1 FROM weather_period_forecast WHERE date = ? AND timestamp = ? AND time_period_start = ? AND region = ?",
                    (fc.date, fc.timestamp, fc.time_period_start, fc.region),
                ).fetchone()

                if existing:
                    conn.execute("""
                        UPDATE weather_period_forecast SET
                            update_timestamp = ?,
                            valid_period_start = ?,
                            valid_period_end = ?,
                            time_period_end = ?,
                            time_period_text = ?,
                            forecast_code = ?,
                            forecast_text = ?,
                            data_quality_flag = ?,
                            created_at = ?
                        WHERE date = ? AND timestamp = ? AND time_period_start = ? AND region = ?
                    """, (
                        fc.update_timestamp,
                        fc.valid_period_start,
                        fc.valid_period_end,
                        fc.time_period_end,
                        fc.time_period_text,
                        fc.forecast_code,
                        fc.forecast_text,
                        fc.data_quality_flag,
                        fc.created_at,
                        fc.date,
                        fc.timestamp,
                        fc.time_period_start,
                        fc.region,
                    ))
                    updated += 1
                else:
                    conn.execute("""
                        INSERT INTO weather_period_forecast (
                            date, timestamp, update_timestamp,
                            valid_period_start, valid_period_end,
                            time_period_start, time_period_end, time_period_text,
                            region, forecast_code, forecast_text,
                            data_quality_flag, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        fc.date, fc.timestamp, fc.update_timestamp,
                        fc.valid_period_start, fc.valid_period_end,
                        fc.time_period_start, fc.time_period_end, fc.time_period_text,
                        fc.region, fc.forecast_code, fc.forecast_text,
                        fc.data_quality_flag, fc.created_at,
                    ))
                    inserted += 1
            conn.commit()

        log.info("Upserted %d period forecasts (%d inserted, %d updated)", len(forecasts), inserted, updated)
        return inserted, updated

    def get_national_forecasts(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 10000,
    ) -> List[WeatherNationalForecast]:
        """Query national forecasts within a time range."""
        sql = "SELECT * FROM weather_national_forecast WHERE 1=1"
        params: List[Any] = []

        if start_time:
            sql += " AND timestamp >= ?"
            params.append(start_time)
        if end_time:
            sql += " AND timestamp <= ?"
            params.append(end_time)

        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_national_fc(row) for row in rows]

    def get_period_forecasts(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        region: Optional[str] = None,
        limit: int = 10000,
    ) -> List[WeatherPeriodForecast]:
        """Query period forecasts within a time range."""
        sql = "SELECT * FROM weather_period_forecast WHERE 1=1"
        params: List[Any] = []

        if start_time:
            sql += " AND timestamp >= ?"
            params.append(start_time)
        if end_time:
            sql += " AND timestamp <= ?"
            params.append(end_time)
        if region:
            sql += " AND region = ?"
            params.append(region)

        sql += " ORDER BY timestamp DESC, time_period_start ASC LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_period_fc(row) for row in rows]

    def get_latest_national_forecast(self) -> Optional[WeatherNationalForecast]:
        """Get the most recent national forecast."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM weather_national_forecast ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            return self._row_to_national_fc(row) if row else None

    def get_latest_forecast_timestamp(self) -> Optional[str]:
        """Get the timestamp of the most recent forecast issuance."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(timestamp) FROM weather_national_forecast"
            ).fetchone()
            return row[0] if row and row[0] else None

    def to_national_dataframe(self) -> pd.DataFrame:
        """Export national forecasts to pandas DataFrame (for PM2.5 feature pipeline)."""
        with self._conn() as conn:
            df = pd.read_sql_query(
                "SELECT * FROM weather_national_forecast ORDER BY timestamp",
                conn,
            )
        if not df.empty:
            # Parse timestamps to tz-aware
            for col in ("timestamp", "update_timestamp"):
                df[col] = pd.to_datetime(df[col]).dt.tz_convert("Asia/Singapore")
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize("Asia/Singapore")
        return df

    def to_period_dataframe(self) -> pd.DataFrame:
        """Export period forecasts to pandas DataFrame (for PM2.5 feature pipeline)."""
        with self._conn() as conn:
            df = pd.read_sql_query(
                "SELECT * FROM weather_period_forecast ORDER BY timestamp, time_period_start, region",
                conn,
            )
        if not df.empty:
            # Parse timestamps to tz-aware
            for col in ("timestamp", "update_timestamp", "valid_period_start", "valid_period_end",
                        "time_period_start", "time_period_end"):
                df[col] = pd.to_datetime(df[col]).dt.tz_convert("Asia/Singapore")
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize("Asia/Singapore")
        return df

    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        with self._conn() as conn:
            total_nat = conn.execute("SELECT COUNT(*) FROM weather_national_forecast").fetchone()[0]
            total_per = conn.execute("SELECT COUNT(*) FROM weather_period_forecast").fetchone()[0]
            unique_dates = conn.execute("SELECT COUNT(DISTINCT date) FROM weather_national_forecast").fetchone()[0]
            date_range = conn.execute(
                "SELECT MIN(timestamp), MAX(timestamp) FROM weather_national_forecast"
            ).fetchone()
            return {
                "national_forecasts": total_nat,
                "period_forecasts": total_per,
                "unique_dates": unique_dates,
                "earliest_forecast": date_range[0],
                "latest_forecast": date_range[1],
            }

    def _row_to_national_fc(self, row: sqlite3.Row) -> WeatherNationalForecast:
        return WeatherNationalForecast(
            date=row["date"],
            timestamp=row["timestamp"],
            update_timestamp=row["update_timestamp"],
            temperature_high=row["temperature_high"],
            temperature_low=row["temperature_low"],
            relative_humidity_high=row["relative_humidity_high"],
            relative_humidity_low=row["relative_humidity_low"],
            wind_speed_high=row["wind_speed_high"],
            wind_speed_low=row["wind_speed_low"],
            wind_speed_direction=row["wind_speed_direction"],
            forecast_code=row["forecast_code"],
            forecast_text=row["forecast_text"],
            created_at=row["created_at"],
        )

    def _row_to_period_fc(self, row: sqlite3.Row) -> WeatherPeriodForecast:
        return WeatherPeriodForecast(
            date=row["date"],
            timestamp=row["timestamp"],
            update_timestamp=row["update_timestamp"],
            valid_period_start=row["valid_period_start"],
            valid_period_end=row["valid_period_end"],
            time_period_start=row["time_period_start"],
            time_period_end=row["time_period_end"],
            time_period_text=row["time_period_text"],
            region=row["region"],
            forecast_code=row["forecast_code"],
            forecast_text=row["forecast_text"],
            data_quality_flag=row["data_quality_flag"],
            created_at=row["created_at"],
        )


def live_snapshot_to_national_forecasts(snapshot, created_at: str) -> List[WeatherNationalForecast]:
    """Convert a WeatherLiveSnapshot to WeatherNationalForecast list."""
    # The snapshot contains one issuance (the latest)
    # We need the date from the issuance timestamp
    issue_ts = pd.Timestamp(snapshot.issue_timestamp)
    date_str = issue_ts.strftime("%Y-%m-%d")

    g = snapshot.general
    return [WeatherNationalForecast(
        date=date_str,
        timestamp=snapshot.issue_timestamp,
        update_timestamp=snapshot.updated_timestamp or snapshot.issue_timestamp,
        temperature_high=g.temperature_high_c or 0.0,
        temperature_low=g.temperature_low_c or 0.0,
        relative_humidity_high=g.relative_humidity_high_pct or 0.0,
        relative_humidity_low=g.relative_humidity_low_pct or 0.0,
        wind_speed_high=g.wind_speed_high_kmh or 0.0,
        wind_speed_low=g.wind_speed_low_kmh or 0.0,
        wind_speed_direction=g.wind_direction or "",
        forecast_code=g.forecast_code or "",
        forecast_text=g.forecast_text or "",
        created_at=created_at,
    )]


def live_snapshot_to_period_forecasts(snapshot, created_at: str) -> List[WeatherPeriodForecast]:
    """Convert a WeatherLiveSnapshot to WeatherPeriodForecast list.

    The NEA live API returns periods with regional forecasts.
    We expand each period into one row per region.
    """
    forecasts = []
    if not snapshot.periods:
        return forecasts

    issue_ts = pd.Timestamp(snapshot.issue_timestamp)
    date_str = issue_ts.strftime("%Y-%m-%d")

    for period in snapshot.periods:
        vps = period.time_period_start or snapshot.issue_timestamp
        vpe = period.time_period_end or snapshot.issue_timestamp
        tps = period.time_period_start or vps
        tpe = period.time_period_end or vpe

        for region_name, region_data in period.regions.items():
            forecasts.append(WeatherPeriodForecast(
                date=date_str,
                timestamp=snapshot.issue_timestamp,
                update_timestamp=snapshot.updated_timestamp or snapshot.issue_timestamp,
                valid_period_start=vps,
                valid_period_end=vpe,
                time_period_start=tps,
                time_period_end=tpe,
                time_period_text=period.time_period_text or "",
                region=region_name,
                forecast_code=region_data.forecast_code or "",
                forecast_text=region_data.forecast_text or "",
                data_quality_flag="ok",
                created_at=created_at,
            ))

    return forecasts