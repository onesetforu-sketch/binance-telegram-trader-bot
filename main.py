"""
Binance Telegram Trader Bot — Entry Point
Run this file to start the bot.
"""

import os
import logging
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CommandHandler

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

# Load environment variables
load_dotenv()

# Logging configuration
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set. Please configure your .env file.")

    logger.info("Starting Binance Telegram Trader Bot...")

    app = ApplicationBuilder().token(token).build()

    # Register command handlers
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

    logger.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
