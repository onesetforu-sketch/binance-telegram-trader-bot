"""
Telegram bot command and message handlers.
Each handler corresponds to a bot command or interaction.
"""

import os
import logging
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from binance.client import Client as BinanceClient

from src.binance_client import (
    get_client,
    get_account_balance,
    get_ticker_price,
    get_24h_stats,
    place_market_order,
    place_limit_order,
    get_open_orders,
    cancel_order,
    get_order_history,
    get_klines,
)

logger = logging.getLogger(__name__)

ALLOWED_USER_ID = int(os.getenv("TELEGRAM_ALLOWED_USER_ID", "0"))


def restricted(func):
    """Decorator to restrict bot access to the allowed user only."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if ALLOWED_USER_ID and user_id != ALLOWED_USER_ID:
            await update.message.reply_text("⛔ Unauthorized. This bot is private.")
            logger.warning(f"Unauthorized access attempt by user ID: {user_id}")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped


def get_binance_client() -> BinanceClient:
    return get_client()


# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────
@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Welcome to Binance Trader Bot + PAXG Gold Engine!*\n\n"
        "I combine standard Binance trading with a 5-factor macro gold analysis engine.\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💎 *PAXG Gold Auto-Trader*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "/goldanalysis — Full 5-factor macro analysis\n"
        "/goldscore — Quick composite score & signal\n"
        "/goldregime — Current market regime (A/B/C/D)\n"
        "/goldrisks — Active risk flags & bearish triggers\n"
        "/paxgposition — PAXG position & unrealized P&L\n"
        "/autotrade `on|off` — Enable/disable auto-trading\n"
        "/dryrun — Simulate a trade (no real order)\n"
        "/tradeconfig — View risk & sizing configuration\n"
        "/tradehistory — Recent auto-trade log\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 *Market Data*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "/price `<SYMBOL>` — Latest price\n"
        "/stats `<SYMBOL>` — 24h market stats\n"
        "/candles `<SYMBOL> [INTERVAL]` — Candlestick data\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💼 *Account & Trading*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "/balance — Account balances\n"
        "/buy `<SYMBOL> <QTY>` — Market buy\n"
        "/sell `<SYMBOL> <QTY>` — Market sell\n"
        "/limitbuy `<SYMBOL> <QTY> <PRICE>` — Limit buy\n"
        "/limitsell `<SYMBOL> <QTY> <PRICE>` — Limit sell\n"
        "/openorders `[SYMBOL]` — Open orders\n"
        "/cancel `<SYMBOL> <ORDER_ID>` — Cancel order\n"
        "/history `<SYMBOL>` — Order history\n\n"

        "_Intervals: 1m, 5m, 15m, 1h, 4h, 1d_"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─────────────────────────────────────────────
# /help
# ─────────────────────────────────────────────
@restricted
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


# ─────────────────────────────────────────────
# /price <SYMBOL>
# ─────────────────────────────────────────────
@restricted
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /price `<SYMBOL>`\nExample: `/price BTCUSDT`", parse_mode="Markdown")
        return
    symbol = context.args[0].upper()
    client = get_binance_client()
    result = get_ticker_price(client, symbol)
    if result["success"]:
        await update.message.reply_text(
            f"💰 *{result['symbol']}*\nCurrent Price: `${float(result['price']):,.4f}`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ Error: {result['error']}")


# ─────────────────────────────────────────────
# /stats <SYMBOL>
# ─────────────────────────────────────────────
@restricted
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /stats `<SYMBOL>`\nExample: `/stats ETHUSDT`", parse_mode="Markdown")
        return
    symbol = context.args[0].upper()
    client = get_binance_client()
    result = get_24h_stats(client, symbol)
    if result["success"]:
        change_pct = float(result["price_change_pct"])
        emoji = "📈" if change_pct >= 0 else "📉"
        text = (
            f"{emoji} *{result['symbol']} — 24h Stats*\n\n"
            f"Last Price:  `${float(result['last_price']):,.4f}`\n"
            f"Change:      `{result['price_change']} ({change_pct:+.2f}%)`\n"
            f"High:        `${float(result['high']):,.4f}`\n"
            f"Low:         `${float(result['low']):,.4f}`\n"
            f"Volume:      `{float(result['volume']):,.2f}`"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Error: {result['error']}")


# ─────────────────────────────────────────────
# /balance
# ─────────────────────────────────────────────
@restricted
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = get_binance_client()
    result = get_account_balance(client)
    if result["success"]:
        if not result["balances"]:
            await update.message.reply_text("💼 Your account has no assets with a balance.")
            return
        lines = ["💼 *Account Balances:*\n"]
        for b in result["balances"]:
            lines.append(f"• *{b['asset']}*: Free `{float(b['free']):.6f}` | Locked `{float(b['locked']):.6f}`")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Error: {result['error']}")


# ─────────────────────────────────────────────
# /buy <SYMBOL> <QTY>
# ─────────────────────────────────────────────
@restricted
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /buy `<SYMBOL> <QTY>`\nExample: `/buy BTCUSDT 0.001`", parse_mode="Markdown")
        return
    symbol = context.args[0].upper()
    try:
        qty = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid quantity. Please enter a number.")
        return

    await update.message.reply_text(f"⏳ Placing market BUY order for `{qty}` {symbol}...", parse_mode="Markdown")
    client = get_binance_client()
    result = place_market_order(client, symbol, "BUY", qty)
    if result["success"]:
        order = result["order"]
        await update.message.reply_text(
            f"✅ *Market BUY Order Placed!*\n\n"
            f"Symbol:   `{order['symbol']}`\n"
            f"Order ID: `{order['orderId']}`\n"
            f"Status:   `{order['status']}`\n"
            f"Qty:      `{order['executedQty']}`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ Order failed: {result['error']}")


# ─────────────────────────────────────────────
# /sell <SYMBOL> <QTY>
# ─────────────────────────────────────────────
@restricted
async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /sell `<SYMBOL> <QTY>`\nExample: `/sell BTCUSDT 0.001`", parse_mode="Markdown")
        return
    symbol = context.args[0].upper()
    try:
        qty = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid quantity. Please enter a number.")
        return

    await update.message.reply_text(f"⏳ Placing market SELL order for `{qty}` {symbol}...", parse_mode="Markdown")
    client = get_binance_client()
    result = place_market_order(client, symbol, "SELL", qty)
    if result["success"]:
        order = result["order"]
        await update.message.reply_text(
            f"✅ *Market SELL Order Placed!*\n\n"
            f"Symbol:   `{order['symbol']}`\n"
            f"Order ID: `{order['orderId']}`\n"
            f"Status:   `{order['status']}`\n"
            f"Qty:      `{order['executedQty']}`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ Order failed: {result['error']}")


# ─────────────────────────────────────────────
# /limitbuy <SYMBOL> <QTY> <PRICE>
# ─────────────────────────────────────────────
@restricted
async def limitbuy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /limitbuy `<SYMBOL> <QTY> <PRICE>`\nExample: `/limitbuy BTCUSDT 0.001 60000`", parse_mode="Markdown")
        return
    symbol = context.args[0].upper()
    try:
        qty = float(context.args[1])
        price = float(context.args[2])
    except ValueError:
        await update.message.reply_text("❌ Invalid quantity or price.")
        return

    client = get_binance_client()
    result = place_limit_order(client, symbol, "BUY", qty, price)
    if result["success"]:
        order = result["order"]
        await update.message.reply_text(
            f"✅ *Limit BUY Order Placed!*\n\n"
            f"Symbol:   `{order['symbol']}`\n"
            f"Order ID: `{order['orderId']}`\n"
            f"Price:    `${price:,.4f}`\n"
            f"Qty:      `{qty}`\n"
            f"Status:   `{order['status']}`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ Order failed: {result['error']}")


# ─────────────────────────────────────────────
# /limitsell <SYMBOL> <QTY> <PRICE>
# ─────────────────────────────────────────────
@restricted
async def limitsell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /limitsell `<SYMBOL> <QTY> <PRICE>`\nExample: `/limitsell BTCUSDT 0.001 70000`", parse_mode="Markdown")
        return
    symbol = context.args[0].upper()
    try:
        qty = float(context.args[1])
        price = float(context.args[2])
    except ValueError:
        await update.message.reply_text("❌ Invalid quantity or price.")
        return

    client = get_binance_client()
    result = place_limit_order(client, symbol, "SELL", qty, price)
    if result["success"]:
        order = result["order"]
        await update.message.reply_text(
            f"✅ *Limit SELL Order Placed!*\n\n"
            f"Symbol:   `{order['symbol']}`\n"
            f"Order ID: `{order['orderId']}`\n"
            f"Price:    `${price:,.4f}`\n"
            f"Qty:      `{qty}`\n"
            f"Status:   `{order['status']}`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ Order failed: {result['error']}")


# ─────────────────────────────────────────────
# /openorders [SYMBOL]
# ─────────────────────────────────────────────
@restricted
async def openorders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = context.args[0].upper() if context.args else None
    client = get_binance_client()
    result = get_open_orders(client, symbol)
    if result["success"]:
        orders = result["orders"]
        if not orders:
            await update.message.reply_text("📂 No open orders found.")
            return
        lines = ["📂 *Open Orders:*\n"]
        for o in orders[:10]:
            lines.append(
                f"• `{o['symbol']}` | ID: `{o['orderId']}` | {o['side']} {o['type']}\n"
                f"  Qty: `{o['origQty']}` @ `${float(o['price']):,.4f}` | Status: `{o['status']}`"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Error: {result['error']}")


# ─────────────────────────────────────────────
# /cancel <SYMBOL> <ORDER_ID>
# ─────────────────────────────────────────────
@restricted
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /cancel `<SYMBOL> <ORDER_ID>`\nExample: `/cancel BTCUSDT 123456789`", parse_mode="Markdown")
        return
    symbol = context.args[0].upper()
    try:
        order_id = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid order ID.")
        return

    client = get_binance_client()
    result = cancel_order(client, symbol, order_id)
    if result["success"]:
        await update.message.reply_text(f"✅ Order `{order_id}` for `{symbol}` has been cancelled.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Error: {result['error']}")


# ─────────────────────────────────────────────
# /history <SYMBOL>
# ─────────────────────────────────────────────
@restricted
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /history `<SYMBOL>`\nExample: `/history BTCUSDT`", parse_mode="Markdown")
        return
    symbol = context.args[0].upper()
    client = get_binance_client()
    result = get_order_history(client, symbol, limit=10)
    if result["success"]:
        orders = result["orders"]
        if not orders:
            await update.message.reply_text(f"🕓 No order history found for `{symbol}`.", parse_mode="Markdown")
            return
        lines = [f"🕓 *Recent Orders for {symbol}:*\n"]
        for o in orders[-10:]:
            lines.append(
                f"• ID: `{o['orderId']}` | {o['side']} {o['type']}\n"
                f"  Qty: `{o['executedQty']}` @ `${float(o['price']):,.4f}` | `{o['status']}`"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Error: {result['error']}")


# ─────────────────────────────────────────────
# /candles <SYMBOL> [INTERVAL]
# ─────────────────────────────────────────────
@restricted
async def candles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /candles `<SYMBOL> [INTERVAL]`\nExample: `/candles BTCUSDT 1h`", parse_mode="Markdown")
        return
    symbol = context.args[0].upper()
    interval = context.args[1] if len(context.args) > 1 else "1h"
    valid_intervals = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"]
    if interval not in valid_intervals:
        await update.message.reply_text(f"❌ Invalid interval. Choose from: {', '.join(valid_intervals)}")
        return

    client = get_binance_client()
    result = get_klines(client, symbol, interval, limit=5)
    if result["success"]:
        lines = [f"🕯 *{symbol} — Last 5 Candles ({interval}):*\n"]
        for k in result["klines"]:
            lines.append(
                f"O: `{k['open']}` H: `{k['high']}` L: `{k['low']}` C: `{k['close']}` V: `{k['volume']}`"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Error: {result['error']}")
