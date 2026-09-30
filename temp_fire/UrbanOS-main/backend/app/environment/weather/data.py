"""Weather data models, collection, and storage."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from backend.app.environment.weather.api import WeatherLiveSnapshot

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))
_DEFAULT_DB_PATH = Path("data/weather_forecasts.db")


# ============================================================
# MODELS
# ============================================================

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


@dataclass
class WeatherForecastStore:
    """SQLite-backed storage for NEA 24h weather forecasts."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or _DEFAULT_DB_PATH
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

    def upsert_national_forecasts(self, forecasts: List["WeatherNationalForecast"]) -> Tuple[int, int]:
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

    def upsert_period_forecasts(self, forecasts: List["WeatherPeriodForecast"]) -> Tuple[int, int]:
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
    ) -> List["WeatherNationalForecast"]:
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
    ) -> List["WeatherPeriodForecast"]:
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

    def get_latest_national_forecast(self) -> Optional["WeatherNationalForecast"]:
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

    def to_national_dataframe(self) -> "pd.DataFrame":
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

    def _row_to_national_fc(self, row: sqlite3.Row) -> "WeatherNationalForecast":
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

    def _row_to_period_fc(self, row: sqlite3.Row) -> "WeatherPeriodForecast":
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

    


# ============================================================
# COLLECTOR (merged from collector.py)
# ============================================================

from backend.app.environment.weather.api import WeatherApiClient, WeatherLiveSnapshot

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))


@dataclass
class WeatherCollectionResult:
    """Result of a single collection run."""
    timestamp: str
    national_forecasts_received: int
    national_forecasts_stored: int
    national_forecasts_updated: int
    period_forecasts_received: int
    period_forecasts_stored: int
    period_forecasts_updated: int
    errors: List[str]


class WeatherForecastCollector:
    """Service for collecting and storing NEA 24h weather forecasts."""

    def __init__(
        self,
        api_client: Optional["WeatherApiClient"] = None,
        store: Optional["WeatherForecastStore"] = None,
    ) -> None:
        from backend.app.environment.weather.api import WeatherApiClient
        from backend.app.environment.weather.data import WeatherForecastStore

        self.api_client = api_client or WeatherApiClient()
        self.store = store or WeatherForecastStore()

    def collect_once(self) -> "WeatherCollectionResult":
        """Perform one collection run: fetch, normalize, store."""
        errors: List[str] = []
        timestamp = datetime.now(SG_OFFSET).isoformat()

        try:
            snapshot: WeatherLiveSnapshot = self.api_client.fetch()
        except Exception as e:
            error_msg = f"API fetch failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)
            return WeatherCollectionResult(
                timestamp=timestamp,
                national_forecasts_received=0,
                national_forecasts_stored=0,
                national_forecasts_updated=0,
                period_forecasts_received=0,
                period_forecasts_stored=0,
                period_forecasts_updated=0,
                errors=errors,
            )

        # Convert to storage objects
        created_at = timestamp
        national_fcs = live_snapshot_to_national_forecasts(snapshot, created_at)
        period_fcs = live_snapshot_to_period_forecasts(snapshot, created_at)

        national_received = len(national_fcs)
        period_received = len(period_fcs)

        # Store national forecasts
        national_stored = 0
        national_updated = 0
        try:
            inserted, updated = self.store.upsert_national_forecasts(national_fcs)
            national_stored = inserted + updated
            national_updated = updated
        except Exception as e:
            error_msg = f"National forecast storage upsert failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)

        # Store period forecasts
        period_stored = 0
        period_updated = 0
        try:
            inserted, updated = self.store.upsert_period_forecasts(period_fcs)
            period_stored = inserted + updated
            period_updated = updated
        except Exception as e:
            error_msg = f"Period forecast storage upsert failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)

        log.info(
            "Weather collection complete: national received=%d, stored=%d (inserted=%d, updated=%d), "
            "period received=%d, stored=%d (inserted=%d, updated=%d)",
            national_received, national_stored, national_stored - national_updated, national_updated,
            period_received, period_stored, period_stored - period_updated, period_updated
        )

        return WeatherCollectionResult(
            timestamp=timestamp,
            national_forecasts_received=national_received,
            national_forecasts_stored=national_stored,
            national_forecasts_updated=national_updated,
            period_forecasts_received=period_received,
            period_forecasts_stored=period_stored,
            period_forecasts_updated=period_updated,
            errors=errors,
        )


