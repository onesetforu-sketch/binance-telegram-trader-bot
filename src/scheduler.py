"""
Background Scheduler
=====================
Runs the price-action (PA) strategy on a fixed interval and sends a Telegram
alert when a fresh LONG / SHORT setup appears.

  - Interval is configured via ``ANALYSIS_INTERVAL_MINUTES`` (default: 15).
  - Alerts only fire when ``/pastrategy on`` has been set by the user.
  - Only a NEW bias or NEW broken level triggers an alert (no spam).
  - This iteration is alert-only: no orders are placed automatically.
"""

import logging
import os
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

from src.auth import get_allowed_user_id
from src.pa_handlers import format_signal_message
from src.pa_strategy import (
    compute_signal,
    is_new_signal,
    load_pa_state,
    save_pa_state,
)

logger = logging.getLogger(__name__)


def _safe_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    if not raw:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning(
            "Invalid integer for %s=%r; using default %d", name, raw, default
        )
        return default


# Default to 15 minutes to match the signal timeframe.
ANALYSIS_INTERVAL_MINUTES = max(1, _safe_int_env("ANALYSIS_INTERVAL_MINUTES", 15))


async def run_analysis_cycle(bot: Bot):
    """Evaluate the PA signal and emit a Telegram alert when appropriate."""
    allowed_user_id = get_allowed_user_id()
    if not allowed_user_id:
        logger.warning("TELEGRAM_ALLOWED_USER_ID not set — skipping PA alerts")
        return

    try:
        logger.info("Running scheduled PA analysis cycle...")
        signal = compute_signal()
        state = load_pa_state()

        bias = signal.get("bias", "NO_SETUP")
        logger.info(
            "PA signal: bias=%s session=%s reason=%s",
            bias,
            signal.get("session"),
            signal.get("reason", "")[:120],
        )

        # Update "signals_seen" for informational /pastrategy status.
        state["signals_seen"] = int(state.get("signals_seen", 0)) + (
            1 if bias != "NO_SETUP" else 0
        )

        should_alert = state.get("alerts_enabled") and is_new_signal(signal, state)

        if should_alert:
            msg = format_signal_message(signal)
            try:
                await bot.send_message(
                    chat_id=allowed_user_id,
                    text=msg,
                    parse_mode="Markdown",
                )
            except Exception as send_exc:
                logger.warning(
                    "Markdown alert failed (%s); retrying as plain text", send_exc
                )
                await bot.send_message(chat_id=allowed_user_id, text=msg)
            logger.info("PA alert sent: bias=%s level=%s", bias, signal.get("broken_level"))
            state["last_alert_time"] = datetime.now(timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC"
            )

        # Always update last-seen bias / level so we don't re-alert on the same setup.
        state["last_signal_bias"] = bias
        state["last_signal_broken_level"] = signal.get("broken_level")
        # Successful cycle — clear any previously recorded error so we alert
        # the user again if a new failure appears later.
        if state.get("last_error_message"):
            state["last_error_message"] = None
        save_pa_state(state)

    except Exception as e:
        logger.exception("PA analysis cycle failed")
        # Dedupe error alerts: only notify the user when the error message
        # changes, so a sustained Binance outage doesn't spam every cycle.
        err_msg = f"{type(e).__name__}: {e}"
        try:
            state = load_pa_state()
        except Exception:
            state = None
        if state is not None and state.get("last_error_message") != err_msg:
            try:
                await bot.send_message(
                    chat_id=allowed_user_id,
                    text=f"⚠️ PA analysis cycle failed: {err_msg}",
                )
            except Exception:
                logger.exception("Failed to deliver PA-failure alert")
            state["last_error_message"] = err_msg
            state["last_error_time"] = datetime.now(timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC"
            )
            try:
                save_pa_state(state)
            except Exception:
                logger.exception("Failed to persist PA error state")


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Start the APScheduler with the periodic PA analysis job."""
    scheduler = AsyncIOScheduler(timezone="UTC")

    scheduler.add_job(
        run_analysis_cycle,
        trigger="interval",
        minutes=ANALYSIS_INTERVAL_MINUTES,
        args=[bot],
        id="pa_analysis",
        next_run_time=datetime.now(timezone.utc),  # Run immediately on startup
    )

    scheduler.start()
    logger.info(
        f"PA strategy scheduler started (interval: {ANALYSIS_INTERVAL_MINUTES} min)"
    )
    return scheduler
