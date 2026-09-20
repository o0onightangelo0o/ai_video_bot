"""
Inline keyboards used by the generation wizard.

All callback data is prefixed (``asp:``, ``dur:``, ``sty:``, ``go:``, ``lang:``)
so a single callback router can dispatch them.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .i18n import t

ASPECT_RATIOS = ("16:9", "9:16", "1:1")
DURATIONS = (5, 8, 10)
STYLES = ("none", "cinematic", "anime", "3d", "realistic", "watercolor")


def _cancel_row(lang: str) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="go:cancel")]


def aspect_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Aspect-ratio picker."""
    kb = InlineKeyboardBuilder()
    for ar in ASPECT_RATIOS:
        icon = {"16:9": "🖥", "9:16": "📱", "1:1": "⬛"}[ar]
        kb.button(text=f"{icon} {ar}", callback_data=f"asp:{ar}")
    kb.adjust(3)
    kb.row(*_cancel_row(lang))
    return kb.as_markup()


def duration_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Duration picker (seconds)."""
    kb = InlineKeyboardBuilder()
    for d in DURATIONS:
        kb.button(text=f"⏱ {d}s", callback_data=f"dur:{d}")
    kb.adjust(3)
    kb.row(*_cancel_row(lang))
    return kb.as_markup()


def style_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Artistic style picker."""
    kb = InlineKeyboardBuilder()
    for s in STYLES:
        kb.button(text=t(f"style_{s}", lang), callback_data=f"sty:{s}")
    kb.adjust(2)
    kb.row(*_cancel_row(lang))
    return kb.as_markup()


def confirm_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Final confirm / cancel."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("btn_confirm", lang), callback_data="go:confirm"),
                InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="go:cancel"),
            ]
        ]
    )


def cancel_job_keyboard(lang: str, job_id: int) -> InlineKeyboardMarkup:
    """Single button to cancel a running job."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("btn_cancel", lang), callback_data=f"job:cancel:{job_id}")]
        ]
    )


def language_keyboard() -> InlineKeyboardMarkup:
    """Language switcher."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
                InlineKeyboardButton(text="🇸🇦 العربية", callback_data="lang:ar"),
            ]
        ]
    )


def admin_pager(kind: str, page: int, has_next: bool, extra: str = "") -> InlineKeyboardMarkup:
    """◀️ / ▶️ pager for admin lists. callback: adm:<kind>:<page>[:extra]"""
    suffix = f":{extra}" if extra else ""
    row: list[InlineKeyboardButton] = []
    if page > 0:
        row.append(InlineKeyboardButton(text="◀️", callback_data=f"adm:{kind}:{page - 1}{suffix}"))
    row.append(InlineKeyboardButton(text=f"· {page + 1} ·", callback_data="adm:noop"))
    if has_next:
        row.append(InlineKeyboardButton(text="▶️", callback_data=f"adm:{kind}:{page + 1}{suffix}"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def admin_menu() -> InlineKeyboardMarkup:
    """Shortcut buttons under /stats."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👥 Users", callback_data="adm:users:0"),
                InlineKeyboardButton(text="📝 Prompts", callback_data="adm:prompts:0"),
            ],
            [InlineKeyboardButton(text="📥 Export CSV", callback_data="adm:export")],
        ]
    )
