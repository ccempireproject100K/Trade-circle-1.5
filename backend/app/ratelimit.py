"""Sliding-window rate limiting.

In-process only: with more than one app worker, move the counters to a shared
store (Redis or Mongo TTL collection) so limits hold across workers.
"""
import math
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float, clock=time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> None:
        """Record a hit for key, or raise 429 if the key is over its limit."""
        now = self._clock()
        hits = self._hits[key]
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            retry_after = math.ceil(hits[0] + self.window - now)
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many attempts. Try again later.",
                headers={"Retry-After": str(max(retry_after, 1))},
            )
        hits.append(now)


def client_ip(request: Request) -> str:
    if request.app.state.settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Our proxy appends the address it saw, so the last entry is the one we can trust.
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"
