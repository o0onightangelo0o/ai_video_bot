"""
Configuration loader.

Reads all settings from environment variables (optionally from a `.env` file
via python-dotenv). No secret is ever hard-coded here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env(key: str, default: str | None = None, *, required: bool = False) -> str:
    """Return an environment variable, raising if it is required and missing."""
    value = os.getenv(key, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value or ""


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_list(key: str, default: str = "") -> list[str]:
    raw = os.getenv(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Immutable application settings."""

    # --- Telegram ---------------------------------------------------------
    bot_token: str = field(default_factory=lambda: _env("BOT_TOKEN", required=True))
    admin_ids: list[int] = field(
        default_factory=lambda: [int(x) for x in _env_list("ADMIN_ID")]
    )

    # --- Run mode: "polling" (local) or "webhook" (production) ------------
    mode: str = field(default_factory=lambda: _env("MODE", "polling").lower())
    webhook_base_url: str = field(default_factory=lambda: _env("WEBHOOK_BASE_URL", ""))
    webhook_path: str = field(default_factory=lambda: _env("WEBHOOK_PATH", "/telegram/webhook"))
    webhook_secret: str = field(default_factory=lambda: _env("WEBHOOK_SECRET", ""))
    host: str = field(default_factory=lambda: _env("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))

    # --- Video providers ----------------------------------------------------
    # Comma-separated priority list, e.g. "replicate,fal,mock"
    provider_order: list[str] = field(
        default_factory=lambda: _env_list("PROVIDER_ORDER", "mock")
    )
    replicate_api_key: str = field(default_factory=lambda: _env("REPLICATE_API_KEY", ""))
    replicate_model: str = field(
        default_factory=lambda: _env("REPLICATE_MODEL", "wan-video/wan-2.1-1.3b")
    )
    fal_api_key: str = field(default_factory=lambda: _env("FAL_API_KEY", ""))
    fal_model: str = field(
        default_factory=lambda: _env("FAL_MODEL", "fal-ai/ltx-video")
    )
    # Generic key kept for compatibility with the spec (VIDEO_API_KEY)
    video_api_key: str = field(default_factory=lambda: _env("VIDEO_API_KEY", ""))

    job_poll_interval: int = field(default_factory=lambda: _env_int("JOB_POLL_INTERVAL", 5))
    job_timeout: int = field(default_factory=lambda: _env_int("JOB_TIMEOUT", 900))

    # --- Limits / protection -------------------------------------------------
    max_requests_per_hour: int = field(
        default_factory=lambda: _env_int("MAX_REQUESTS_PER_HOUR", 3)
    )
    queue_workers: int = field(default_factory=lambda: _env_int("QUEUE_WORKERS", 2))
    max_queue_size: int = field(default_factory=lambda: _env_int("MAX_QUEUE_SIZE", 50))
    prompt_min_len: int = field(default_factory=lambda: _env_int("PROMPT_MIN_LEN", 5))
    prompt_max_len: int = field(default_factory=lambda: _env_int("PROMPT_MAX_LEN", 500))
    banned_words: list[str] = field(
        default_factory=lambda: [w.lower() for w in _env_list("BANNED_WORDS", "")]
    )

    # --- Storage / logs ------------------------------------------------------
    db_path: str = field(default_factory=lambda: _env("DB_PATH", str(BASE_DIR / "data" / "bot.db")))
    log_dir: str = field(default_factory=lambda: _env("LOG_DIR", str(BASE_DIR / "logs")))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO").upper())
    default_lang: str = field(default_factory=lambda: _env("DEFAULT_LANG", "en"))

    def is_admin(self, user_id: int) -> bool:
        """Return True if the given Telegram user id is an administrator."""
        return user_id in self.admin_ids


settings = Settings()
