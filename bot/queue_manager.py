"""
Asynchronous job queue.

Jobs are persisted in SQLite first, then their ids are pushed into an
`asyncio.Queue` consumed by N worker coroutines. On startup, any job left in
`queued`/`running` state (e.g. after a redeploy) is re-enqueued.
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from loguru import logger

from .config import settings
from .database import Database
from .video_service import JobCancelled, ProviderError, VideoRequest, VideoService

# Signature: async def deliver(job: dict, result_url: str | None, error: str | None)
Deliver = Callable[[dict, str | None, str | None], Awaitable[None]]
Notify = Callable[[dict, str], Awaitable[None]]


class QueueFull(Exception):
    """Raised when the in-memory queue reached `MAX_QUEUE_SIZE`."""


class QueueManager:
    """Coordinates workers that pull jobs and run them through VideoService."""

    def __init__(
        self,
        db: Database,
        video: VideoService,
        deliver: Deliver,
        notify: Notify,
    ) -> None:
        self._db = db
        self._video = video
        self._deliver = deliver
        self._notify = notify
        self._queue: asyncio.Queue[int] = asyncio.Queue(maxsize=settings.max_queue_size)
        self._workers: list[asyncio.Task] = []
        self._cancel_flags: set[int] = set()
        self._running = 0
        self._backoff_until = 0.0

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        """Spawn workers and re-enqueue jobs left over from a previous run."""
        for job in await self._db.get_pending_jobs():
            await self._db.update_job(job["id"], status="queued")
            self._queue.put_nowait(job["id"])
        for i in range(settings.queue_workers):
            self._workers.append(asyncio.create_task(self._worker(i), name=f"worker-{i}"))
        logger.info("Queue started with {} workers, {} recovered jobs",
                    settings.queue_workers, self._queue.qsize())

    async def stop(self) -> None:
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    # ------------------------------------------------------------- public API
    @property
    def size(self) -> int:
        return self._queue.qsize()

    @property
    def running(self) -> int:
        """Number of jobs currently being rendered."""
        return self._running

    def eta_minutes(self, position: int) -> int:
        """
        Rough wait estimate for a job at `position` (1-based) in the queue,
        given the worker count and the provider's average render time.
        """
        workers = max(1, settings.queue_workers)
        waves = (position + self._running + workers - 1) // workers
        return max(1, round(waves * settings.avg_render_seconds / 60))

    async def enqueue(self, job_id: int) -> int:
        """Add a persisted job to the queue. Returns the position (1-based)."""
        if self._queue.full():
            raise QueueFull()
        self._queue.put_nowait(job_id)
        return self._queue.qsize()

    async def cancel(self, job_id: int) -> bool:
        """Mark a job cancelled; the worker will stop at the next poll tick."""
        job = await self._db.get_job(job_id)
        if not job or job["status"] not in ("queued", "running"):
            return False
        self._cancel_flags.add(job_id)
        await self._db.update_job(job_id, status="cancelled", finished_at=time.time())
        return True

    # ---------------------------------------------------------------- worker
    async def _worker(self, idx: int) -> None:
        logger.info("Worker {} started", idx)
        while True:
            job_id = await self._queue.get()
            # Global cool-down after a provider 429 (rate limit).
            delay = self._backoff_until - time.time()
            if delay > 0:
                logger.info("Worker {} cooling down {:.0f}s (provider rate limit)", idx, delay)
                await asyncio.sleep(delay)
            self._running += 1
            try:
                await self._process(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("Worker {} crashed on job {}", idx, job_id)
            finally:
                self._running -= 1
                self._queue.task_done()

    async def _process(self, job_id: int) -> None:
        job = await self._db.get_job(job_id)
        if not job:
            return
        if job["status"] == "cancelled" or job_id in self._cancel_flags:
            self._cancel_flags.discard(job_id)
            return

        await self._db.update_job(job_id, status="running", started_at=time.time())
        await self._notify(job, "started")

        req = VideoRequest(
            prompt=job["prompt"],
            aspect_ratio=job["aspect_ratio"],
            duration=int(job["duration"]),
            style=job["style"],
        )

        async def is_cancelled() -> bool:
            if job_id in self._cancel_flags:
                return True
            fresh = await self._db.get_job(job_id)
            return bool(fresh and fresh["status"] == "cancelled")

        async def on_switch(provider: str) -> None:
            await self._db.update_job(job_id, provider=provider)
            await self._notify(job, f"fallback:{provider}")

        try:
            result = await self._video.generate(
                req, is_cancelled=is_cancelled, on_provider_switch=on_switch
            )
        except JobCancelled:
            self._cancel_flags.discard(job_id)
            logger.info("Job {} cancelled", job_id)
            return
        except ProviderError as exc:
            if "429" in str(exc):
                # Provider is throttling us: pause all workers for a while.
                self._backoff_until = time.time() + 120
                logger.warning("Provider rate-limited; pausing workers for 120s")
            await self._db.update_job(
                job_id, status="failed", error=str(exc)[:500], finished_at=time.time()
            )
            await self._deliver(job, None, str(exc))
            return

        await self._db.update_job(
            job_id,
            status="done",
            provider=result.provider,
            provider_job=result.provider_job_id,
            video_url=result.video_url,
            finished_at=time.time(),
        )
        await self._deliver(job, result.video_url, None)
