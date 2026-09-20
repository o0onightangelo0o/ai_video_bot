"""
SQLite persistence layer (async via aiosqlite).

Tables:
    users      - Telegram users, language, ban flag
    jobs       - Video generation jobs and their lifecycle
    blacklist  - Banned user ids (with optional reason)
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

import aiosqlite
from loguru import logger

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    lang        TEXT NOT NULL DEFAULT 'en',
    created_at  REAL NOT NULL,
    last_seen   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    chat_id       INTEGER NOT NULL,
    prompt        TEXT NOT NULL,
    aspect_ratio  TEXT NOT NULL DEFAULT '16:9',
    duration      INTEGER NOT NULL DEFAULT 5,
    style         TEXT NOT NULL DEFAULT 'none',
    status        TEXT NOT NULL DEFAULT 'queued',  -- queued|running|done|failed|cancelled
    provider      TEXT,
    provider_job  TEXT,
    video_url     TEXT,
    error         TEXT,
    created_at    REAL NOT NULL,
    started_at    REAL,
    finished_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_jobs_user_created ON jobs(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS blacklist (
    user_id   INTEGER PRIMARY KEY,
    reason    TEXT,
    added_at  REAL NOT NULL
);
"""


class Database:
    """Thin async wrapper around a single SQLite connection."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: Optional[aiosqlite.Connection] = None

    # ------------------------------------------------------------------ setup
    async def connect(self) -> None:
        """Open the connection and ensure the schema exists."""
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        logger.info("Database ready at {}", self._path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    # ------------------------------------------------------------------ users
    async def upsert_user(
        self, user_id: int, username: str | None, first_name: str | None, lang: str
    ) -> dict[str, Any]:
        """Create the user if missing, otherwise refresh metadata. Returns the row."""
        now = time.time()
        await self.conn.execute(
            """
            INSERT INTO users (user_id, username, first_name, lang, created_at, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_seen = excluded.last_seen
            """,
            (user_id, username, first_name, lang, now, now),
        )
        await self.conn.commit()
        return await self.get_user(user_id)  # type: ignore[return-value]

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        async with self.conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def set_user_lang(self, user_id: int, lang: str) -> None:
        await self.conn.execute("UPDATE users SET lang = ? WHERE user_id = ?", (lang, user_id))
        await self.conn.commit()

    # -------------------------------------------------------------- blacklist
    async def is_banned(self, user_id: int) -> bool:
        async with self.conn.execute(
            "SELECT 1 FROM blacklist WHERE user_id = ?", (user_id,)
        ) as cur:
            return await cur.fetchone() is not None

    async def ban(self, user_id: int, reason: str = "") -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO blacklist (user_id, reason, added_at) VALUES (?, ?, ?)",
            (user_id, reason, time.time()),
        )
        await self.conn.commit()

    async def unban(self, user_id: int) -> None:
        await self.conn.execute("DELETE FROM blacklist WHERE user_id = ?", (user_id,))
        await self.conn.commit()

    # ------------------------------------------------------------------- jobs
    async def create_job(
        self,
        user_id: int,
        chat_id: int,
        prompt: str,
        aspect_ratio: str,
        duration: int,
        style: str,
    ) -> int:
        """Insert a new queued job and return its id."""
        cur = await self.conn.execute(
            """
            INSERT INTO jobs (user_id, chat_id, prompt, aspect_ratio, duration, style, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)
            """,
            (user_id, chat_id, prompt, aspect_ratio, duration, style, time.time()),
        )
        await self.conn.commit()
        return int(cur.lastrowid)

    async def get_job(self, job_id: int) -> dict[str, Any] | None:
        async with self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_active_job(self, user_id: int) -> dict[str, Any] | None:
        """Return the user's currently queued/running job, if any."""
        async with self.conn.execute(
            """
            SELECT * FROM jobs
            WHERE user_id = ? AND status IN ('queued', 'running')
            ORDER BY created_at DESC LIMIT 1
            """,
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_pending_jobs(self) -> list[dict[str, Any]]:
        """Jobs that were queued/running when the process last stopped."""
        async with self.conn.execute(
            "SELECT * FROM jobs WHERE status IN ('queued', 'running') ORDER BY created_at"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def update_job(self, job_id: int, **fields: Any) -> None:
        """Update arbitrary columns of a job."""
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        await self.conn.execute(
            f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id)
        )
        await self.conn.commit()

    async def count_user_jobs_since(self, user_id: int, since_ts: float) -> int:
        """Count jobs (not cancelled) created by the user since a timestamp."""
        async with self.conn.execute(
            """
            SELECT COUNT(*) FROM jobs
            WHERE user_id = ? AND created_at >= ? AND status NOT IN ('cancelled', 'failed')
            """,
            (user_id, since_ts),
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0

    async def oldest_job_ts_since(self, user_id: int, since_ts: float) -> float | None:
        async with self.conn.execute(
            """
            SELECT MIN(created_at) FROM jobs
            WHERE user_id = ? AND created_at >= ? AND status NOT IN ('cancelled', 'failed')
            """,
            (user_id, since_ts),
        ) as cur:
            row = await cur.fetchone()
            return float(row[0]) if row and row[0] is not None else None

    # ------------------------------------------------------------ admin lists
    async def list_users(self, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        """Users with their video counts, most recently active first."""
        async with self.conn.execute(
            """
            SELECT u.user_id, u.username, u.first_name, u.lang, u.created_at, u.last_seen,
                   COUNT(j.id) AS jobs_total,
                   SUM(CASE WHEN j.status='done' THEN 1 ELSE 0 END) AS jobs_done
            FROM users u LEFT JOIN jobs j ON j.user_id = u.user_id
            GROUP BY u.user_id ORDER BY u.last_seen DESC LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def list_prompts(
        self, limit: int = 20, offset: int = 0, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Recent prompts (all users, or one user) with status and author."""
        where = "WHERE j.user_id = ?" if user_id else ""
        params: tuple = (user_id, limit, offset) if user_id else (limit, offset)
        async with self.conn.execute(
            f"""
            SELECT j.id, j.user_id, j.prompt, j.aspect_ratio, j.duration, j.style,
                   j.status, j.provider, j.created_at, u.username, u.first_name
            FROM jobs j LEFT JOIN users u ON u.user_id = j.user_id
            {where} ORDER BY j.created_at DESC LIMIT ? OFFSET ?
            """,
            params,
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def count_prompts(self, user_id: int | None = None) -> int:
        sql = "SELECT COUNT(*) FROM jobs" + (" WHERE user_id = ?" if user_id else "")
        async with self.conn.execute(sql, (user_id,) if user_id else ()) as cur:
            return int((await cur.fetchone())[0])

    async def export_prompts_csv(self) -> str:
        """Return every job as CSV text (for /export)."""
        import csv
        import io
        from datetime import datetime, timezone

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["job_id", "user_id", "username", "date_utc", "status", "provider",
                    "aspect", "duration", "style", "prompt"])
        async with self.conn.execute(
            """
            SELECT j.*, u.username FROM jobs j LEFT JOIN users u ON u.user_id = j.user_id
            ORDER BY j.id
            """
        ) as cur:
            async for r in cur:
                w.writerow([
                    r["id"], r["user_id"], r["username"] or "",
                    datetime.fromtimestamp(r["created_at"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
                    r["status"], r["provider"] or "", r["aspect_ratio"], r["duration"],
                    r["style"], r["prompt"],
                ])
        return buf.getvalue()

    # ------------------------------------------------------------------ stats
    async def stats(self) -> dict[str, Any]:
        """Aggregate statistics for the admin /stats command."""
        out: dict[str, Any] = {}
        queries = {
            "users_total": "SELECT COUNT(*) FROM users",
            "users_24h": "SELECT COUNT(*) FROM users WHERE last_seen >= ?",
            "jobs_total": "SELECT COUNT(*) FROM jobs",
            "jobs_24h": "SELECT COUNT(*) FROM jobs WHERE created_at >= ?",
            "users_new_24h": "SELECT COUNT(*) FROM users WHERE created_at >= ?",
            "jobs_done": "SELECT COUNT(*) FROM jobs WHERE status = 'done'",
            "jobs_failed": "SELECT COUNT(*) FROM jobs WHERE status = 'failed'",
            "jobs_active": "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')",
            "banned": "SELECT COUNT(*) FROM blacklist",
        }
        day_ago = time.time() - 86400
        for key, sql in queries.items():
            params = (day_ago,) if "?" in sql else ()
            async with self.conn.execute(sql, params) as cur:
                row = await cur.fetchone()
                out[key] = int(row[0]) if row else 0
        async with self.conn.execute(
            "SELECT provider, COUNT(*) c FROM jobs WHERE status='done' GROUP BY provider"
        ) as cur:
            out["by_provider"] = {r["provider"] or "?": r["c"] for r in await cur.fetchall()}
        async with self.conn.execute(
            """
            SELECT u.user_id, u.username, u.first_name, COUNT(j.id) c
            FROM jobs j JOIN users u ON u.user_id = j.user_id
            WHERE j.status='done' GROUP BY u.user_id ORDER BY c DESC LIMIT 5
            """
        ) as cur:
            out["top_users"] = [dict(r) for r in await cur.fetchall()]
        return out
