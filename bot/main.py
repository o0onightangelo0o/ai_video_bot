"""
Application entry point.

* ``MODE=polling``  – long polling (local development, VPS).
* ``MODE=webhook``  – aiohttp web server receiving Telegram updates on
  ``WEBHOOK_PATH`` and exposing ``/health`` for uptime monitors.

Run:  python -m bot.main
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from loguru import logger

from .config import settings
from .database import Database
from .handlers import Services, make_callbacks, router
from .queue_manager import QueueManager
from .rate_limiter import RateLimiter
from .video_service import VideoService


def setup_logging() -> None:
    """Console + rotating file logs."""
    Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stdout, level=settings.log_level,
               format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | "
                      "<cyan>{name}</cyan>:<cyan>{line}</cyan> - {message}")
    logger.add(Path(settings.log_dir) / "bot_{time:YYYY-MM-DD}.log",
               level=settings.log_level, rotation="00:00", retention="7 days",
               compression="zip", enqueue=True, encoding="utf-8")


async def set_commands(bot: Bot) -> None:
    """Register the command menu in both languages."""
    en = [
        BotCommand(command="start", description="Start / welcome"),
        BotCommand(command="generate", description="Generate a video"),
        BotCommand(command="status", description="Current job status"),
        BotCommand(command="cancel", description="Cancel current job"),
        BotCommand(command="lang", description="Change language"),
        BotCommand(command="help", description="Help"),
    ]
    ar = [
        BotCommand(command="start", description="البداية / الترحيب"),
        BotCommand(command="generate", description="توليد فيديو"),
        BotCommand(command="status", description="حالة الطلب الحالي"),
        BotCommand(command="cancel", description="إلغاء الطلب الحالي"),
        BotCommand(command="lang", description="تغيير اللغة"),
        BotCommand(command="help", description="المساعدة"),
    ]
    await bot.set_my_commands(en)
    await bot.set_my_commands(ar, language_code="ar")
    admin_cmds = en + [
        BotCommand(command="stats", description="📈 Statistics"),
        BotCommand(command="users", description="👥 Users list"),
        BotCommand(command="prompts", description="📝 Prompts list"),
        BotCommand(command="export", description="📥 Export CSV"),
        BotCommand(command="ban", description="🚫 Ban user  (/ban <id> [reason])"),
        BotCommand(command="unban", description="✅ Unban user"),
        BotCommand(command="banned", description="📋 Banned list"),
    ]
    for admin_id in settings.admin_ids:
        try:
            await bot.set_my_commands(admin_cmds, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception as exc:  # noqa: BLE001 - admin may not have started the bot yet
            logger.warning("Could not set admin commands for {}: {}", admin_id, exc)


async def build() -> tuple[Bot, Dispatcher, Services]:
    """Wire all components together."""
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    db = Database(settings.db_path)
    await db.connect()

    video = VideoService()
    deliver, notify = make_callbacks(bot, db, video)
    queue = QueueManager(db, video, deliver, notify)
    limiter = RateLimiter(db, settings.max_requests_per_hour)

    svc = Services(db=db, queue=queue, limiter=limiter, video=video)
    dp["svc"] = svc  # injected into handlers as the `svc` argument
    dp.include_router(router)

    @dp.errors()
    async def on_error(event, **_):  # type: ignore[no-untyped-def]
        logger.exception("Unhandled error: {}", event.exception)
        return True

    async def on_startup() -> None:
        await set_commands(bot)
        await queue.start()
        me = await bot.get_me()
        logger.info("Bot @{} started in {} mode", me.username, settings.mode)

    async def on_shutdown() -> None:
        logger.info("Shutting down…")
        await queue.stop()
        await video.close()
        await db.close()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    return bot, dp, svc


async def run_polling() -> None:
    bot, dp, _ = await build()
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


def run_webhook() -> None:
    """Start the aiohttp server and register the webhook with Telegram."""
    if not settings.webhook_base_url:
        raise RuntimeError("WEBHOOK_BASE_URL is required in webhook mode")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot, dp, svc = loop.run_until_complete(build())

    webhook_url = settings.webhook_base_url.rstrip("/") + settings.webhook_path

    async def _set_webhook(_: web.Application) -> None:
        await bot.set_webhook(
            webhook_url,
            secret_token=settings.webhook_secret or None,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=False,
        )
        logger.info("Webhook set to {}", webhook_url)

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True, "queue": svc.queue.size})

    async def _keep_alive(app_: web.Application) -> None:
        """Self-ping /health every 10 min so free hosts (Render) never idle out."""
        import httpx

        async def loop_() -> None:
            url = settings.webhook_base_url.rstrip("/") + "/health"
            async with httpx.AsyncClient(timeout=20) as client:
                while True:
                    await asyncio.sleep(600)
                    try:
                        await client.get(url)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("keep-alive ping failed: {}", exc)

        app_["keep_alive"] = asyncio.create_task(loop_())

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    SimpleRequestHandler(
        dispatcher=dp, bot=bot, secret_token=settings.webhook_secret or None
    ).register(app, path=settings.webhook_path)
    setup_application(app, dp, bot=bot)  # wires dp.startup/shutdown to aiohttp
    app.on_startup.append(_set_webhook)
    app.on_startup.append(_keep_alive)

    web.run_app(app, host=settings.host, port=settings.port, loop=loop, print=None)


def main() -> None:
    setup_logging()
    logger.info("Starting AI Video Bot (mode={})", settings.mode)
    if settings.mode == "webhook":
        run_webhook()
    else:
        asyncio.run(run_polling())


if __name__ == "__main__":
    main()
