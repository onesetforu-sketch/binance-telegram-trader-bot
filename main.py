"""
Binance Telegram Trader Bot — Entry Point
==========================================
Includes:
  - Standard Binance trading commands
  - PAXG Gold Auto-Trader with 5-factor macro engine
  - Background scheduler for periodic analysis and alerts
"""

import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Shared auth helpers
from src.auth import get_allowed_user_id

# Standard trading handlers
from src.handlers import (
    start,
    help_command,
    price,
    stats,
    balance,
    buy,
    sell,
    limitbuy,
    limitsell,
    openorders,
    cancel,
    history,
    candles,
)

# PAXG Gold Auto-Trader handlers
from src.paxg_handlers import (
    gold_analysis,
    gold_score,
    gold_regime,
    paxg_position,
    autotrade,
    trade_config,
    dry_run,
    gold_risks,
    trade_history,
)

# Background scheduler
from src.scheduler import ANALYSIS_INTERVAL_MINUTES, start_scheduler

# Load environment variables
load_dotenv()

# Logging
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
)
logger = logging.getLogger(__name__)


def _startup_banner() -> None:
    """Log a clear startup banner describing the bot's runtime configuration."""
    is_testnet = os.getenv("USE_TESTNET", "True").strip().lower() == "true"
    mode = "TESTNET (paper trading)" if is_testnet else "LIVE MAINNET (real funds)"
    allowed_id = get_allowed_user_id()

    logger.info("=" * 60)
    logger.info("Binance Telegram Trader Bot — PAXG Gold Engine")
    logger.info("-" * 60)
    logger.info("Binance mode       : %s", mode)
    logger.info("Analysis interval  : every %d minute(s)", ANALYSIS_INTERVAL_MINUTES)

    if allowed_id:
        logger.info("Allowed user ID    : %d (private mode)", allowed_id)
    else:
        logger.warning(
            "Allowed user ID    : NOT SET — TELEGRAM_ALLOWED_USER_ID is empty, "
            "so anyone who messages this bot can trigger commands. "
            "Set TELEGRAM_ALLOWED_USER_ID in .env to lock down access."
        )

    if not is_testnet:
        logger.warning(
            "LIVE MAINNET mode: real funds are at risk. "
            "Verify /tradeconfig risk settings before enabling /autotrade on."
        )
    logger.info("=" * 60)


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch-all error handler for Telegram handlers.

    ``python-telegram-bot`` swallows uncaught handler exceptions by default —
    this hook makes them visible in logs and sends a short apology to the
    user instead of leaving the message unanswered.
    """
    logger.exception("Unhandled error while processing update", exc_info=context.error)

    # Best-effort user-facing notice.
    if isinstance(update, Update) and update.effective_message is not None:
        try:
            await update.effective_message.reply_text(
                "⚠️ Something went wrong handling that command. "
                "Please try again shortly — details have been logged."
            )
        except Exception:
            logger.exception("Failed to notify user of error")


async def post_init(application):
    """Called after the bot is initialized — start the background scheduler."""
    start_scheduler(application.bot)
    logger.info("Background macro analysis scheduler started.")


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set. Please configure your .env file.")

    _startup_banner()
    logger.info("Starting Binance Telegram Trader Bot with PAXG Gold Engine...")

    app = (
        ApplicationBuilder()
        .token(token)
        .post_init(post_init)
        .build()
    )

    # ── Standard Binance Commands ──────────────────────────────────────────
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("sell", sell))
    app.add_handler(CommandHandler("limitbuy", limitbuy))
    app.add_handler(CommandHandler("limitsell", limitsell))
    app.add_handler(CommandHandler("openorders", openorders))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("candles", candles))

    # ── PAXG Gold Auto-Trader Commands ─────────────────────────────────────
    app.add_handler(CommandHandler("goldanalysis", gold_analysis))
    app.add_handler(CommandHandler("goldscore", gold_score))
    app.add_handler(CommandHandler("goldregime", gold_regime))
    app.add_handler(CommandHandler("paxgposition", paxg_position))
    app.add_handler(CommandHandler("autotrade", autotrade))
    app.add_handler(CommandHandler("tradeconfig", trade_config))
    app.add_handler(CommandHandler("dryrun", dry_run))
    app.add_handler(CommandHandler("goldrisks", gold_risks))
    app.add_handler(CommandHandler("tradehistory", trade_history))

    # Global error handler — logs any uncaught exception from a handler.
    app.add_error_handler(_on_error)

    logger.info("All handlers registered. Bot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
