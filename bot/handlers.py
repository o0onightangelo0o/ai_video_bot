"""
Telegram command, message and callback handlers (aiogram v3).

The generation wizard is implemented with aiogram's FSM:
    prompt -> aspect ratio -> duration -> style -> confirm
"""

from __future__ import annotations

import html
import time
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter, Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from loguru import logger

from . import keyboards as kb
from .config import settings
from .database import Database
from .i18n import normalize_lang, t
from .queue_manager import QueueFull, QueueManager
from .rate_limiter import RateLimiter
from .video_service import VideoService

router = Router(name="main")


class IsAdmin(BaseFilter):
    """Allow only Telegram ids listed in ADMIN_ID (single source of truth)."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        ok = bool(user) and settings.is_admin(user.id)
        if not ok and user:
            logger.warning("Unauthorised admin attempt by {} (@{}): {}",
                           user.id, user.username,
                           getattr(event, "text", None) or getattr(event, "data", None))
        return ok


class GenerateFlow(StatesGroup):
    """FSM states of the /generate wizard."""

    prompt = State()
    aspect = State()
    duration = State()
    style = State()
    confirm = State()


# ---------------------------------------------------------------------------
# Shared context injected via Dispatcher workflow_data (see main.py)
# ---------------------------------------------------------------------------
class Services:
    """Bundle of singletons made available to every handler."""

    def __init__(
        self,
        db: Database,
        queue: QueueManager,
        limiter: RateLimiter,
        video: VideoService,
    ) -> None:
        self.db = db
        self.queue = queue
        self.limiter = limiter
        self.video = video


async def _ensure_user(msg_or_cb: Message | CallbackQuery, svc: Services) -> tuple[dict[str, Any], str]:
    """Upsert the user and return (row, lang). Raises PermissionError if banned."""
    user = msg_or_cb.from_user
    assert user is not None
    row = await svc.db.get_user(user.id)
    lang = row["lang"] if row else normalize_lang(user.language_code, settings.default_lang)
    row = await svc.db.upsert_user(user.id, user.username, user.first_name, lang)
    if await svc.db.is_banned(user.id):
        raise PermissionError
    return row, row["lang"]


def _validate_prompt(text: str, lang: str, user_id: int = 0) -> str | None:
    """Return an error message if the prompt is invalid, else None. Admins skip filters."""
    text = text.strip()
    if len(text) < settings.prompt_min_len:
        return t("prompt_too_short", lang, n=settings.prompt_min_len)
    if settings.is_admin(user_id):
        return None
    if len(text) > settings.prompt_max_len:
        return t("prompt_too_long", lang, n=settings.prompt_max_len)
    lowered = text.lower()
    if any(word in lowered for word in settings.banned_words):
        return t("prompt_banned", lang)
    return None


# ---------------------------------------------------------------------------
# Basic commands
# ---------------------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(message: Message, svc: Services, state: FSMContext) -> None:
    """Welcome message + short instructions."""
    await state.clear()
    try:
        _, lang = await _ensure_user(message, svc)
    except PermissionError:
        await message.answer(t("banned", "en"))
        return
    name = html.escape(message.from_user.first_name or "")
    await message.answer(t("welcome", lang, name=name, limit=settings.max_requests_per_hour))


@router.message(Command("help"))
async def cmd_help(message: Message, svc: Services) -> None:
    """Detailed help."""
    try:
        _, lang = await _ensure_user(message, svc)
    except PermissionError:
        return
    await message.answer(
        t("help", lang, max_len=settings.prompt_max_len,
          providers=", ".join(svc.video.provider_names))
    )


@router.message(Command("lang"))
async def cmd_lang(message: Message, svc: Services) -> None:
    """Language switcher."""
    try:
        _, lang = await _ensure_user(message, svc)
    except PermissionError:
        return
    await message.answer(t("lang_choose", lang), reply_markup=kb.language_keyboard())


@router.callback_query(F.data.startswith("lang:"))
async def cb_lang(cb: CallbackQuery, svc: Services) -> None:
    lang = cb.data.split(":", 1)[1]
    await svc.db.set_user_lang(cb.from_user.id, lang)
    await cb.message.edit_text(t("lang_set", lang))
    await cb.answer()


# ---------------------------------------------------------------------------
# /generate wizard
# ---------------------------------------------------------------------------
@router.message(Command("generate"))
async def cmd_generate(message: Message, svc: Services, state: FSMContext) -> None:
    """Entry point of the wizard: checks ban, active job and rate limit."""
    try:
        _, lang = await _ensure_user(message, svc)
    except PermissionError:
        await message.answer(t("banned", "en"))
        return

    active = await svc.db.get_active_job(message.from_user.id)
    if active and not settings.is_admin(message.from_user.id):
        await message.answer(t("already_active", lang, job_id=active["id"]))
        return

    rl = await svc.limiter.check(message.from_user.id)
    if not rl.allowed:
        await message.answer(
            t("rate_limited", lang, used=rl.used, limit=rl.limit,
              minutes=max(1, rl.retry_after // 60))
        )
        return

    await state.set_state(GenerateFlow.prompt)
    await state.update_data(lang=lang)
    await message.answer(t("ask_prompt", lang))


@router.message(GenerateFlow.prompt, F.text & ~F.text.startswith("/"))
async def step_prompt(message: Message, state: FSMContext) -> None:
    """Receive and validate the prompt."""
    data = await state.get_data()
    lang = data.get("lang", "en")
    error = _validate_prompt(message.text or "", lang, message.from_user.id)
    if error:
        await message.answer(error)
        return
    await state.update_data(prompt=message.text.strip())
    await state.set_state(GenerateFlow.aspect)
    await message.answer(t("ask_aspect", lang), reply_markup=kb.aspect_keyboard(lang))


@router.callback_query(GenerateFlow.aspect, F.data.startswith("asp:"))
async def step_aspect(cb: CallbackQuery, state: FSMContext) -> None:
    aspect = cb.data.split(":", 1)[1]
    if aspect not in kb.ASPECT_RATIOS:
        await cb.answer()
        return
    data = await state.update_data(aspect=aspect)
    lang = data["lang"]
    await state.set_state(GenerateFlow.duration)
    await cb.message.edit_text(t("ask_duration", lang), reply_markup=kb.duration_keyboard(lang))
    await cb.answer()


@router.callback_query(GenerateFlow.duration, F.data.startswith("dur:"))
async def step_duration(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        duration = int(cb.data.split(":", 1)[1])
    except ValueError:
        await cb.answer()
        return
    if duration not in kb.DURATIONS:
        await cb.answer()
        return
    data = await state.update_data(duration=duration)
    lang = data["lang"]
    await state.set_state(GenerateFlow.style)
    await cb.message.edit_text(t("ask_style", lang), reply_markup=kb.style_keyboard(lang))
    await cb.answer()


@router.callback_query(GenerateFlow.style, F.data.startswith("sty:"))
async def step_style(cb: CallbackQuery, state: FSMContext) -> None:
    style = cb.data.split(":", 1)[1]
    if style not in kb.STYLES:
        await cb.answer()
        return
    data = await state.update_data(style=style)
    lang = data["lang"]
    await state.set_state(GenerateFlow.confirm)
    await cb.message.edit_text(
        t("confirm", lang,
          prompt=html.escape(data["prompt"]),
          aspect=data["aspect"],
          duration=data["duration"],
          style=t(f"style_{style}", lang)),
        reply_markup=kb.confirm_keyboard(lang),
    )
    await cb.answer()


@router.callback_query(F.data == "go:cancel")
async def cb_flow_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    """Cancel the wizard at any step."""
    data = await state.get_data()
    lang = data.get("lang", "en")
    await state.clear()
    await cb.message.edit_text(t("flow_cancelled", lang))
    await cb.answer()


@router.callback_query(GenerateFlow.confirm, F.data == "go:confirm")
async def cb_confirm(cb: CallbackQuery, state: FSMContext, svc: Services) -> None:
    """Persist the job and push it to the queue."""
    data = await state.get_data()
    lang = data.get("lang", "en")
    await state.clear()
    user_id = cb.from_user.id

    # Re-check limits at the last moment (state may be stale).
    if not settings.is_admin(user_id) and await svc.db.get_active_job(user_id):
        await cb.answer(t("already_active", lang, job_id=0), show_alert=True)
        return
    rl = await svc.limiter.check(user_id)
    if not rl.allowed:
        await cb.message.edit_text(
            t("rate_limited", lang, used=rl.used, limit=rl.limit,
              minutes=max(1, rl.retry_after // 60))
        )
        await cb.answer()
        return

    job_id = await svc.db.create_job(
        user_id=user_id,
        chat_id=cb.message.chat.id,
        prompt=data["prompt"],
        aspect_ratio=data["aspect"],
        duration=data["duration"],
        style=data["style"],
    )
    try:
        pos = await svc.queue.enqueue(job_id)
    except QueueFull:
        await svc.db.update_job(job_id, status="cancelled", error="queue full")
        await cb.message.edit_text(t("queue_full", lang))
        await cb.answer()
        return

    logger.info("User {} queued job {} (pos {})", user_id, job_id, pos)
    await cb.message.edit_text(
        t("queued", lang, job_id=job_id, pos=pos, eta=svc.queue.eta_minutes(pos)),
        reply_markup=kb.cancel_job_keyboard(lang, job_id),
    )
    await cb.answer()


# ---------------------------------------------------------------------------
# /status & /cancel
# ---------------------------------------------------------------------------
@router.message(Command("status"))
async def cmd_status(message: Message, svc: Services) -> None:
    """Show the user's current job."""
    try:
        _, lang = await _ensure_user(message, svc)
    except PermissionError:
        return
    job = await svc.db.get_active_job(message.from_user.id)
    if not job:
        await message.answer(t("status_none", lang))
        return
    elapsed = int(time.time() - (job["started_at"] or job["created_at"]))
    await message.answer(
        t("status", lang,
          job_id=job["id"],
          status=t(f"status_{job['status']}", lang),
          prompt=html.escape(job["prompt"]),
          provider=job["provider"] or "—",
          elapsed=elapsed,
          ahead=svc.queue.size if job["status"] == "queued" else 0,
          eta=(svc.queue.eta_minutes(svc.queue.size) if job["status"] == "queued"
               else max(1, round((settings.avg_render_seconds - elapsed) / 60)))),
        reply_markup=kb.cancel_job_keyboard(lang, job["id"]),
    )


