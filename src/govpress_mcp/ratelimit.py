from __future__ import annotations

import asyncio
import inspect
import threading
import time
import urllib.error
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable

MIN_INTERVAL_SECONDS = 0.3
MAX_RETRIES = 5

_throttle_lock = threading.Lock()
_last_request_monotonic = 0.0
_stats_lock = threading.Lock()


@dataclass
class RetryStats:
    seen_429: int = 0
    recovered_429: int = 0
    failed_429: int = 0
    seen_503: int = 0
    recovered_503: int = 0
    failed_503: int = 0


class RetryableError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


_retry_stats = RetryStats()


def _is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, RetryableError):
        return exc.status_code in {429, 503}
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in {429, 503}
    if isinstance(exc, (TimeoutError, urllib.error.URLError)):
        return True
    return False


def _retry_status_code(exc: Exception) -> int | None:
    if isinstance(exc, RetryableError):
        return exc.status_code
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code
    return None


def reset_retry_stats() -> None:
    global _retry_stats
    with _stats_lock:
        _retry_stats = RetryStats()


def get_retry_stats() -> RetryStats:
    with _stats_lock:
        return RetryStats(
            seen_429=_retry_stats.seen_429,
            recovered_429=_retry_stats.recovered_429,
            failed_429=_retry_stats.failed_429,
            seen_503=_retry_stats.seen_503,
            recovered_503=_retry_stats.recovered_503,
            failed_503=_retry_stats.failed_503,
        )


def _record_seen(status_code: int) -> None:
    with _stats_lock:
        if status_code == 429:
            _retry_stats.seen_429 += 1
        elif status_code == 503:
            _retry_stats.seen_503 += 1


def _record_recovered(status_code: int) -> None:
    with _stats_lock:
        if status_code == 429:
            _retry_stats.recovered_429 += 1
        elif status_code == 503:
            _retry_stats.recovered_503 += 1


def _record_failed(status_code: int) -> None:
    with _stats_lock:
        if status_code == 429:
            _retry_stats.failed_429 += 1
        elif status_code == 503:
            _retry_stats.failed_503 += 1


async def throttle() -> None:
    global _last_request_monotonic
    with _throttle_lock:
        now = time.monotonic()
        remaining = MIN_INTERVAL_SECONDS - (now - _last_request_monotonic)
    if remaining > 0:
        await asyncio.sleep(remaining)
    with _throttle_lock:
        _last_request_monotonic = time.monotonic()


def with_retry(func: Callable[..., Any]) -> Callable[..., Any]:
    if inspect.iscoroutinefunction(func):
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = 1.0
            seen_codes: set[int] = set()
            for attempt in range(MAX_RETRIES + 1):
                try:
                    result = await func(*args, **kwargs)
                    for status_code in seen_codes:
                        _record_recovered(status_code)
                    return result
                except Exception as exc:
                    status_code = _retry_status_code(exc)
                    if status_code in {429, 503}:
                        _record_seen(status_code)
                        seen_codes.add(status_code)
                    if attempt >= MAX_RETRIES or not _is_retryable_exception(exc):
                        for failed_code in seen_codes:
                            _record_failed(failed_code)
                        raise
                    await asyncio.sleep(delay)
                    delay *= 2

        return async_wrapper

    @wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        delay = 1.0
        seen_codes: set[int] = set()
        for attempt in range(MAX_RETRIES + 1):
            try:
                result = func(*args, **kwargs)
                for status_code in seen_codes:
                    _record_recovered(status_code)
                return result
            except Exception as exc:
                status_code = _retry_status_code(exc)
                if status_code in {429, 503}:
                    _record_seen(status_code)
                    seen_codes.add(status_code)
                if attempt >= MAX_RETRIES or not _is_retryable_exception(exc):
                    for failed_code in seen_codes:
                        _record_failed(failed_code)
                    raise
                time.sleep(delay)
                delay *= 2

    return sync_wrapper
