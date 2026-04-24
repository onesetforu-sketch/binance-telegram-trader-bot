"""
Shared authentication and reply helpers.

Provides:
  - ``get_allowed_user_id()``: safely parse ``TELEGRAM_ALLOWED_USER_ID`` (0 means
    "not configured"; the bot is effectively open when left at 0).
  - ``restricted``: decorator that gates bot handlers to the allowed user only.
  - ``reply_safe`` / ``edit_safe``: send Markdown replies that gracefully fall
    back to plain text when Telegram's parser rejects the content (e.g. raw
    exception strings that contain unescaped ``_`` or ``*``).
"""

from __future__ import annotations

import logging
import os
from functools import wraps

from telegram import Message, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


def _safe_int_env(name: str, default: int = 0) -> int:
    raw = os.getenv(name, "")
    if not raw:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning(
            "Invalid integer for %s=%r; falling back to %d", name, raw, default
        )
        return default


def get_allowed_user_id() -> int:
    """Return the configured allowed Telegram user ID (0 if unset)."""
    return _safe_int_env("TELEGRAM_ALLOWED_USER_ID", 0)


def restricted(func):
    """Restrict a handler to ``TELEGRAM_ALLOWED_USER_ID`` only.

    If the env var is unset (0), the handler runs for anyone — the startup
    banner in ``main.py`` logs a loud warning so this is not silent.
    """

    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        allowed_id = get_allowed_user_id()
        user = update.effective_user
        user_id = user.id if user else None

        if allowed_id and user_id != allowed_id:
            logger.warning(
                "Unauthorized access attempt: user_id=%s username=%s",
                user_id,
                getattr(user, "username", None),
            )
            if update.message is not None:
                await update.message.reply_text(
                    "⛔ Unauthorized. This bot is private."
                )
            return None
        return await func(update, context, *args, **kwargs)

    return wrapped


async def reply_safe(update: Update, text: str, *, parse_mode: str | None = "Markdown") -> Message | None:
    """Reply to an update, falling back to plain text on Markdown parse errors.

    Telegram's Markdown V1 is unforgiving — a stray ``_`` in a Binance error
    message will raise ``BadRequest``. When that happens we log and resend the
    message as plain text so the user still sees the content.
    """
    if update.message is None:
        return None
    try:
        return await update.message.reply_text(text, parse_mode=parse_mode)
    except BadRequest as exc:
        logger.warning("Markdown reply failed (%s); retrying as plain text", exc)
        return await update.message.reply_text(text)


async def edit_safe(message: Message, text: str, *, parse_mode: str | None = "Markdown") -> Message | None:
    """Edit a message, falling back to plain text on Markdown parse errors."""
    try:
        return await message.edit_text(text, parse_mode=parse_mode)
    except BadRequest as exc:
        logger.warning("Markdown edit failed (%s); retrying as plain text", exc)
        try:
            return await message.edit_text(text)
        except BadRequest as exc2:
            logger.error("Plain-text edit also failed: %s", exc2)
            return None