def live_snapshot_to_national_forecasts(snapshot, created_at: str):
    """Convert WeatherLiveSnapshot to list of WeatherNationalForecast for storage."""
    from datetime import datetime
    
    # Parse the issuance timestamp to get date
    try:
        if snapshot.issue_timestamp:
            dt = datetime.fromisoformat(snapshot.issue_timestamp)
            date = dt.date().isoformat()
        else:
            date = datetime.now(SG_OFFSET).date().isoformat()
    except Exception:
        date = datetime.now(SG_OFFSET).date().isoformat()
    
    return [WeatherNationalForecast(
        date=date,
        timestamp=snapshot.issue_timestamp or snapshot.snapshot_at,
        update_timestamp=snapshot.updated_timestamp or snapshot.snapshot_at,
        temperature_high=snapshot.general.temperature_high_c or 0.0,
        temperature_low=snapshot.general.temperature_low_c or 0.0,
        relative_humidity_high=snapshot.general.relative_humidity_high_pct or 0.0,
        relative_humidity_low=snapshot.general.relative_humidity_low_pct or 0.0,
        wind_speed_high=snapshot.general.wind_speed_high_kmh or 0.0,
        wind_speed_low=snapshot.general.wind_speed_low_kmh or 0.0,
        wind_speed_direction=snapshot.general.wind_direction or "",
        forecast_code=snapshot.general.forecast_code or "",
        forecast_text=snapshot.general.forecast_text or "",
        created_at=created_at,
    )]


def live_snapshot_to_period_forecasts(snapshot, created_at: str):
    """Convert WeatherLiveSnapshot to list of WeatherPeriodForecast for storage."""
    from datetime import datetime
    
    # Parse the issuance timestamp to get date
    try:
        if snapshot.issue_timestamp:
            dt = datetime.fromisoformat(snapshot.issue_timestamp)
            date = dt.date().isoformat()
        else:
            date = datetime.now(SG_OFFSET).date().isoformat()
    except Exception:
        date = datetime.now(SG_OFFSET).date().isoformat()
    
    forecasts = []
    for period in snapshot.periods:
        for region, region_data in period.regions.items():
            forecasts.append(WeatherPeriodForecast(
                date=date,
                timestamp=snapshot.issue_timestamp or snapshot.snapshot_at,
                update_timestamp=snapshot.updated_timestamp or snapshot.snapshot_at,
                valid_period_start=snapshot.general.valid_period_start or "",
                valid_period_end=snapshot.general.valid_period_end or "",
                time_period_start=period.time_period_start or "",
                time_period_end=period.time_period_end or "",
                time_period_text=period.time_period_text or "",
                region=region,
                forecast_code=region_data.forecast_code or "",
                forecast_text=region_data.forecast_text or "",
                data_quality_flag="ok",
                created_at=created_at,
            ))
    return forecasts


def collect_weather_once() -> "WeatherCollectionResult":
    """Convenience function for scheduled collection runs."""
    collector = WeatherForecastCollector()
    return collector.collect_once()


def get_weather_collection_stats() -> Dict[str, Any]:
    """Get weather forecast storage statistics."""
    store = WeatherForecastStore()
    return store.get_stats()


# ============================================================
# WEATHER LOADER FUNCTIONS (merged from loader.py)
# ============================================================

from backend.app.environment.result import WeatherForecastSummary
from ml.pm25.ingest_weather import ingest_weather

SG_TZ = "Asia/Singapore"
WEATHER_SOURCE = "NEA Historical24hourWeatherForecast"


