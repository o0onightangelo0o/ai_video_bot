"""
Per-user sliding-window rate limiter backed by SQLite.

Because the counter is derived from the `jobs` table, limits survive restarts
and are consistent across multiple workers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .config import settings
from .database import Database


@dataclass
class RateLimitResult:
    """Outcome of a rate-limit check."""

    allowed: bool
    used: int
    limit: int
    retry_after: int  # seconds until the oldest request falls out of the window


class RateLimiter:
    """Sliding one-hour window: at most `limit` jobs per user per hour."""

    WINDOW_SECONDS = 3600

    def __init__(self, db: Database, limit: int) -> None:
        self._db = db
        self._limit = limit

    async def check(self, user_id: int) -> RateLimitResult:
        """Return whether the user may create a new job right now.

        Administrators are exempt from all limits.
        """
        if settings.is_admin(user_id):
            return RateLimitResult(True, 0, 0, 0)
        now = time.time()
        since = now - self.WINDOW_SECONDS
        used = await self._db.count_user_jobs_since(user_id, since)
        if used < self._limit:
            return RateLimitResult(True, used, self._limit, 0)

        oldest = await self._db.oldest_job_ts_since(user_id, since)
        retry_after = int(max(1, (oldest or now) + self.WINDOW_SECONDS - now))
        return RateLimitResult(False, used, self._limit, retry_after)
