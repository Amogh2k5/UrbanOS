"""Controlled transit data collection schedulers for LTA transit APIs.

Reference data (bus services, routes, stops) changes infrequently - collect daily.
Train service alerts are real-time - collect every 5-10 minutes.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from threading import Event, Lock
from typing import Optional

from backend.app.mobility.transit.data import (
    TransitCollectionResult,
    TransitCollector,
    collect_transit_reference_once,
    collect_transit_alerts_once,
)

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))


@dataclass
class SchedulerConfig:
    """Configuration for the transit scheduler."""
    interval_seconds: int = 300  # 5 minutes default for alerts
    max_runtime_seconds: Optional[int] = None  # None = run indefinitely


class TransitAlertsScheduler:
    """Scheduler for periodic LTA train service alerts collection.

    Features:
    - Configurable interval (default 5 minutes)
    - No overlapping collections
    - Graceful shutdown on SIGINT/SIGTERM
    - Logs each collection result
    """

    def __init__(
        self,
        config: Optional[SchedulerConfig] = None,
        collector: Optional[TransitCollector] = None,
    ) -> None:
        self.config = config or SchedulerConfig()
        self.collector = collector or TransitCollector()
        self._stop_event = Event()
        self._collection_lock = Lock()
        self._collection_in_progress = False
        self._last_result: Optional[TransitCollectionResult] = None
        self._run_count = 0
        self._start_time: Optional[float] = None
        self._next_scheduled_start: Optional[float] = None

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum: int, frame) -> None:
        log.info("Shutdown signal received (signal=%d), stopping gracefully...", signum)
        self._stop_event.set()

    def _check_api_key(self) -> bool:
        api_key = os.getenv("LTA_ACCOUNT_KEY")
        if not api_key:
            log.error("LTA_ACCOUNT_KEY not configured. Set the LTA_ACCOUNT_KEY environment variable.")
            return False
        return True

    def run(self) -> None:
        if not self._check_api_key():
            sys.exit(1)

        log.info(
            "Starting transit alerts scheduler: interval=%ds, max_runtime=%s",
            self.config.interval_seconds,
            f"{self.config.max_runtime_seconds}s" if self.config.max_runtime_seconds else "indefinite",
        )

        self._start_time = time.time()
        self._next_scheduled_start = self._start_time

        while not self._stop_event.is_set():
            if self.config.max_runtime_seconds and self._start_time:
                elapsed = time.time() - self._start_time
                if elapsed >= self.config.max_runtime_seconds:
                    log.info("Max runtime reached (%.1fs), stopping", elapsed)
                    break

            now = time.time()

            if now >= self._next_scheduled_start:
                delay = now - self._next_scheduled_start
                if delay > 1.0:
                    log.warning(
                        "Collection start delayed by %.1fs (interval=%.1fs, previous collection ran long)",
                        delay, self.config.interval_seconds,
                    )

            if not self._collection_lock.acquire(blocking=False):
                log.warning("Previous collection still running, waiting for completion...")
                if not self._collection_lock.acquire(timeout=60):
                    log.error("Timed out waiting for previous collection to complete")
                    self._schedule_next_start()
                    continue

            self._collection_in_progress = True
            collection_start_time = time.time()
            try:
                self._run_collection_cycle(collection_start_time)
            finally:
                self._collection_in_progress = False
                self._collection_lock.release()

            self._next_scheduled_start = collection_start_time + self.config.interval_seconds
            self._sleep_until_next_start()

        log.info("Transit alerts scheduler stopped. Total runs: %d", self._run_count)

    def _run_collection_cycle(self, collection_start_time: float) -> None:
        self._run_count += 1
        log.info("Starting train alerts collection run #%d at %s",
                 self._run_count, datetime.now(SG_OFFSET).isoformat())

        try:
            result = self.collector.collect_train_alerts()
            # Clean up old alerts (>24 hours)
            deleted = self.collector.store.cleanup_old_alerts(max_age_hours=24)
            if deleted:
                log.info("Cleaned up %d stale alerts during run #%d", deleted, self._run_count)
            self._last_result = result
            duration = time.time() - collection_start_time

            if result.errors:
                log.error(
                    "Train alerts run #%d FAILED: received=%d, stored=%d, duration=%.2fs, errors=%s",
                    self._run_count, result.train_alerts_received, result.train_alerts_stored,
                    duration, result.errors,
                )
            else:
                log.info(
                    "Train alerts run #%d SUCCESS: received=%d, stored=%d, cleaned=%d, duration=%.2fs",
                    self._run_count, result.train_alerts_received, result.train_alerts_stored,
                    deleted, duration,
                )

        except Exception as e:
            duration = time.time() - collection_start_time
            log.error(
                "Train alerts run #%d EXCEPTION: duration=%.2fs, error=%s",
                self._run_count, duration, e,
            )
            self._last_result = TransitCollectionResult(
                timestamp=datetime.now(SG_OFFSET).isoformat(),
                bus_services_received=0, bus_services_stored=0,
                bus_routes_received=0, bus_routes_stored=0,
                bus_stops_received=0, bus_stops_stored=0,
                train_alerts_received=0, train_alerts_stored=0,
                errors=[f"Collection exception: {e}"],
            )

    def _schedule_next_start(self) -> None:
        if self._next_scheduled_start is None:
            self._next_scheduled_start = time.time()
        else:
            self._next_scheduled_start += self.config.interval_seconds

    def _sleep_until_next_start(self) -> None:
        now = time.time()
        sleep_time = max(0, self._next_scheduled_start - now)
        if sleep_time > 0:
            log.debug("Sleeping %.2fs until next collection start", sleep_time)
            self._stop_event.wait(timeout=sleep_time)

    def get_last_result(self) -> Optional[TransitCollectionResult]:
        return self._last_result

    def is_running(self) -> bool:
        return self._collection_in_progress


@dataclass
class ReferenceSchedulerConfig:
    interval_seconds: int = 86400  # 24 hours default for reference data
    max_runtime_seconds: Optional[int] = None


class TransitReferenceScheduler:
    """Scheduler for periodic LTA bus reference data collection (daily)."""

    def __init__(
        self,
        config: Optional[ReferenceSchedulerConfig] = None,
        collector: Optional[TransitCollector] = None,
    ) -> None:
        self.config = config or ReferenceSchedulerConfig()
        self.collector = collector or TransitCollector()
        self._stop_event = Event()
        self._collection_lock = Lock()
        self._collection_in_progress = False
        self._last_result: Optional[TransitCollectionResult] = None
        self._run_count = 0
        self._start_time: Optional[float] = None
        self._next_scheduled_start: Optional[float] = None

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum: int, frame) -> None:
        log.info("Shutdown signal received (signal=%d), stopping gracefully...", signum)
        self._stop_event.set()

    def _check_api_key(self) -> bool:
        api_key = os.getenv("LTA_ACCOUNT_KEY")
        if not api_key:
            log.error("LTA_ACCOUNT_KEY not configured. Set the LTA_ACCOUNT_KEY environment variable.")
            return False
        return True

    def run(self) -> None:
        if not self._check_api_key():
            sys.exit(1)

        log.info(
            "Starting transit reference scheduler: interval=%ds, max_runtime=%s",
            self.config.interval_seconds,
            f"{self.config.max_runtime_seconds}s" if self.config.max_runtime_seconds else "indefinite",
        )

        self._start_time = time.time()
        self._next_scheduled_start = self._start_time

        while not self._stop_event.is_set():
            if self.config.max_runtime_seconds and self._start_time:
                elapsed = time.time() - self._start_time
                if elapsed >= self.config.max_runtime_seconds:
                    log.info("Max runtime reached (%.1fs), stopping", elapsed)
                    break

            now = time.time()

            if now >= self._next_scheduled_start:
                delay = now - self._next_scheduled_start
                if delay > 1.0:
                    log.warning(
                        "Collection start delayed by %.1fs (interval=%.1fs, previous collection ran long)",
                        delay, self.config.interval_seconds,
                    )

            if not self._collection_lock.acquire(blocking=False):
                log.warning("Previous collection still running, waiting for completion...")
                if not self._collection_lock.acquire(timeout=300):  # longer timeout for reference data
                    log.error("Timed out waiting for previous collection to complete")
                    self._schedule_next_start()
                    continue

            self._collection_in_progress = True
            collection_start_time = time.time()
            try:
                self._run_collection_cycle(collection_start_time)
            finally:
                self._collection_in_progress = False
                self._collection_lock.release()

            self._next_scheduled_start = collection_start_time + self.config.interval_seconds
            self._sleep_until_next_start()

        log.info("Transit reference scheduler stopped. Total runs: %d", self._run_count)

    def _run_collection_cycle(self, collection_start_time: float) -> None:
        self._run_count += 1
        log.info("Starting reference data collection run #%d at %s",
                 self._run_count, datetime.now(SG_OFFSET).isoformat())

        try:
            result = self.collector.collect_reference_data()
            self._last_result = result
            duration = time.time() - collection_start_time

            if result.errors:
                log.error(
                    "Reference run #%d FAILED: services=%d, routes=%d, stops=%d, duration=%.2fs, errors=%s",
                    self._run_count, result.bus_services_stored, result.bus_routes_stored,
                    result.bus_stops_stored, duration, result.errors,
                )
            else:
                log.info(
                    "Reference run #%d SUCCESS: services=%d, routes=%d, stops=%d, duration=%.2fs",
                    self._run_count, result.bus_services_stored, result.bus_routes_stored,
                    result.bus_stops_stored, duration,
                )

        except Exception as e:
            duration = time.time() - collection_start_time
            log.error(
                "Reference run #%d EXCEPTION: duration=%.2fs, error=%s",
                self._run_count, duration, e,
            )
            self._last_result = TransitCollectionResult(
                timestamp=datetime.now(SG_OFFSET).isoformat(),
                bus_services_received=0, bus_services_stored=0,
                bus_routes_received=0, bus_routes_stored=0,
                bus_stops_received=0, bus_stops_stored=0,
                train_alerts_received=0, train_alerts_stored=0,
                errors=[f"Collection exception: {e}"],
            )

    def _schedule_next_start(self) -> None:
        if self._next_scheduled_start is None:
            self._next_scheduled_start = time.time()
        else:
            self._next_scheduled_start += self.config.interval_seconds

    def _sleep_until_next_start(self) -> None:
        now = time.time()
        sleep_time = max(0, self._next_scheduled_start - now)
        if sleep_time > 0:
            log.debug("Sleeping %.2fs until next collection start", sleep_time)
            self._stop_event.wait(timeout=sleep_time)

    def get_last_result(self) -> Optional[TransitCollectionResult]:
        return self._last_result

    def is_running(self) -> bool:
        return self._collection_in_progress


def run_alerts_scheduler(
    interval_seconds: int = 300,
    max_runtime_seconds: Optional[int] = None,
) -> None:
    config = SchedulerConfig(interval_seconds=interval_seconds, max_runtime_seconds=max_runtime_seconds)
    scheduler = TransitAlertsScheduler(config=config)
    scheduler.run()


def run_reference_scheduler(
    interval_seconds: int = 86400,
    max_runtime_seconds: Optional[int] = None,
) -> None:
    config = ReferenceSchedulerConfig(interval_seconds=interval_seconds, max_runtime_seconds=max_runtime_seconds)
    scheduler = TransitReferenceScheduler(config=config)
    scheduler.run()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="UrbanOS LTA Transit Schedulers")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    alerts_parser = subparsers.add_parser("alerts", help="Run train alerts scheduler")
    alerts_parser.add_argument("--interval", type=int, default=300, help="Interval in seconds (default: 300)")
    alerts_parser.add_argument("--max-runtime", type=int, default=None, help="Max runtime in seconds")
    alerts_parser.add_argument("--log-level", type=str, default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    ref_parser = subparsers.add_parser("reference", help="Run reference data scheduler")
    ref_parser.add_argument("--interval", type=int, default=86400, help="Interval in seconds (default: 86400)")
    ref_parser.add_argument("--max-runtime", type=int, default=None, help="Max runtime in seconds")
    ref_parser.add_argument("--log-level", type=str, default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.mode == "alerts":
        run_alerts_scheduler(interval_seconds=args.interval, max_runtime_seconds=args.max_runtime)
    elif args.mode == "reference":
        run_reference_scheduler(interval_seconds=args.interval, max_runtime_seconds=args.max_runtime)