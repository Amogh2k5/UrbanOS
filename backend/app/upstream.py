"""Small shared primitives for rate-limited upstream data sources."""
from __future__ import annotations

import email.utils
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Generic, Hashable, Optional, TypeVar

T = TypeVar("T")


@dataclass
class _Entry(Generic[T]):
    expires_at: float
    value: Optional[T] = None
    error: Optional[BaseException] = None
    failed: bool = False


class SingleFlightTTLCache:
    """Per-key TTL cache that coalesces concurrent loads without global blocking."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[Hashable, _Entry] = {}
        self._in_flight: dict[Hashable, threading.Event] = {}

    def get_or_fetch(
        self,
        key: Hashable,
        fetch: Callable[[], T],
        *,
        ttl_seconds: float,
        error_ttl_seconds: float = 0.0,
        cache_result: Optional[Callable[[T], bool]] = None,
    ) -> T:
        while True:
            with self._lock:
                entry = self._entries.get(key)
                if entry is not None and entry.expires_at > time.monotonic():
                    if entry.error is not None:
                        raise entry.error
                    return entry.value  # type: ignore[return-value]
                if entry is not None:
                    self._entries.pop(key, None)
                event = self._in_flight.get(key)
                if event is None:
                    event = threading.Event()
                    self._in_flight[key] = event
                    owner = True
                else:
                    owner = False
            if owner:
                break
            event.wait()

        try:
            value = fetch()
        except BaseException as exc:
            with self._lock:
                if error_ttl_seconds > 0:
                    self._entries[key] = _Entry(
                        time.monotonic() + error_ttl_seconds, error=exc
                    )
                self._in_flight.pop(key).set()
            raise

        should_cache = cache_result(value) if cache_result is not None else True
        ttl = ttl_seconds if should_cache else error_ttl_seconds
        with self._lock:
            if ttl > 0:
                self._entries[key] = _Entry(time.monotonic() + ttl, value=value, failed=not should_cache)
            self._in_flight.pop(key).set()
        return value

    def clear(self, key: Optional[Hashable] = None, *, preserve_errors: bool = False) -> None:
        with self._lock:
            if key is None:
                if preserve_errors:
                    self._entries = {k: v for k, v in self._entries.items() if v.error is not None or v.failed}
                else:
                    self._entries.clear()
            else:
                entry = self._entries.get(key)
                if not (preserve_errors and entry is not None and (entry.error is not None or entry.failed)):
                    self._entries.pop(key, None)


def http_status_code(exc: BaseException) -> Optional[int]:
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) or getattr(exc, "code", None)


def retry_after_seconds(exc: BaseException, *, now: Optional[datetime] = None) -> Optional[float]:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or getattr(exc, "headers", None) or {}
    raw = headers.get("Retry-After") if hasattr(headers, "get") else None
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        try:
            target = email.utils.parsedate_to_datetime(str(raw))
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            current = now or datetime.now(timezone.utc)
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            return max(0.0, (target - current).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def retry_429_delay(
    exc: BaseException,
    attempt: int,
    *,
    base_seconds: float = 1.0,
    max_seconds: float = 30.0,
    jitter: Callable[[float, float], float] = random.uniform,
) -> Optional[float]:
    """Return a jittered exponential delay only for 429 responses."""
    if http_status_code(exc) != 429:
        return None
    retry_after = retry_after_seconds(exc)
    if retry_after is not None:
        return retry_after
    ceiling = min(base_seconds * (2 ** attempt), max_seconds)
    return jitter(0.0, ceiling)


def with_429_retry(
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    base_seconds: float = 1.0,
    max_seconds: float = 30.0,
    sleep: Optional[Callable[[float], None]] = None,
) -> T:
    """Retry only HTTP 429 errors, with bounded attempts and Retry-After."""
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:
            delay = retry_429_delay(
                exc, attempt, base_seconds=base_seconds, max_seconds=max_seconds
            )
            if delay is None or attempt >= attempts - 1:
                raise
            (sleep or time.sleep)(delay)
    raise RuntimeError("429 retry loop exited unexpectedly")