async def _cancel_active(user_id: int, svc: Services) -> int | None:
    job = await svc.db.get_active_job(user_id)
    if not job:
        return None
    ok = await svc.queue.cancel(job["id"])
    return job["id"] if ok else None


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, svc: Services, state: FSMContext) -> None:
    """Cancel wizard or the active job."""
    try:
        _, lang = await _ensure_user(message, svc)
    except PermissionError:
        return
    if await state.get_state() is not None:
        await state.clear()
        await message.answer(t("flow_cancelled", lang))
        return
    job_id = await _cancel_active(message.from_user.id, svc)
    if job_id is None:
        await message.answer(t("cancel_none", lang))
    else:
        await message.answer(t("cancelled", lang, job_id=job_id))


@router.callback_query(F.data.startswith("job:cancel:"))
async def cb_cancel_job(cb: CallbackQuery, svc: Services) -> None:
    """Inline cancel button for a queued/running job."""
    row = await svc.db.get_user(cb.from_user.id)
    lang = row["lang"] if row else "en"
    try:
        job_id = int(cb.data.rsplit(":", 1)[1])
    except ValueError:
        await cb.answer()
        return
    job = await svc.db.get_job(job_id)
    if not job or job["user_id"] != cb.from_user.id:
        await cb.answer()
        return
    if await svc.queue.cancel(job_id):
        await cb.message.edit_text(t("cancelled", lang, job_id=job_id))
    else:
        await cb.answer(t("cancel_none", lang), show_alert=True)
        return
    await cb.answer()


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
PAGE = 10


