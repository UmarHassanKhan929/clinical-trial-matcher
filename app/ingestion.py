"""FR-1: pull recruiting studies from ClinicalTrials.gov API v2 politely and cache them."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from .fhir_study import to_research_study

CTGOV_URL = "https://clinicaltrials.gov/api/v2/studies"


class AsyncRateLimiter:
    """Sliding-window limiter: at most `max_calls` acquisitions in any `period` seconds."""

    def __init__(
        self,
        max_calls: int = 3,
        period: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._max = max_calls
        self._period = period
        self._clock = clock
        self._sleep = sleep
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._clock()
                while self._calls and now - self._calls[0] >= self._period:
                    self._calls.popleft()
                if len(self._calls) < self._max:
                    self._calls.append(now)
                    return
                await self._sleep(self._period - (now - self._calls[0]))


class TTLCache:
    """In-memory cache whose entries expire `ttl_seconds` after being written."""

    def __init__(self, ttl_seconds: float = 12 * 3600, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._data: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires_at, value = item
        if self._clock() >= expires_at:
            del self._data[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (self._clock() + self._ttl, value)


class TrialRepository:
    """Fetches RECRUITING studies for a condition and returns them as FHIR ResearchStudy dicts."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        limiter: AsyncRateLimiter | None = None,
        cache: TTLCache | None = None,
        page_size: int = 50,
        max_pages: int = 2,
    ) -> None:
        self._http = http
        self._limiter = limiter or AsyncRateLimiter(3, 1.0)
        self._cache = cache or TTLCache()
        self._page_size = page_size
        self._max_pages = max_pages

    async def recruiting_for(self, condition: str) -> list[dict[str, Any]]:
        key = condition.strip().lower()
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        studies: list[dict[str, Any]] = []
        token: str | None = None
        for _ in range(self._max_pages):
            await self._limiter.acquire()
            params = {
                "query.cond": condition,
                "filter.overallStatus": "RECRUITING",
                "pageSize": str(self._page_size),
                "format": "json",
            }
            if token:
                params["pageToken"] = token
            response = await self._http.get(CTGOV_URL, params=params)
            response.raise_for_status()
            data = response.json()
            for raw in data.get("studies", []):
                resource = to_research_study(raw)
                if resource:
                    studies.append(resource)
            token = data.get("nextPageToken")
            if not token:
                break

        self._cache.set(key, studies)
        return studies