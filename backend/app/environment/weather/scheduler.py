"""Controlled weather forecast collection scheduler for NEA 24-hour Weather Forecast.

Runs collect_weather_once() repeatedly at a configurable interval.
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
from typing import Any, Dict, List, Optional

from backend.app.environment.weather.collector import (
    WeatherCollectionResult,
    WeatherForecastCollector,
    collect_weather_once,
)
from backend.app.environment.weather.storage import WeatherForecastStore

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))


@dataclass
class SchedulerConfig:
    """Configuration for the weather scheduler."""
    interval_seconds: int = 14400  # 4 hours default (NEA updates ~4x/day)
    max_runtime_seconds: Optional[int] = None  # None = run indefinitely


class WeatherScheduler:
    """Scheduler for periodic NEA 24h weather forecast collection.

    Features:
    - Configurable interval (default 4 hours) measured between COLLECTION STARTS
    - No overlapping collections (sequential execution)
    - Graceful shutdown on SIGINT/SIGTERM
    - Logs each collection result
    - If collection exceeds interval, next starts immediately with warning
    """

    def __init__(
        self,
        config: Optional[SchedulerConfig] = None,
        collector: Optional[WeatherForecastCollector] = None,
    ) -> None:
        self.config = config or SchedulerConfig()
        self.collector = collector or WeatherForecastCollector()
        self._stop_event = Event()
        self._collection_lock = Lock()
        self._collection_in_progress = False
        self._last_result: Optional[WeatherCollectionResult] = None
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

    def run(self) -> None:
        """Run the scheduler loop.

        Collects weather data at the configured interval until stopped.
        Interval is measured between collection START times.
        """
        log.info(
            "Starting weather scheduler: interval=%ds, max_runtime=%s",
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

        log.info("Weather scheduler stopped. Total runs: %d", self._run_count)

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
                    "Collection run #%d FAILED: national_received=%d, national_stored=%d, period_received=%d, period_stored=%d, "
                    "duration=%.2fs, errors=%s",
                    self._run_count,
                    result.national_forecasts_received,
                    result.national_forecasts_stored,
                    result.period_forecasts_received,
                    result.period_forecasts_stored,
                    duration,
                    result.errors,
                )
            else:
                log.info(
                    "Collection run #%d SUCCESS: national_received=%d, national_stored=%d (updated=%d), period_received=%d, period_stored=%d (updated=%d), duration=%.2fs, observed_at=%s",
                    self._run_count,
                    result.national_forecasts_received,
                    result.national_forecasts_stored,
                    result.national_forecasts_updated,
                    result.period_forecasts_received,
                    result.period_forecasts_stored,
                    result.period_forecasts_updated,
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
            self._last_result = WeatherCollectionResult(
                timestamp=datetime.now(SG_OFFSET).isoformat(),
                national_forecasts_received=0,
                national_forecasts_stored=0,
                national_forecasts_updated=0,
                period_forecasts_received=0,
                period_forecasts_stored=0,
                period_forecasts_updated=0,
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

    def get_last_result(self) -> Optional[WeatherCollectionResult]:
        """Get the result of the most recent collection run."""
        return self._last_result

    def is_running(self) -> bool:
        """Check if a collection is currently in progress."""
        return self._collection_in_progress


def run_weather_scheduler(
    interval_seconds: int = 14400,
    max_runtime_seconds: Optional[int] = None,
) -> None:
    """Convenience function to run the scheduler with given config.

    Args:
        interval_seconds: Collection interval in seconds (default: 14400 = 4 hours).
        max_runtime_seconds: Optional max runtime in seconds (None = indefinite).
    """
    config = SchedulerConfig(
        interval_seconds=interval_seconds,
        max_runtime_seconds=max_runtime_seconds,
    )
    scheduler = WeatherScheduler(config=config)
    scheduler.run()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="UrbanOS NEA Weather Forecast Scheduler",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=14400,
        help="Collection interval in seconds (default: 14400 = 4 hours)",
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

    run_weather_scheduler(
        interval_seconds=args.interval,
        max_runtime_seconds=args.max_runtime,
    )