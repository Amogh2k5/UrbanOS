"""Transit data models, collection, and storage."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import logging

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))
_DEFAULT_DB_PATH = Path("data/transit_data.db")


# ============================================================
# MODELS (from models.py)
# ============================================================

@dataclass
class StoredBusService:
    service_no: str
    operator: str
    direction: int
    category: str
    origin_code: str
    destination_code: str
    am_peak_freq: Optional[str]
    am_offpeak_freq: Optional[str]
    pm_peak_freq: Optional[str]
    pm_offpeak_freq: Optional[str]
    loop_desc: Optional[str]
    source: str
    fetched_at: str
    created_at: str


@dataclass
class StoredBusRoute:
    service_no: str
    operator: str
    direction: int
    stop_sequence: int
    bus_stop_code: str
    distance: Optional[float]
    wd_first_bus: Optional[str]
    wd_last_bus: Optional[str]
    sat_first_bus: Optional[str]
    sat_last_bus: Optional[str]
    sun_first_bus: Optional[str]
    sun_last_bus: Optional[str]
    source: str
    fetched_at: str
    created_at: str


@dataclass
class StoredBusStop:
    bus_stop_code: str
    road_name: str
    description: str
    latitude: float
    longitude: float
    source: str
    fetched_at: str
    created_at: str


@dataclass
class StoredTrainAlert:
    id: int
    line: str
    direction: Optional[str]
    station: Optional[str]
    message: str
    status: Optional[str]
    source: str
    fetched_at: str
    created_at: str
    category: str = "rail"  # bus, metro, rail


# ============================================================
# API ADAPTER DATA CLASSES (from api_bus.py and api_train.py)
# ============================================================

# Bus Services
@dataclass
class BusService:
    """Bus service reference data."""
    service_no: str
    operator: str
    direction: int
    category: str
    origin_code: str
    destination_code: str
    am_peak_freq: Optional[str]
    am_offpeak_freq: Optional[str]
    pm_peak_freq: Optional[str]
    pm_offpeak_freq: Optional[str]
    loop_desc: Optional[str]
    source: str
    fetched_at: str


@dataclass
class BusServicesSnapshot:
    snapshot_at: str
    source: str
    provider: str
    endpoint: str
    services: List[BusService]
    is_live: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "is_live": self.is_live,
            "count": len(self.services),
            "services": [
                {
                    "service_no": s.service_no,
                    "operator": s.operator,
                    "direction": s.direction,
                    "category": s.category,
                    "origin_code": s.origin_code,
                    "destination_code": s.destination_code,
                    "am_peak_freq": s.am_peak_freq,
                    "am_offpeak_freq": s.am_offpeak_freq,
                    "pm_peak_freq": s.pm_peak_freq,
                    "pm_offpeak_freq": s.pm_offpeak_freq,
                    "loop_desc": s.loop_desc,
                }
                for s in self.services
            ],
        }


# Bus Routes
@dataclass
class BusRoute:
    """Bus route reference data (service + stop sequence)."""
    service_no: str
    operator: str
    direction: int
    stop_sequence: int
    bus_stop_code: str
    distance: Optional[float]
    wd_first_bus: Optional[str]
    wd_last_bus: Optional[str]
    sat_first_bus: Optional[str]
    sat_last_bus: Optional[str]
    sun_first_bus: Optional[str]
    sun_last_bus: Optional[str]
    source: str
    fetched_at: str


@dataclass
class BusRoutesSnapshot:
    snapshot_at: str
    source: str
    provider: str
    endpoint: str
    routes: List["BusRoute"]
    is_live: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "is_live": self.is_live,
            "count": len(self.routes),
            "routes": [
                {
                    "service_no": r.service_no,
                    "operator": r.operator,
                    "direction": r.direction,
                    "stop_sequence": r.stop_sequence,
                    "bus_stop_code": r.bus_stop_code,
                    "distance": r.distance,
                    "wd_first_bus": r.wd_first_bus,
                    "wd_last_bus": r.wd_last_bus,
                    "sat_first_bus": r.sat_first_bus,
                    "sat_last_bus": r.sat_last_bus,
                    "sun_first_bus": r.sun_first_bus,
                    "sun_last_bus": r.sun_last_bus,
                }
                for r in self.routes
            ],
        }


# Bus Stops
@dataclass
class BusStop:
    """Bus stop reference data with location."""
    bus_stop_code: str
    road_name: str
    description: str
    latitude: float
    longitude: float
    source: str
    fetched_at: str


@dataclass
class BusStopsSnapshot:
    snapshot_at: str
    source: str
    provider: str
    endpoint: str
    stops: List["BusStop"]
    is_live: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "is_live": self.is_live,
            "count": len(self.stops),
            "stops": [
                {
                    "bus_stop_code": s.bus_stop_code,
                    "road_name": s.road_name,
                    "description": s.description,
                    "latitude": s.latitude,
                    "longitude": s.longitude,
                }
                for s in self.stops
            ],
        }


# Train Service Alerts
@dataclass
class TrainServiceAlert:
    """Train service alert from LTA."""
    line: str
    direction: Optional[str]
    station: Optional[str]
    message: str
    status: Optional[str]
    source: str
    fetched_at: str


@dataclass
class TrainServiceAlertsSnapshot:
    snapshot_at: str
    source: str
    provider: str
    endpoint: str
    alerts: List["TrainServiceAlert"]
    is_live: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "is_live": self.is_live,
            "count": len(self.alerts),
            "alerts": [
                {
                    "line": a.line,
                    "direction": a.direction,
                    "station": a.station,
                    "message": a.message,
                    "status": a.status,
                }
                for a in self.alerts
            ],
        }


# ============================================================
# Pydantic Response Models (from models.py)
# ============================================================

from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime


class BusServiceResponse(BaseModel):
    service_no: str
    operator: str
    direction: int
    category: str
    origin_code: str
    destination_code: str
    am_peak_freq: Optional[str] = None
    am_offpeak_freq: Optional[str] = None
    pm_peak_freq: Optional[str] = None
    pm_offpeak_freq: Optional[str] = None
    loop_desc: Optional[str] = None


class BusRouteResponse(BaseModel):
    service_no: str
    operator: str
    direction: int
    stop_sequence: int
    bus_stop_code: str
    distance: Optional[float] = None
    wd_first_bus: Optional[str] = None
    wd_last_bus: Optional[str] = None
    sat_first_bus: Optional[str] = None
    sat_last_bus: Optional[str] = None
    sun_first_bus: Optional[str] = None
    sun_last_bus: Optional[str] = None


class BusStopResponse(BaseModel):
    bus_stop_code: str
    road_name: str
    description: str
    latitude: float
    longitude: float


class TrainAlertResponse(BaseModel):
    line: str
    direction: Optional[str] = None
    station: Optional[str] = None
    message: str
    status: Optional[str] = None
    category: str = "rail"


class TransitStatusResponse(BaseModel):
    """Overall transit system status."""
    generated_at: datetime
    bus_services_count: int
    bus_routes_count: int
    bus_stops_count: int
    active_train_alerts: int
    train_alerts: List["TrainAlertResponse"] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class BusArrivalRequest(BaseModel):
    """Request for bus arrival information (for future BusArrivalv2 integration)."""
    bus_stop_code: str
    service_no: Optional[str] = None


class BusArrivalResponse(BaseModel):
    """Bus arrival estimate (placeholder for future BusArrivalv2)."""
    bus_stop_code: str
    service_no: str
    operator: str
    next_bus: Optional[dict] = None
    subsequent_bus: Optional[dict] = None
    note: str = "BusArrivalv2 API not available with current LTA account"


# ============================================================
# COLLECTOR (from collector.py)
# ============================================================

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))


@dataclass
class TransitCollectionResult:
    """Result of a single transit collection run."""
    timestamp: str
    bus_services_received: int
    bus_services_stored: int
    bus_routes_received: int
    bus_routes_stored: int
    bus_stops_received: int
    bus_stops_stored: int
    train_alerts_received: int
    train_alerts_stored: int
    errors: list[str]


class TransitCollector:
    """Service for collecting and storing LTA transit data."""

    def __init__(
        self,
        bus_services_client: Optional["BusServicesApiClient"] = None,
        bus_routes_client: Optional["BusRoutesApiClient"] = None,
        bus_stops_client: Optional["BusStopsApiClient"] = None,
        train_alerts_client: Optional["TrainServiceAlertsApiClient"] = None,
        store: Optional["TransitDataStore"] = None,
    ) -> None:
        # Import here to avoid circular imports
        from backend.app.mobility.transit.api import (
            BusServicesApiClient,
            BusRoutesApiClient,
            BusStopsApiClient,
            TrainServiceAlertsApiClient,
        )
        from backend.app.mobility.transit.data import TransitDataStore
        
        self.bus_services_client = bus_services_client or BusServicesApiClient()
        self.bus_routes_client = bus_routes_client or BusRoutesApiClient()
        self.bus_stops_client = bus_stops_client or BusStopsApiClient()
        self.train_alerts_client = train_alerts_client or TrainServiceAlertsApiClient()
        self.store = store or TransitDataStore()

    def collect_reference_data(self) -> "TransitCollectionResult":
        """Collect static reference data (bus services, routes, stops)."""
        errors: list[str] = []
        timestamp = datetime.now(SG_OFFSET).isoformat()

        # Bus Services
        bus_services_received = 0
        bus_services_stored = 0
        try:
            snapshot: "BusServicesSnapshot" = self.bus_services_client.fetch()
            bus_services_received = len(snapshot.services)
            stored = bus_services_snapshot_to_stored(snapshot)
            inserted, updated = self.store.upsert_bus_services(stored)
            bus_services_stored = inserted + updated
        except Exception as e:
            error_msg = f"Bus Services collection failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)

        # Bus Routes
        bus_routes_received = 0
        bus_routes_stored = 0
        try:
            snapshot: "BusRoutesSnapshot" = self.bus_routes_client.fetch()
            bus_routes_received = len(snapshot.routes)
            stored = bus_routes_snapshot_to_stored(snapshot)
            inserted, updated = self.store.upsert_bus_routes(stored)
            bus_routes_stored = inserted + updated
        except Exception as e:
            error_msg = f"Bus Routes collection failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)

        # Bus Stops
        bus_stops_received = 0
        bus_stops_stored = 0
        try:
            snapshot: "BusStopsSnapshot" = self.bus_stops_client.fetch()
            bus_stops_received = len(snapshot.stops)
            stored = bus_stops_snapshot_to_stored(snapshot)
            inserted, updated = self.store.upsert_bus_stops(stored)
            bus_stops_stored = inserted + updated
        except Exception as e:
            error_msg = f"Bus Stops collection failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)

        log.info(
            "Reference collection complete: services=%d, routes=%d, stops=%d",
            bus_services_stored, bus_routes_stored, bus_stops_stored
        )

        return TransitCollectionResult(
            timestamp=timestamp,
            bus_services_received=bus_services_received,
            bus_services_stored=bus_services_stored,
            bus_routes_received=bus_routes_received,
            bus_routes_stored=bus_routes_stored,
            bus_stops_received=bus_stops_received,
            bus_stops_stored=bus_stops_stored,
            train_alerts_received=0,
            train_alerts_stored=0,
            errors=errors,
        )

    def collect_train_alerts(self) -> "TransitCollectionResult":
        """Collect train service alerts (real-time)."""
        errors: list[str] = []
        timestamp = datetime.now(SG_OFFSET).isoformat()

        train_alerts_received = 0
        train_alerts_stored = 0
        try:
            snapshot: "TrainServiceAlertsSnapshot" = self.train_alerts_client.fetch()
            train_alerts_received = len(snapshot.alerts)
            if train_alerts_received > 0:
                stored = train_alerts_snapshot_to_stored(snapshot)
                inserted = self.store.insert_train_alerts(stored)
                train_alerts_stored = inserted
        except Exception as e:
            error_msg = f"Train Alerts collection failed: {e}"
            log.error(error_msg)
            errors.append(error_msg)

        log.info(
            "Train alerts collection complete: received=%d, stored=%d",
            train_alerts_received, train_alerts_stored
        )

        return TransitCollectionResult(
            timestamp=timestamp,
            bus_services_received=0,
            bus_services_stored=0,
            bus_routes_received=0,
            bus_routes_stored=0,
            bus_stops_received=0,
            bus_stops_stored=0,
            train_alerts_received=train_alerts_received,
            train_alerts_stored=train_alerts_stored,
            errors=errors,
        )

    def collect_all(self) -> "TransitCollectionResult":
        """Collect all transit data (reference + alerts)."""
        ref_result = self.collect_reference_data()
        alert_result = self.collect_train_alerts()

        # Combine results
        return TransitCollectionResult(
            timestamp=ref_result.timestamp,
            bus_services_received=ref_result.bus_services_received,
            bus_services_stored=ref_result.bus_services_stored,
            bus_routes_received=ref_result.bus_routes_received,
            bus_routes_stored=ref_result.bus_routes_stored,
            bus_stops_received=ref_result.bus_stops_received,
            bus_stops_stored=ref_result.bus_stops_stored,
            train_alerts_received=alert_result.train_alerts_received,
            train_alerts_stored=alert_result.train_alerts_stored,
            errors=ref_result.errors + alert_result.errors,
        )


def collect_transit_reference_once() -> "TransitCollectionResult":
    """Convenience function for scheduled reference data collection."""
    collector = TransitCollector()
    return collector.collect_reference_data()


def collect_transit_alerts_once() -> "TransitCollectionResult":
    """Convenience function for scheduled train alerts collection."""
    collector = TransitCollector()
    return collector.collect_train_alerts()


def collect_transit_all_once() -> "TransitCollectionResult":
    """Convenience function for full collection."""
    collector = TransitCollector()
    return collector.collect_all()


def get_transit_stats() -> Dict[str, Any]:
    """Get storage statistics."""
    store = TransitDataStore()
    return store.get_stats()


# ============================================================
# STORAGE (from storage.py)
# ============================================================

@dataclass
class StoredBusService:
    service_no: str
    operator: str
    direction: int
    category: str
    origin_code: str
    destination_code: str
    am_peak_freq: Optional[str]
    am_offpeak_freq: Optional[str]
    pm_peak_freq: Optional[str]
    pm_offpeak_freq: Optional[str]
    loop_desc: Optional[str]
    source: str
    fetched_at: str
    created_at: str


@dataclass
class StoredBusRoute:
    service_no: str
    operator: str
    direction: int
    stop_sequence: int
    bus_stop_code: str
    distance: Optional[float]
    wd_first_bus: Optional[str]
    wd_last_bus: Optional[str]
    sat_first_bus: Optional[str]
    sat_last_bus: Optional[str]
    sun_first_bus: Optional[str]
    sun_last_bus: Optional[str]
    source: str
    fetched_at: str
    created_at: str


@dataclass
class StoredBusStop:
    bus_stop_code: str
    road_name: str
    description: str
    latitude: float
    longitude: float
    source: str
    fetched_at: str
    created_at: str


@dataclass
class StoredTrainAlert:
    id: int
    line: str
    direction: Optional[str]
    station: Optional[str]
    message: str
    status: Optional[str]
    source: str
    fetched_at: str
    created_at: str
    category: str = "rail"


class TransitDataStore:
    """SQLite-backed storage for transit reference data and alerts."""

    def __init__(self, db_path: Path = _DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._conn() as conn:
            # Bus Services - natural key: (service_no, operator, direction)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bus_services (
                    service_no TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    direction INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    origin_code TEXT NOT NULL,
                    destination_code TEXT NOT NULL,
                    am_peak_freq TEXT,
                    am_offpeak_freq TEXT,
                    pm_peak_freq TEXT,
                    pm_offpeak_freq TEXT,
                    loop_desc TEXT,
                    source TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (service_no, operator, direction)
                )
            """)

            # Bus Routes - natural key: (service_no, operator, direction, stop_sequence)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bus_routes (
                    service_no TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    direction INTEGER NOT NULL,
                    stop_sequence INTEGER NOT NULL,
                    bus_stop_code TEXT NOT NULL,
                    distance REAL,
                    wd_first_bus TEXT,
                    wd_last_bus TEXT,
                    sat_first_bus TEXT,
                    sat_last_bus TEXT,
                    sun_first_bus TEXT,
                    sun_last_bus TEXT,
                    source TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (service_no, operator, direction, stop_sequence)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_bus_routes_stop
                ON bus_routes (bus_stop_code)
            """)

            # Bus Stops - natural key: bus_stop_code
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bus_stops (
                    bus_stop_code TEXT NOT NULL PRIMARY KEY,
                    road_name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    source TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_bus_stops_location
                ON bus_stops (latitude, longitude)
            """)

            # Train Service Alerts - auto-increment ID, track by line+message+fetched_at
            conn.execute("""
                CREATE TABLE IF NOT EXISTS train_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    line TEXT NOT NULL,
                    direction TEXT,
                    station TEXT,
                    message TEXT NOT NULL,
                    status TEXT,
                    source TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'rail'
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_train_alerts_line
                ON train_alerts (line)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_train_alerts_fetched
                ON train_alerts (fetched_at DESC)
            """)

            conn.commit()
        log.info("Transit data store initialized at %s", self.db_path)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ============================================================
    # BUS SERVICES
    # ============================================================

    def upsert_bus_services(self, services: List[StoredBusService]) -> Tuple[int, int]:
        """Insert or update bus services. Returns (inserted_count, updated_count)."""
        if not services:
            return 0, 0

        inserted = 0
        updated = 0
        created_at = datetime.now(SG_OFFSET).isoformat()

        with self._conn() as conn:
            for svc in services:
                existing = conn.execute(
                    "SELECT 1 FROM bus_services WHERE service_no = ? AND operator = ? AND direction = ?",
                    (svc.service_no, svc.operator, svc.direction),
                ).fetchone()

                if existing:
                    conn.execute("""
                        UPDATE bus_services SET
                            category = ?, origin_code = ?, destination_code = ?,
                            am_peak_freq = ?, am_offpeak_freq = ?, pm_peak_freq = ?, pm_offpeak_freq = ?,
                            loop_desc = ?, source = ?, fetched_at = ?, created_at = ?
                        WHERE service_no = ? AND operator = ? AND direction = ?
                    """, (
                        svc.category, svc.origin_code, svc.destination_code,
                        svc.am_peak_freq, svc.am_offpeak_freq, svc.pm_peak_freq, svc.pm_offpeak_freq,
                        svc.loop_desc, svc.source, svc.fetched_at, created_at,
                        svc.service_no, svc.operator, svc.direction,
                    ))
                    updated += 1
                else:
                    conn.execute("""
                        INSERT INTO bus_services (
                            service_no, operator, direction, category, origin_code, destination_code,
                            am_peak_freq, am_offpeak_freq, pm_peak_freq, pm_offpeak_freq, loop_desc,
                            source, fetched_at, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        svc.service_no, svc.operator, svc.direction, svc.category,
                        svc.origin_code, svc.destination_code,
                        svc.am_peak_freq, svc.am_offpeak_freq, svc.pm_peak_freq, svc.pm_offpeak_freq,
                        svc.loop_desc, svc.source, svc.fetched_at, created_at,
                    ))
                    inserted += 1
            conn.commit()

        log.info("Upserted %d bus services (%d inserted, %d updated)", len(services), inserted, updated)
        return inserted, updated

    def get_bus_services(self, limit: int = 1000) -> List[StoredBusService]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM bus_services ORDER BY service_no, operator, direction LIMIT ?",
                (limit,)
            ).fetchall()
            return [StoredBusService(**dict(row)) for row in rows]

    def get_bus_service(self, service_no: str, operator: str, direction: int) -> Optional[StoredBusService]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM bus_services WHERE service_no = ? AND operator = ? AND direction = ?",
                (service_no, operator, direction)
            ).fetchone()
            return StoredBusService(**dict(row)) if row else None

    # ============================================================
    # BUS ROUTES
    # ============================================================

    def upsert_bus_routes(self, routes: List[StoredBusRoute]) -> Tuple[int, int]:
        if not routes:
            return 0, 0

        inserted = 0
        updated = 0
        created_at = datetime.now(SG_OFFSET).isoformat()

        with self._conn() as conn:
            for r in routes:
                existing = conn.execute(
                    "SELECT 1 FROM bus_routes WHERE service_no = ? AND operator = ? AND direction = ? AND stop_sequence = ?",
                    (r.service_no, r.operator, r.direction, r.stop_sequence),
                ).fetchone()

                if existing:
                    conn.execute("""
                        UPDATE bus_routes SET
                            bus_stop_code = ?, distance = ?, wd_first_bus = ?, wd_last_bus = ?,
                            sat_first_bus = ?, sat_last_bus = ?, sun_first_bus = ?, sun_last_bus = ?,
                            source = ?, fetched_at = ?, created_at = ?
                        WHERE service_no = ? AND operator = ? AND direction = ? AND stop_sequence = ?
                    """, (
                        r.bus_stop_code, r.distance, r.wd_first_bus, r.wd_last_bus,
                        r.sat_first_bus, r.sat_last_bus, r.sun_first_bus, r.sun_last_bus,
                        r.source, r.fetched_at, created_at,
                        r.service_no, r.operator, r.direction, r.stop_sequence,
                    ))
                    updated += 1
                else:
                    conn.execute("""
                        INSERT INTO bus_routes (
                            service_no, operator, direction, stop_sequence, bus_stop_code, distance,
                            wd_first_bus, wd_last_bus, sat_first_bus, sat_last_bus,
                            sun_first_bus, sun_last_bus, source, fetched_at, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        r.service_no, r.operator, r.direction, r.stop_sequence, r.bus_stop_code, r.distance,
                        r.wd_first_bus, r.wd_last_bus, r.sat_first_bus, r.sat_last_bus,
                        r.sun_first_bus, r.sun_last_bus, r.source, r.fetched_at, created_at,
                    ))
                    inserted += 1
            conn.commit()

        log.info("Upserted %d bus routes (%d inserted, %d updated)", len(routes), inserted, updated)
        return inserted, updated

    def get_bus_routes_for_service(self, service_no: str, operator: str, direction: int) -> List[StoredBusRoute]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM bus_routes WHERE service_no = ? AND operator = ? AND direction = ? ORDER BY stop_sequence",
                (service_no, operator, direction)
            ).fetchall()
            return [StoredBusRoute(**dict(row)) for row in rows]

    def get_bus_routes_for_stop(self, bus_stop_code: str) -> List[StoredBusRoute]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM bus_routes WHERE bus_stop_code = ? ORDER BY service_no, operator, direction, stop_sequence",
                (bus_stop_code,)
            ).fetchall()
            return [StoredBusRoute(**dict(row)) for row in rows]

    # ============================================================
    # BUS STOPS
    # ============================================================

    def upsert_bus_stops(self, stops: List[StoredBusStop]) -> Tuple[int, int]:
        if not stops:
            return 0, 0

        inserted = 0
        updated = 0
        created_at = datetime.now(SG_OFFSET).isoformat()

        with self._conn() as conn:
            for s in stops:
                existing = conn.execute(
                    "SELECT 1 FROM bus_stops WHERE bus_stop_code = ?",
                    (s.bus_stop_code,)
                ).fetchone()

                if existing:
                    conn.execute("""
                        UPDATE bus_stops SET
                            road_name = ?, description = ?, latitude = ?, longitude = ?,
                            source = ?, fetched_at = ?, created_at = ?
                        WHERE bus_stop_code = ?
                    """, (
                        s.road_name, s.description, s.latitude, s.longitude,
                        s.source, s.fetched_at, created_at, s.bus_stop_code,
                    ))
                    updated += 1
                else:
                    conn.execute("""
                        INSERT INTO bus_stops (
                            bus_stop_code, road_name, description, latitude, longitude,
                            source, fetched_at, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        s.bus_stop_code, s.road_name, s.description, s.latitude, s.longitude,
                        s.source, s.fetched_at, created_at,
                    ))
                    inserted += 1
            conn.commit()

        log.info("Upserted %d bus stops (%d inserted, %d updated)", len(stops), inserted, updated)
        return inserted, updated

    def get_bus_stop(self, bus_stop_code: str) -> Optional[StoredBusStop]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM bus_stops WHERE bus_stop_code = ?",
                (bus_stop_code,)
            ).fetchone()
            return StoredBusStop(**dict(row)) if row else None

    def get_bus_stops_near(self, lat: float, lon: float, radius_km: float = 1.0, limit: int = 50) -> List[StoredBusStop]:
        """Find bus stops within radius_km of a point (approximate)."""
        # Rough approximation: 1 degree ~= 111 km
        deg = radius_km / 111.0
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM bus_stops
                WHERE latitude BETWEEN ? AND ?
                AND longitude BETWEEN ? AND ?
                LIMIT ?
            """, (lat - deg, lat + deg, lon - deg, lon + deg, limit)).fetchall()
            return [StoredBusStop(**dict(row)) for row in rows]

    def get_all_bus_stops(self, limit: int = 5000) -> List[StoredBusStop]:
        """Get all bus stops (for map rendering)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM bus_stops ORDER BY bus_stop_code LIMIT ?",
                (limit,)
            ).fetchall()
            return [StoredBusStop(**dict(row)) for row in rows]

    # ============================================================
    # TRAIN ALERTS
    # ============================================================

    def insert_train_alerts(self, alerts: List[StoredTrainAlert]) -> int:
        if not alerts:
            return 0

        inserted = 0
        created_at = datetime.now(SG_OFFSET).isoformat()

        with self._conn() as conn:
            for a in alerts:
                # Check for duplicate (same line, message, and similar fetch time)
                existing = conn.execute(
                    "SELECT 1 FROM train_alerts WHERE line = ? AND message = ? AND fetched_at = ?",
                    (a.line, a.message, a.fetched_at)
                ).fetchone()

                if not existing:
                    conn.execute("""
                        INSERT INTO train_alerts (
                            line, direction, station, message, status, source, fetched_at, created_at, category
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        a.line, a.direction, a.station, a.message, a.status,
                        a.source, a.fetched_at, created_at, a.category,
                    ))
                    inserted += 1
            conn.commit()

        log.info("Inserted %d new train alerts", inserted)
        return inserted

    def get_latest_train_alerts(self, limit: int = 50) -> List[StoredTrainAlert]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM train_alerts ORDER BY fetched_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [StoredTrainAlert(**dict(row)) for row in rows]

    def get_train_alerts_for_line(self, line: str, limit: int = 20) -> List[StoredTrainAlert]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM train_alerts WHERE line = ? ORDER BY fetched_at DESC LIMIT ?",
                (line, limit)
            ).fetchall()
            return [StoredTrainAlert(**dict(row)) for row in rows]

    def cleanup_old_alerts(self, max_age_hours: int = 24) -> int:
        """Delete alerts older than max_age_hours. Returns number of deleted alerts."""
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(SG_OFFSET) - timedelta(hours=max_age_hours)
        cutoff_iso = cutoff.isoformat()

        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM train_alerts WHERE fetched_at < ?",
                (cutoff_iso,)
            )
            conn.commit()
            deleted = cursor.rowcount
            if deleted:
                log.info("Cleaned up %d alerts older than %d hours", deleted, max_age_hours)
            return deleted

    # ============================================================
    # STATS
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        with self._conn() as conn:
            bus_services = conn.execute("SELECT COUNT(*) FROM bus_services").fetchone()[0]
            bus_routes = conn.execute("SELECT COUNT(*) FROM bus_routes").fetchone()[0]
            bus_stops = conn.execute("SELECT COUNT(*) FROM bus_stops").fetchone()[0]
            train_alerts = conn.execute("SELECT COUNT(*) FROM train_alerts").fetchone()[0]

            # Date ranges
            services_range = conn.execute("SELECT MIN(fetched_at), MAX(fetched_at) FROM bus_services").fetchone()
            stops_range = conn.execute("SELECT MIN(fetched_at), MAX(fetched_at) FROM bus_stops").fetchone()
            alerts_range = conn.execute("SELECT MIN(fetched_at), MAX(fetched_at) FROM train_alerts").fetchone()

            return {
                "bus_services": bus_services,
                "bus_routes": bus_routes,
                "bus_stops": bus_stops,
                "train_alerts": train_alerts,
                "bus_services_fetched_range": {"min": services_range[0], "max": services_range[1]},
                "bus_stops_fetched_range": {"min": stops_range[0], "max": stops_range[1]},
                "train_alerts_fetched_range": {"min": alerts_range[0], "max": alerts_range[1]},
            }