def _fmt_user(u: dict) -> str:
    handle = f"@{u['username']}" if u.get("username") else html.escape(u.get("first_name") or "—")
    return f"{handle} (<code>{u['user_id']}</code>)"


def _fmt_date(ts: float | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d %H:%M")


async def _stats_text(svc: Services) -> str:
    s = await svc.db.stats()
    by_provider = "\n".join(f"   • {k}: {v}" for k, v in s["by_provider"].items()) or "   • —"
    top = "\n".join(f"   {i+1}. {_fmt_user(u)} — {u['c']}" for i, u in enumerate(s["top_users"])) or "   —"
    return (
        "📈 <b>Bot statistics</b>\n\n"
        f"👥 Users: <b>{s['users_total']}</b>  (new 24h: {s['users_new_24h']}, active 24h: {s['users_24h']})\n"
        f"🎬 Videos requested: <b>{s['jobs_total']}</b>  (24h: {s['jobs_24h']})\n"
        f"   ✅ generated: <b>{s['jobs_done']}</b>  ❌ failed: {s['jobs_failed']}  ⏳ active: {s['jobs_active']}\n"
        f"🚫 Banned: {s['banned']}   📦 Queue now: {svc.queue.size}\n"
        f"⚙️ Providers: {', '.join(svc.video.provider_names)}\n"
        f"🏁 Generated by provider:\n{by_provider}\n"
        f"🏆 Top users:\n{top}\n\n"
        "Commands: /users · /prompts · /prompts &lt;user_id&gt; · /export"
    )


async def _users_page(svc: Services, page: int) -> tuple[str, bool]:
    rows = await svc.db.list_users(PAGE + 1, page * PAGE)
    has_next = len(rows) > PAGE
    rows = rows[:PAGE]
    lines = [f"👥 <b>Users</b> — page {page + 1}\n"]
    for u in rows:
        lines.append(
            f"• {_fmt_user(u)} [{u['lang']}]\n"
            f"   🎬 {u['jobs_done'] or 0}/{u['jobs_total'] or 0} videos · last seen {_fmt_date(u['last_seen'])}"
        )
    if not rows:
        lines.append("—")
    return "\n".join(lines), has_next


async def _prompts_page(svc: Services, page: int, user_id: int | None) -> tuple[str, bool]:
    rows = await svc.db.list_prompts(PAGE + 1, page * PAGE, user_id)
    has_next = len(rows) > PAGE
    rows = rows[:PAGE]
    total = await svc.db.count_prompts(user_id)
    title = f"📝 <b>Prompts</b> ({total}) — page {page + 1}"
    if user_id:
        title += f" — user <code>{user_id}</code>"
    lines = [title + "\n"]
    icon = {"done": "✅", "failed": "❌", "cancelled": "🛑", "queued": "⏳", "running": "🎬"}
    for j in rows:
        who = f"@{j['username']}" if j.get("username") else str(j["user_id"])
        lines.append(
            f"{icon.get(j['status'], '•')} <b>#{j['id']}</b> {html.escape(who)} · {_fmt_date(j['created_at'])} · "
            f"{j['aspect_ratio']} {j['duration']}s\n"
            f"   <i>{html.escape(j['prompt'][:160])}</i>"
        )
    if not rows:
        lines.append("—")
    return "\n".join(lines), has_next


@router.message(Command("stats"), IsAdmin())
async def cmd_stats(message: Message, svc: Services) -> None:
    """Usage statistics (admin only)."""
    await message.answer(await _stats_text(svc), reply_markup=kb.admin_menu())


@router.message(Command("users"), IsAdmin())
async def cmd_users(message: Message, svc: Services) -> None:
    """List users with video counts (admin only)."""
    if not settings.is_admin(message.from_user.id):
        return
    text, has_next = await _users_page(svc, 0)
    await message.answer(text, reply_markup=kb.admin_pager("users", 0, has_next))


@router.message(Command("prompts"), IsAdmin())
async def cmd_prompts(message: Message, svc: Services) -> None:
    """List recent prompts, optionally for one user: /prompts [user_id] (admin only)."""
    if not settings.is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    uid = int(parts[1]) if len(parts) > 1 and parts[1].lstrip("-").isdigit() else None
    text, has_next = await _prompts_page(svc, 0, uid)
    await message.answer(text, reply_markup=kb.admin_pager("prompts", 0, has_next, str(uid or "")))


@router.message(Command("export"), IsAdmin())
async def cmd_export(message: Message, svc: Services) -> None:
    """Send all prompts as a CSV file (admin only)."""
    if not settings.is_admin(message.from_user.id):
        return
    await _send_export(message.chat.id, svc, message.bot)


async def _send_export(chat_id: int, svc: Services, bot: Bot) -> None:
    csv_text = await svc.db.export_prompts_csv()
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M")
    file = BufferedInputFile(("\ufeff" + csv_text).encode("utf-8"), filename=f"prompts_{stamp}.csv")
    await bot.send_document(chat_id, file, caption="📥 All prompts (CSV, UTF-8)")


@router.callback_query(F.data.startswith("adm:"), IsAdmin())
async def cb_admin(cb: CallbackQuery, svc: Services) -> None:
    """Pagination / shortcuts for admin lists."""
    if not settings.is_admin(cb.from_user.id):
        await cb.answer()
        return
    parts = cb.data.split(":")
    kind = parts[1]
    try:
        if kind == "noop":
            pass
        elif kind == "export":
            await _send_export(cb.message.chat.id, svc, cb.bot)
        elif kind == "users":
            page = int(parts[2])
            text, has_next = await _users_page(svc, page)
            await cb.message.edit_text(text, reply_markup=kb.admin_pager("users", page, has_next))
        elif kind == "prompts":
            page = int(parts[2])
            uid = int(parts[3]) if len(parts) > 3 and parts[3] else None
            text, has_next = await _prompts_page(svc, page, uid)
            await cb.message.edit_text(
                text, reply_markup=kb.admin_pager("prompts", page, has_next, str(uid or ""))
            )
    except Exception as exc:  # noqa: BLE001 - e.g. "message is not modified"
        logger.debug("admin callback: {}", exc)
    await cb.answer()


@router.message(Command("ban"), IsAdmin())
async def cmd_ban(message: Message, svc: Services) -> None:
    """/ban <user_id> [reason] — admin only."""
    if not settings.is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Usage: /ban <user_id> [reason]")
        return
    reason = parts[2] if len(parts) > 2 else ""
    target = int(parts[1])
    if settings.is_admin(target):
        await message.answer("⛔ Cannot ban an administrator.")
        return
    await svc.db.ban(target, reason)
    logger.info("ADMIN {} banned {} ({})", message.from_user.id, target, reason)
    await message.answer(f"🚫 User <code>{target}</code> banned." + (f"\nReason: {html.escape(reason)}" if reason else ""))


@router.message(Command("banned"), IsAdmin())
async def cmd_banned(message: Message, svc: Services) -> None:
    """List banned users (admin only)."""
    rows = await svc.db.list_banned()
    if not rows:
        await message.answer("✅ Blacklist is empty.")
        return
    lines = ["🚫 <b>Banned users</b>\n"]
    for r in rows:
        who = f"@{r['username']}" if r.get("username") else (r.get("first_name") or "?")
        lines.append(f"• {html.escape(who)} (<code>{r['user_id']}</code>) — {html.escape(r['reason'] or '—')}")
    await message.answer("\n".join(lines))


@router.message(Command("unban"), IsAdmin())
async def cmd_unban(message: Message, svc: Services) -> None:
    """/unban <user_id> — admin only."""
    if not settings.is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Usage: /unban <user_id>")
        return
    await svc.db.unban(int(parts[1]))
    logger.info("ADMIN {} unbanned {}", message.from_user.id, parts[1])
    await message.answer(f"✅ User <code>{parts[1]}</code> unbanned.")


@router.message(Command("stats", "users", "prompts", "export", "ban", "unban", "banned"))
async def cmd_admin_denied(message: Message, svc: Services) -> None:
    """Anyone who is not the admin gets a polite refusal."""
    row = await svc.db.get_user(message.from_user.id)
    lang = row["lang"] if row else normalize_lang(message.from_user.language_code, settings.default_lang)
    await message.answer(t("admin_only", lang))


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------
@router.message(F.text)
async def fallback_text(message: Message, svc: Services) -> None:
    """Any text outside the wizard."""
    try:
        _, lang = await _ensure_user(message, svc)
    except PermissionError:
        return
    await message.answer(t("unknown", lang))


# ---------------------------------------------------------------------------
# Delivery callbacks used by QueueManager (need the Bot instance)
# ---------------------------------------------------------------------------
def make_callbacks(bot: Bot, db: Database, video: VideoService):
    """Build the `deliver` and `notify` coroutines bound to a Bot instance."""

    async def _lang(user_id: int) -> str:
        row = await db.get_user(user_id)
        return row["lang"] if row else "en"

    async def notify(job: dict, event: str) -> None:
        lang = await _lang(job["user_id"])
        try:
            if event == "started":
                await bot.send_message(job["chat_id"],
                                       t("started", lang, job_id=job["id"],
                                         eta=max(1, round(settings.avg_render_seconds / 60))),
                                       reply_markup=kb.cancel_job_keyboard(lang, job["id"]))
            elif event.startswith("fallback:"):
                await bot.send_message(job["chat_id"],
                                       t("fallback", lang, provider=event.split(":", 1)[1]))
        except Exception:  # noqa: BLE001
            logger.exception("notify failed for job {}", job["id"])

    async def deliver(job: dict, url: str | None, error: str | None) -> None:
        lang = await _lang(job["user_id"])
        chat_id = job["chat_id"]
        logger.info("deliver job {}: url={} error={}", job["id"], url, error)
        try:
            if error or not url:
                await bot.send_message(
                    chat_id,
                    t("failed", lang, job_id=job["id"], error=html.escape((error or "")[:300])),
                )
                return

            fresh = await db.get_job(job["id"]) or job
            caption = t(
                "done_caption", lang,
                prompt=html.escape(job["prompt"][:700]),
                aspect=job["aspect_ratio"],
                duration=job["duration"],
                style=t(f"style_{job['style']}", lang),
                provider=fresh.get("provider") or "",
            )
            data = await video.download(url)
            logger.info("job {}: downloaded {} bytes", job["id"], len(data) if data else None)
            if data is None:
                # Could not fetch the file (too large or provider blocked direct
                # download). Only expose the link if it is actually reachable.
                if not url.startswith("file://") and await video.url_ok(url):
                    await bot.send_message(chat_id, caption + "\n\n" + t("done_link", lang, url=url))
                else:
                    await db.update_job(job["id"], status="failed", error="video unreachable")
                    await bot.send_message(
                        chat_id, t("failed", lang, job_id=job["id"], error="video file unreachable")
                    )
                return
            file = BufferedInputFile(data, filename=f"video_{job['id']}.mp4")
            try:
                await bot.send_video(chat_id, file, caption=caption, supports_streaming=True)
                logger.info("job {}: video sent", job["id"])
            except Exception as exc:  # noqa: BLE001 - fall back to document
                logger.warning("send_video failed for job {} ({}), sending as document", job["id"], exc)
                file = BufferedInputFile(data, filename=f"video_{job['id']}.mp4")
                await bot.send_document(chat_id, file, caption=caption)
        except Exception:  # noqa: BLE001
            logger.exception("deliver failed for job {}", job["id"])
            try:
                await bot.send_message(chat_id, t("error_generic", lang))
            except Exception:  # noqa: BLE001
                pass

    return deliver, notify
