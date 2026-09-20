"""
Video generation service.

Provides a common `BaseProvider` interface plus concrete implementations:

* ``ReplicateProvider`` – Replicate predictions API (Wan / Minimax / LTX ...)
* ``FalProvider``       – fal.ai queue API (LTX-Video, etc.)
* ``MockProvider``      – free, offline provider for local testing

`VideoService` tries providers in the configured priority order and falls back
automatically when one raises `ProviderError`.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

import httpx
from loguru import logger

from .config import settings

ProgressCallback = Callable[[str], Awaitable[None]]

# A tiny public sample video used by MockProvider so the whole flow can be
# exercised end-to-end without paying for any API.
_MOCK_SAMPLE_URLS = (
    "https://download.samplelib.com/mp4/sample-5s.mp4",
    "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_1MB.mp4",
    "https://filesamples.com/samples/video/mp4/sample_640x360.mp4",
)


class ProviderError(Exception):
    """Raised by a provider when generation fails for a recoverable reason."""


class JobCancelled(Exception):
    """Raised when the job was cancelled by the user while polling."""


@dataclass
class VideoRequest:
    """Normalised request passed to every provider."""

    prompt: str
    aspect_ratio: str = "16:9"  # 16:9 | 9:16 | 1:1
    duration: int = 5  # seconds
    style: str = "none"

    @property
    def full_prompt(self) -> str:
        """Prompt enriched with the optional artistic style."""
        if self.style and self.style != "none":
            return f"{self.prompt}, {self.style} style"
        return self.prompt


@dataclass
class VideoResult:
    """Successful generation result."""

    video_url: str
    provider: str
    provider_job_id: str
    elapsed: float


class BaseProvider(ABC):
    """Abstract async provider."""

    name: str = "base"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True when the provider has the credentials it needs."""

    @abstractmethod
    async def submit(self, req: VideoRequest) -> str:
        """Submit a job and return the provider-side job id."""

    @abstractmethod
    async def poll(self, job_id: str) -> tuple[str, Optional[str], Optional[str]]:
        """
        Return ``(status, video_url, error)``.

        ``status`` must be one of: ``pending``, ``done``, ``failed``.
        """

    async def cancel(self, job_id: str) -> None:  # noqa: B027 - optional hook
        """Best-effort remote cancellation (no-op by default)."""

    async def generate(
        self,
        req: VideoRequest,
        *,
        is_cancelled: Callable[[], Awaitable[bool]],
        on_progress: Optional[ProgressCallback] = None,
    ) -> VideoResult:
        """Submit then poll until completion, honouring cancellation/timeout."""
        start = time.time()
        job_id = await self.submit(req)
        logger.info("[{}] submitted job {}", self.name, job_id)

        while True:
            if await is_cancelled():
                await self.cancel(job_id)
                raise JobCancelled()

            if time.time() - start > settings.job_timeout:
                await self.cancel(job_id)
                raise ProviderError(f"{self.name}: job timed out after {settings.job_timeout}s")

            status, url, err = await self.poll(job_id)
            logger.debug("[{}] job {} status={}", self.name, job_id, status)
            if status == "done" and url:
                return VideoResult(url, self.name, job_id, time.time() - start)
            if status == "failed":
                raise ProviderError(f"{self.name}: {err or 'generation failed'}")

            if on_progress:
                await on_progress(status)
            await asyncio.sleep(settings.job_poll_interval)