# ============================================================
# CONVERSION FUNCTIONS
# ============================================================

def bus_services_snapshot_to_stored(snapshot) -> List[StoredBusService]:
    return [
        StoredBusService(
            service_no=s.service_no,
            operator=s.operator,
            direction=s.direction,
            category=s.category,
            origin_code=s.origin_code,
            destination_code=s.destination_code,
            am_peak_freq=s.am_peak_freq,
            am_offpeak_freq=s.am_offpeak_freq,
            pm_peak_freq=s.pm_peak_freq,
            pm_offpeak_freq=s.pm_offpeak_freq,
            loop_desc=s.loop_desc,
            source=s.source,
            fetched_at=s.fetched_at,
            created_at=datetime.now(SG_OFFSET).isoformat(),
        )
        for s in snapshot.services
    ]


def bus_routes_snapshot_to_stored(snapshot) -> List[StoredBusRoute]:
    return [
        StoredBusRoute(
            service_no=r.service_no,
            operator=r.operator,
            direction=r.direction,
            stop_sequence=r.stop_sequence,
            bus_stop_code=r.bus_stop_code,
            distance=r.distance,
            wd_first_bus=r.wd_first_bus,
            wd_last_bus=r.wd_last_bus,
            sat_first_bus=r.sat_first_bus,
            sat_last_bus=r.sat_last_bus,
            sun_first_bus=r.sun_first_bus,
            sun_last_bus=r.sun_last_bus,
            source=r.source,
            fetched_at=r.fetched_at,
            created_at=datetime.now(SG_OFFSET).isoformat(),
        )
        for r in snapshot.routes
    ]


def bus_stops_snapshot_to_stored(snapshot) -> List[StoredBusStop]:
    return [
        StoredBusStop(
            bus_stop_code=s.bus_stop_code,
            road_name=s.road_name,
            description=s.description,
            latitude=s.latitude,
            longitude=s.longitude,
            source=s.source,
            fetched_at=s.fetched_at,
            created_at=datetime.now(SG_OFFSET).isoformat(),
        )
        for s in snapshot.stops
    ]


def train_alerts_snapshot_to_stored(snapshot) -> List[StoredTrainAlert]:
    return [
        StoredTrainAlert(
            id=0,  # auto-increment
            line=a.line,
            direction=a.direction,
            station=a.station,
            message=a.message,
            status=a.status,
            source=a.source,
            fetched_at=a.fetched_at,
            created_at=datetime.now(SG_OFFSET).isoformat(),
        )
        for a in snapshot.alerts
    ]