@dataclass
class WeatherDiagnostics:
    n_files_read: int
    national_rows: int
    period_rows: int
    year_offset_rows: int
    has_forecast_at_t0: bool
    latest_issue_delta_hours: Optional[float]  # how stale latest issue is vs t0


def load_weather(weather_dir: Path):
    """Run ingestion. Returns (national_df, period_df, report)."""
    return ingest_weather(str(weather_dir))


def latest_forecast_summary(
    national: pd.DataFrame,
    t0: pd.Timestamp,
    period: Optional[pd.DataFrame] = None,
) -> Tuple[Optional[WeatherForecastSummary], Optional[pd.Timestamp]]:
    """Find the latest NEA forecast issue with `timestamp <= t0` and return its summary.

    The national table holds one row per `(date, timestamp)` with the national forecast
    fields (temp/RH/wind/code) but does NOT carry `valid_period_start/end` (those live in
    the period table). If `period` is provided, the latest issue's earliest valid_period_start
    and latest valid_period_end are joined into the summary.

    Returns (summary_or_None, latest_issue_timestamp_or_None).
    """
    if national.empty:
        return None, None

    # Ensure tz-aware
    ts_col = national["timestamp"]
    if ts_col.dt.tz is None:
        ts_col = ts_col.dt.tz_localize(SG_TZ)
    else:
        ts_col = ts_col.dt.tz_convert(SG_TZ)

    eligible = national[ts_col <= t0]
    if eligible.empty:
        return None, None

    latest = eligible.sort_values("timestamp").iloc[-1]
    latest_ts = pd.Timestamp(latest["timestamp"])

    # valid_period_* come from the period table for the same issue timestamp.
    vps = vpe = None
    if period is not None and not period.empty:
        per_ts = period["timestamp"]
        if per_ts.dt.tz is None:
            per_ts = per_ts.dt.tz_localize(SG_TZ)
        else:
            per_ts = per_ts.dt.tz_convert(SG_TZ)
        matching = period[per_ts == latest_ts]
        if not matching.empty:
            # Earliest valid_period_start and latest valid_period_end across
            # the sub-period rows for this issue: the full coverage window.
            start_vals = matching["valid_period_start"].dropna()
            end_vals = matching["valid_period_end"].dropna()
            if not start_vals.empty:
                vps = pd.Timestamp(start_vals.min())
                if vps.tzinfo is None:
                    vps = vps.tz_localize(SG_TZ)
                else:
                    vps = vps.tz_convert(SG_TZ)
            if not end_vals.empty:
                vpe = pd.Timestamp(end_vals.max())
                if vpe.tzinfo is None:
                    vpe = vpe.tz_localize(SG_TZ)
                else:
                    vpe = vpe.tz_convert(SG_TZ)

    summary = WeatherForecastSummary(
        source=WEATHER_SOURCE,
        forecast_issue_timestamp=latest_ts,
        valid_period_start=vps,
        valid_period_end=vpe,
        national_forecast_code=_str(latest, "forecast_code"),
        national_forecast_text=_str(latest, "forecast_text"),
        temperature_high_c=_num(latest, "temperature_high"),
        temperature_low_c=_num(latest, "temperature_low"),
        relative_humidity_high_pct=_num(latest, "relative_humidity_high"),
        relative_humidity_low_pct=_num(latest, "relative_humidity_low"),
        wind_speed_high_kmh=_num(latest, "wind_speed_high"),
        wind_speed_low_kmh=_num(latest, "wind_speed_low"),
        wind_direction=_str(latest, "wind_speed_direction"),
    )
    return summary, latest_ts


def _str(latest_row: pd.Series, col: str) -> Optional[str]:
    val = latest_row.get(col)
    if pd.isna(val):
        return None
    return str(val)


def _num(latest_row: pd.Series, col: str) -> Optional[float]:
    val = latest_row.get(col)
    if pd.isna(val):
        return None
    return float(val)