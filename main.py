"""
Binance Telegram Trader Bot — Entry Point
==========================================
Includes:
  - Standard Binance trading commands
  - PAXG Gold Auto-Trader with 5-factor macro engine
  - Background scheduler for periodic analysis and alerts
"""

import os
import logging
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CommandHandler

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
from src.scheduler import start_scheduler

# Load environment variables
load_dotenv()

# Logging
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(application):
    """Called after the bot is initialized — start the background scheduler."""
    start_scheduler(application.bot)
    logger.info("Background macro analysis scheduler started.")


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set. Please configure your .env file.")

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

    logger.info("All handlers registered. Bot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