# ---------------------------------------------------------------------------
# Replicate
# ---------------------------------------------------------------------------
class ReplicateProvider(BaseProvider):
    """Replicate predictions API. Works with most text-to-video models."""

    name = "replicate"
    _BASE = "https://api.replicate.com/v1"

    def is_configured(self) -> bool:
        return bool(settings.replicate_api_key or settings.video_api_key)

    @property
    def _headers(self) -> dict[str, str]:
        key = settings.replicate_api_key or settings.video_api_key
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    async def submit(self, req: VideoRequest) -> str:
        # Input keys differ slightly between models; these are the most common.
        payload = {
            "input": {
                "prompt": req.full_prompt,
                "aspect_ratio": req.aspect_ratio,
                "num_frames": min(max(req.duration, 1), 10) * 16 + 1,
                "duration": req.duration,
            }
        }
        model = settings.replicate_model
        url = f"{self._BASE}/models/{model}/predictions"
        try:
            r = await self._client.post(url, json=payload, headers=self._headers, timeout=60)
        except httpx.HTTPError as exc:
            raise ProviderError(f"replicate network error: {exc}") from exc
        if r.status_code >= 400:
            raise ProviderError(f"replicate HTTP {r.status_code}: {r.text[:200]}")
        return r.json()["id"]

    async def poll(self, job_id: str) -> tuple[str, Optional[str], Optional[str]]:
        try:
            r = await self._client.get(
                f"{self._BASE}/predictions/{job_id}", headers=self._headers, timeout=30
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"replicate network error: {exc}") from exc
        if r.status_code >= 400:
            raise ProviderError(f"replicate HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        status = data.get("status")
        if status == "succeeded":
            output = data.get("output")
            url = output[0] if isinstance(output, list) else output
            return "done", url, None
        if status in ("failed", "canceled"):
            return "failed", None, str(data.get("error") or status)
        return "pending", None, None

    async def cancel(self, job_id: str) -> None:
        try:
            await self._client.post(
                f"{self._BASE}/predictions/{job_id}/cancel", headers=self._headers, timeout=15
            )
        except httpx.HTTPError:
            pass


# ---------------------------------------------------------------------------
# fal.ai
# ---------------------------------------------------------------------------
class FalProvider(BaseProvider):
    """fal.ai queue API (https://fal.ai)."""

    name = "fal"
    _QUEUE = "https://queue.fal.run"

    def is_configured(self) -> bool:
        return bool(settings.fal_api_key)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Key {settings.fal_api_key}", "Content-Type": "application/json"}

    async def submit(self, req: VideoRequest) -> str:
        payload = {
            "prompt": req.full_prompt,
            "aspect_ratio": req.aspect_ratio,
        }
        try:
            r = await self._client.post(
                f"{self._QUEUE}/{settings.fal_model}", json=payload, headers=self._headers, timeout=60
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"fal network error: {exc}") from exc
        if r.status_code >= 400:
            raise ProviderError(f"fal HTTP {r.status_code}: {r.text[:200]}")
        return r.json()["request_id"]

    async def poll(self, job_id: str) -> tuple[str, Optional[str], Optional[str]]:
        model = settings.fal_model
        try:
            r = await self._client.get(
                f"{self._QUEUE}/{model}/requests/{job_id}/status", headers=self._headers, timeout=30
            )
            if r.status_code >= 400:
                raise ProviderError(f"fal HTTP {r.status_code}: {r.text[:200]}")
            status = r.json().get("status")
            if status == "COMPLETED":
                res = await self._client.get(
                    f"{self._QUEUE}/{model}/requests/{job_id}", headers=self._headers, timeout=30
                )
                data = res.json()
                video = data.get("video") or {}
                url = video.get("url") if isinstance(video, dict) else video
                return ("done", url, None) if url else ("failed", None, "no video in response")
            if status in ("FAILED", "CANCELLED"):
                return "failed", None, status
            return "pending", None, None
        except httpx.HTTPError as exc:
            raise ProviderError(f"fal network error: {exc}") from exc

    async def cancel(self, job_id: str) -> None:
        try:
            await self._client.put(
                f"{self._QUEUE}/{settings.fal_model}/requests/{job_id}/cancel",
                headers=self._headers,
                timeout=15,
            )
        except httpx.HTTPError:
            pass


# ---------------------------------------------------------------------------
# Mock (free)
# ---------------------------------------------------------------------------
class MockProvider(BaseProvider):
    """
    Offline provider for development. Simulates a ~20s render and returns a
    public sample clip. Fails deliberately if the prompt contains "FAIL" so the
    fallback path can be tested.
    """

    name = "mock"
    _jobs: dict[str, float] = {}

    def is_configured(self) -> bool:
        return True

    async def submit(self, req: VideoRequest) -> str:
        if "FAIL" in req.prompt:
            raise ProviderError("mock: forced failure for testing")
        job_id = f"mock-{int(time.time() * 1000)}"
        self._jobs[job_id] = time.time()
        return job_id

    async def poll(self, job_id: str) -> tuple[str, Optional[str], Optional[str]]:
        started = self._jobs.get(job_id)
        if started is None:
            return "failed", None, "unknown job"
        if time.time() - started >= 20:
            self._jobs.pop(job_id, None)
            # Pick the first sample that is actually reachable right now.
            for url in _MOCK_SAMPLE_URLS:
                try:
                    r = await self._client.head(url, timeout=10)
                    logger.info("mock: sample {} -> HTTP {}", url, r.status_code)
                    if r.status_code < 400:
                        return "done", url, None
                except httpx.HTTPError as exc:
                    logger.warning("mock: sample {} unreachable: {}", url, exc)
                    continue
            return "failed", None, "mock: no sample video reachable"
        return "pending", None, None


# ---------------------------------------------------------------------------
# Orchestrator with fallback
# ---------------------------------------------------------------------------
_REGISTRY: dict[str, type[BaseProvider]] = {
    ReplicateProvider.name: ReplicateProvider,
    FalProvider.name: FalProvider,
    MockProvider.name: MockProvider,
}


class VideoService:
    """Tries each configured provider in order until one succeeds."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(follow_redirects=True)
        self._providers: list[BaseProvider] = []
        for name in settings.provider_order:
            cls = _REGISTRY.get(name)
            if cls is None:
                logger.warning("Unknown provider '{}' ignored", name)
                continue
            provider = cls(self._client)
            if provider.is_configured():
                self._providers.append(provider)
            else:
                logger.warning("Provider '{}' skipped (not configured)", name)
        if not self._providers:
            logger.warning("No provider configured — falling back to MockProvider")
            self._providers.append(MockProvider(self._client))
        logger.info("Providers (priority): {}", [p.name for p in self._providers])

    @property
    def provider_names(self) -> list[str]:
        return [p.name for p in self._providers]

    async def close(self) -> None:
        await self._client.aclose()

    async def generate(
        self,
        req: VideoRequest,
        *,
        is_cancelled: Callable[[], Awaitable[bool]],
        on_provider_switch: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> VideoResult:
        """
        Generate a video with automatic fallback.

        Raises:
            JobCancelled: user cancelled the job.
            ProviderError: every provider failed.
        """
        errors: list[str] = []
        for idx, provider in enumerate(self._providers):
            if idx > 0 and on_provider_switch:
                await on_provider_switch(provider.name)
            try:
                return await provider.generate(req, is_cancelled=is_cancelled)
            except JobCancelled:
                raise
            except ProviderError as exc:
                logger.warning("Provider {} failed: {}", provider.name, exc)
                errors.append(str(exc))
            except Exception as exc:  # noqa: BLE001 - never crash the worker
                logger.exception("Unexpected error in provider {}", provider.name)
                errors.append(f"{provider.name}: {exc}")
        raise ProviderError(" | ".join(errors) or "all providers failed")

    async def url_ok(self, url: str) -> bool:
        """Return True if the URL answers with a 2xx/3xx to a HEAD/GET request."""
        try:
            r = await self._client.head(url, timeout=15)
            if r.status_code == 405:
                r = await self._client.get(url, timeout=15, headers={"Range": "bytes=0-0"})
            return r.status_code < 400
        except httpx.HTTPError:
            return False

    async def download(self, url: str, max_bytes: int = 49 * 1024 * 1024) -> bytes | None:
        """Download a video into memory (Telegram bot upload limit is 50 MB)."""
        try:
            async with self._client.stream("GET", url, timeout=120) as r:
                r.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                async for chunk in r.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        return None
                    chunks.append(chunk)
                return b"".join(chunks)
        except (httpx.HTTPError, Exception) as exc:  # noqa: BLE001
            logger.warning("Download failed for {}: {!r}", url, exc)
            return None
