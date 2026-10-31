"""Fixed-window rate limiting backed by Redis.

The limiter fails open: if Redis is unreachable, requests go through and a warning is logged.
Availability of sign-in matters more than throttling during a Redis outage.
"""

import logging
import time
from typing import Protocol

from redis.asyncio import Redis
from redis.asyncio import from_url as redis_from_url

from mindnest_api.errors import AppError

logger = logging.getLogger("mindnest.ratelimit")


class Limiter(Protocol):
    async def check(self, key: str, limit: int, window_seconds: int) -> None:
        """Count one hit for key; raise AppError(429) when it is over the limit."""
        ...


class RedisLimiter:
    def __init__(self, url: str) -> None:
        self._client: Redis = redis_from_url(url, socket_connect_timeout=1, socket_timeout=1)

    async def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = int(time.time())
        bucket = now // window_seconds
        redis_key = f"rl:{key}:{bucket}"
        try:
            count = await self._client.incr(redis_key)
            if count == 1:
                await self._client.expire(redis_key, window_seconds + 1)
        except Exception:
            logger.warning("Rate limiter unavailable; allowing request", exc_info=True)
            return
        if count > limit:
            retry_after = max(1, (bucket + 1) * window_seconds - now)
            raise AppError(
                429,
                "rate_limited",
                "Too many attempts. Please wait a little and try again.",
                headers={"Retry-After": str(retry_after)},
            )

    async def aclose(self) -> None:
        await self._client.aclose()
