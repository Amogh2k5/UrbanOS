"""Controlled 5-minute traffic data collection scheduler for LTA Traffic Speed Bands.

Runs collect_traffic_once() repeatedly at a configurable interval.
The interval represents the time BETWEEN COLLECTION STARTS.
Supports graceful shutdown, prevents overlapping collections, and logs results.
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

from backend.app.environment.traffic_collector import (
    CollectionResult,
    TrafficCollector,
    collect_traffic_once,
)

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))


@dataclass
class SchedulerConfig:
    """Configuration for the traffic scheduler."""
    interval_seconds: int = 300  # 5 minutes default
    max_runtime_seconds: Optional[int] = None  # None = run indefinitely


class TrafficScheduler:
    """Scheduler for periodic LTA traffic data collection.

    Features:
    - Configurable interval (default 5 minutes) measured between COLLECTION STARTS
    - No overlapping collections (sequential execution)
    - Graceful shutdown on SIGINT/SIGTERM
    - Logs each collection result
    - Stops with clear error if LTA_API_KEY is missing
    - If collection exceeds interval, next starts immediately with warning
    """

    def __init__(
        self,
        config: Optional[SchedulerConfig] = None,
        collector: Optional[TrafficCollector] = None,
    ) -> None:
        self.config = config or SchedulerConfig()
        self.collector = collector or TrafficCollector()
        self._stop_event = Event()
        self._collection_lock = Lock()
        self._collection_in_progress = False
        self._last_result: Optional[CollectionResult] = None
        self._run_count = 0
        self._start_time: Optional[float] = None
        self._next_scheduled_start: Optional[float] = None

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum: int, frame) -> None:
        """Handle shutdown signals."""
        log.info("Shutdown signal received (signal=%d), stopping gracefully...", signum)
        self._stop_event.set()

    def _check_api_key(self) -> bool:
        """Verify LTA_API_KEY is configured."""
        api_key = os.getenv("LTA_API_KEY")
        if not api_key:
            log.error("LTA_API_KEY not configured. Set the LTA_API_KEY environment variable.")
            return False
        return True

    def run(self) -> None:
        """Run the scheduler loop.

        Collects traffic data at the configured interval until stopped.
        Interval is measured between collection START times.
        """
        if not self._check_api_key():
            sys.exit(1)

        log.info(
            "Starting traffic scheduler: interval=%ds, max_runtime=%s",
            self.config.interval_seconds,
            f"{self.config.max_runtime_seconds}s" if self.config.max_runtime_seconds else "indefinite",
        )

        self._start_time = time.time()
        self._next_scheduled_start = self._start_time

        while not self._stop_event.is_set():
            # Check max runtime
            if self.config.max_runtime_seconds and self._start_time:
                elapsed = time.time() - self._start_time
                if elapsed >= self.config.max_runtime_seconds:
                    log.info("Max runtime reached (%.1fs), stopping", elapsed)
                    break

            now = time.time()

            # If we're past the scheduled start time, note it
            if now >= self._next_scheduled_start:
                delay = now - self._next_scheduled_start
                if delay > 1.0:  # Only log if significantly delayed
                    log.warning(
                        "Collection start delayed by %.1fs (interval=%.1fs, previous collection ran long)",
                        delay,
                        self.config.interval_seconds,
                    )

            # Try to acquire collection lock (prevents overlapping runs)
            if not self._collection_lock.acquire(blocking=False):
                log.warning("Previous collection still running, waiting for completion...")
                # Wait for the lock to be released, then check if we should proceed
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

            # Schedule next start based on THIS collection's start time
            self._next_scheduled_start = collection_start_time + self.config.interval_seconds

            # Sleep until next scheduled start
            self._sleep_until_next_start()

        log.info("Traffic scheduler stopped. Total runs: %d", self._run_count)

    def _run_collection_cycle(self, collection_start_time: float) -> None:
        """Execute one collection cycle."""
        self._run_count += 1

        log.info("Starting collection run #%d at %s", self._run_count, datetime.now(SG_OFFSET).isoformat())

        try:
            result = self.collector.collect_once()
            self._last_result = result
            duration = time.time() - collection_start_time

            if result.errors:
                log.error(
                    "Collection run #%d FAILED: received=%d, stored=%d, zones_mapped=%d, zones_unmapped=%d, "
                    "duration=%.2fs, errors=%s",
                    self._run_count,
                    result.records_received,
                    result.records_stored,
                    result.records_updated,
                    result.zones_mapped,
                    result.zones_unmapped,
                    duration,
                    result.errors,
                )
            else:
                log.info(
                    "Collection run #%d SUCCESS: received=%d, stored=%d (updated=%d), zones_mapped=%d, "
                    "zones_unmapped=%d, duration=%.2fs, observed_at=%s",
                    self._run_count,
                    result.records_received,
                    result.records_stored,
                    result.records_updated,
                    result.zones_mapped,
                    result.zones_unmapped,
                    duration,
                    result.timestamp,
                )

        except Exception as e:
            duration = time.time() - collection_start_time
            log.error(
                "Collection run #%d EXCEPTION: duration=%.2fs, error=%s",
                self._run_count,
                duration,
                e,
            )
            self._last_result = CollectionResult(
                timestamp=datetime.now(SG_OFFSET).isoformat(),
                records_received=0,
                records_stored=0,
                records_updated=0,
                zones_mapped=0,
                zones_unmapped=0,
                errors=[f"Collection exception: {e}"],
            )

    def _schedule_next_start(self) -> None:
        """Schedule the next collection start time."""
        if self._next_scheduled_start is None:
            self._next_scheduled_start = time.time()
        else:
            self._next_scheduled_start += self.config.interval_seconds

    def _sleep_until_next_start(self) -> None:
        """Sleep until the next scheduled collection start time."""
        now = time.time()
        sleep_time = max(0, self._next_scheduled_start - now)

        if sleep_time > 0:
            log.debug("Sleeping %.2fs until next collection start", sleep_time)
            self._stop_event.wait(timeout=sleep_time)

    def get_last_result(self) -> Optional[CollectionResult]:
        """Get the result of the most recent collection run."""
        return self._last_result

    def is_running(self) -> bool:
        """Check if a collection is currently in progress."""
        return self._collection_in_progress


def run_scheduler(
    interval_seconds: int = 300,
    max_runtime_seconds: Optional[int] = None,
) -> None:
    """Convenience function to run the scheduler with given config.

    Args:
        interval_seconds: Collection interval in seconds (default 300 = 5 min).
        max_runtime_seconds: Optional max runtime in seconds (None = indefinite).
    """
    config = SchedulerConfig(
        interval_seconds=interval_seconds,
        max_runtime_seconds=max_runtime_seconds,
    )
    scheduler = TrafficScheduler(config=config)
    scheduler.run()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="UrbanOS LTA Traffic Speed Bands Scheduler",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Collection interval in seconds (default: 300 = 5 minutes)",
    )
    parser.add_argument(
        "--max-runtime",
        type=int,
        default=None,
        help="Maximum runtime in seconds (default: run indefinitely)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    run_scheduler(
        interval_seconds=args.interval,
        max_runtime_seconds=args.max_runtime,
    )