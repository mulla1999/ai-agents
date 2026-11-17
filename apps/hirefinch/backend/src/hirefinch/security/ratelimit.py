"""Fixed-window rate limits for sign-in, sign-up and reset endpoints.

With ``HIREFINCH_REDIS_URL`` set, counters live in Redis and are shared by every backend instance.
Without it (or if Redis is unreachable) an in-process counter is used, which is correct for a single
instance. Account lockout after repeated failures is separate and stored in the database.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

log = logging.getLogger(__name__)


class MemoryLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def hit(self, key: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > window:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def clear(self) -> None:
        self._hits.clear()


class RedisLimiter:
    def __init__(self, url: str) -> None:
        import redis.asyncio as redis

        self._redis = redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
        self._fallback = MemoryLimiter()

    async def hit(self, key: str, limit: int, window: int) -> bool:
        bucket = f"hirefinch:rl:{key}:{int(time.time() // window)}"
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                count, _ = await pipe.incr(bucket).expire(bucket, window).execute()
        except Exception as exc:  # Redis down: keep protecting, per instance
            log.warning("rate limiter falling back to memory: %s", exc.__class__.__name__)
            return await self._fallback.hit(key, limit, window)
        return int(count) <= limit

    def clear(self) -> None:
        self._fallback.clear()


def build_limiter(redis_url: str | None) -> MemoryLimiter | RedisLimiter:
    return RedisLimiter(redis_url) if redis_url else MemoryLimiter()
