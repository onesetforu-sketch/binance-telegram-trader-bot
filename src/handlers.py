"""
Telegram bot command and message handlers.
Each handler corresponds to a bot command or interaction.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes
from binance.client import Client as BinanceClient

from src.auth import reply_safe, restricted
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


def get_binance_client() -> BinanceClient:
    return get_client()


# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────
@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Welcome to Binance Trader Bot + PAXG PA Strategy!*\n\n"
        "Standard Binance trading + a rule-based price-action strategy for "
        "PAXG/USDT (VWAP + key levels + volume). Alerts only — no auto-execute.\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📈 *PAXG Price-Action Strategy*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "/palevels — Yesterday H/L, Asia H/L, round levels, VWAP\n"
        "/pasignal — Current bias (LONG / SHORT / NO_SETUP) + checklist\n"
        "/pastrategy `on|off|status` — Toggle alert broadcasting\n\n"

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
    await reply_safe(update, text)


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
        await reply_safe(update, "Usage: /price `<SYMBOL>`\nExample: `/price BTCUSDT`")
        return
    symbol = context.args[0].upper()
    client = get_binance_client()
    result = get_ticker_price(client, symbol)
    if result["success"]:
        await reply_safe(
            update,
            f"💰 *{result['symbol']}*\nCurrent Price: `${float(result['price']):,.4f}`",
        )
    else:
        await reply_safe(update, f"❌ Error: {result['error']}", parse_mode=None)


# ─────────────────────────────────────────────
# /stats <SYMBOL>
# ─────────────────────────────────────────────
@restricted
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply_safe(update, "Usage: /stats `<SYMBOL>`\nExample: `/stats ETHUSDT`")
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
        await reply_safe(update, text)
    else:
        await reply_safe(update, f"❌ Error: {result['error']}", parse_mode=None)


# ─────────────────────────────────────────────
# /balance
# ─────────────────────────────────────────────
@restricted
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = get_binance_client()
    result = get_account_balance(client)
    if result["success"]:
        if not result["balances"]:
            await reply_safe(update, "💼 Your account has no assets with a balance.", parse_mode=None)
            return
        lines = ["💼 *Account Balances:*\n"]
        for b in result["balances"]:
            lines.append(f"• *{b['asset']}*: Free `{float(b['free']):.6f}` | Locked `{float(b['locked']):.6f}`")
        await reply_safe(update, "\n".join(lines))
    else:
        await reply_safe(update, f"❌ Error: {result['error']}", parse_mode=None)


# ─────────────────────────────────────────────
# /buy <SYMBOL> <QTY>
# ─────────────────────────────────────────────
@restricted
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await reply_safe(update, "Usage: /buy `<SYMBOL> <QTY>`\nExample: `/buy BTCUSDT 0.001`")
        return
    symbol = context.args[0].upper()
    try:
        qty = float(context.args[1])
    except ValueError:
        await reply_safe(update, "❌ Invalid quantity. Please enter a number.", parse_mode=None)
        return
    if qty <= 0:
        await reply_safe(update, "❌ Quantity must be greater than zero.", parse_mode=None)
        return

    await reply_safe(update, f"⏳ Placing market BUY order for `{qty}` {symbol}...")
    client = get_binance_client()
    result = place_market_order(client, symbol, "BUY", qty)
    if result["success"]:
        order = result["order"]
        await reply_safe(
            update,
            f"✅ *Market BUY Order Placed!*\n\n"
            f"Symbol:   `{order['symbol']}`\n"
            f"Order ID: `{order['orderId']}`\n"
            f"Status:   `{order['status']}`\n"
            f"Qty:      `{order['executedQty']}`",
        )
    else:
        await reply_safe(update, f"❌ Order failed: {result['error']}", parse_mode=None)


# ─────────────────────────────────────────────
# /sell <SYMBOL> <QTY>
# ─────────────────────────────────────────────
@restricted
async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await reply_safe(update, "Usage: /sell `<SYMBOL> <QTY>`\nExample: `/sell BTCUSDT 0.001`")
        return
    symbol = context.args[0].upper()
    try:
        qty = float(context.args[1])
    except ValueError:
        await reply_safe(update, "❌ Invalid quantity. Please enter a number.", parse_mode=None)
        return
    if qty <= 0:
        await reply_safe(update, "❌ Quantity must be greater than zero.", parse_mode=None)
        return

    await reply_safe(update, f"⏳ Placing market SELL order for `{qty}` {symbol}...")
    client = get_binance_client()
    result = place_market_order(client, symbol, "SELL", qty)
    if result["success"]:
        order = result["order"]
        await reply_safe(
            update,
            f"✅ *Market SELL Order Placed!*\n\n"
            f"Symbol:   `{order['symbol']}`\n"
            f"Order ID: `{order['orderId']}`\n"
            f"Status:   `{order['status']}`\n"
            f"Qty:      `{order['executedQty']}`",
        )
    else:
        await reply_safe(update, f"❌ Order failed: {result['error']}", parse_mode=None)


# ─────────────────────────────────────────────
# /limitbuy <SYMBOL> <QTY> <PRICE>
# ─────────────────────────────────────────────
@restricted
async def limitbuy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await reply_safe(update, "Usage: /limitbuy `<SYMBOL> <QTY> <PRICE>`\nExample: `/limitbuy BTCUSDT 0.001 60000`")
        return
    symbol = context.args[0].upper()
    try:
        qty = float(context.args[1])
        price = float(context.args[2])
    except ValueError:
        await reply_safe(update, "❌ Invalid quantity or price.", parse_mode=None)
        return
    if qty <= 0 or price <= 0:
        await reply_safe(update, "❌ Quantity and price must both be greater than zero.", parse_mode=None)
        return

    client = get_binance_client()
    result = place_limit_order(client, symbol, "BUY", qty, price)
    if result["success"]:
        order = result["order"]
        await reply_safe(
            update,
            f"✅ *Limit BUY Order Placed!*\n\n"
            f"Symbol:   `{order['symbol']}`\n"
            f"Order ID: `{order['orderId']}`\n"
            f"Price:    `${price:,.4f}`\n"
            f"Qty:      `{qty}`\n"
            f"Status:   `{order['status']}`",
        )
    else:
        await reply_safe(update, f"❌ Order failed: {result['error']}", parse_mode=None)


# ─────────────────────────────────────────────
# /limitsell <SYMBOL> <QTY> <PRICE>
# ─────────────────────────────────────────────
@restricted
async def limitsell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await reply_safe(update, "Usage: /limitsell `<SYMBOL> <QTY> <PRICE>`\nExample: `/limitsell BTCUSDT 0.001 70000`")
        return
    symbol = context.args[0].upper()
    try:
        qty = float(context.args[1])
        price = float(context.args[2])
    except ValueError:
        await reply_safe(update, "❌ Invalid quantity or price.", parse_mode=None)
        return
    if qty <= 0 or price <= 0:
        await reply_safe(update, "❌ Quantity and price must both be greater than zero.", parse_mode=None)
        return

    client = get_binance_client()
    result = place_limit_order(client, symbol, "SELL", qty, price)
    if result["success"]:
        order = result["order"]
        await reply_safe(
            update,
            f"✅ *Limit SELL Order Placed!*\n\n"
            f"Symbol:   `{order['symbol']}`\n"
            f"Order ID: `{order['orderId']}`\n"
            f"Price:    `${price:,.4f}`\n"
            f"Qty:      `{qty}`\n"
            f"Status:   `{order['status']}`",
        )
    else:
        await reply_safe(update, f"❌ Order failed: {result['error']}", parse_mode=None)


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
            await reply_safe(update, "📂 No open orders found.", parse_mode=None)
            return
        lines = ["📂 *Open Orders:*\n"]
        for o in orders[:10]:
            lines.append(
                f"• `{o['symbol']}` | ID: `{o['orderId']}` | {o['side']} {o['type']}\n"
                f"  Qty: `{o['origQty']}` @ `${float(o['price']):,.4f}` | Status: `{o['status']}`"
            )
        await reply_safe(update, "\n".join(lines))
    else:
        await reply_safe(update, f"❌ Error: {result['error']}", parse_mode=None)


# ─────────────────────────────────────────────
# /cancel <SYMBOL> <ORDER_ID>
# ─────────────────────────────────────────────
@restricted
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await reply_safe(update, "Usage: /cancel `<SYMBOL> <ORDER_ID>`\nExample: `/cancel BTCUSDT 123456789`")
        return
    symbol = context.args[0].upper()
    try:
        order_id = int(context.args[1])
    except ValueError:
        await reply_safe(update, "❌ Invalid order ID. Must be an integer.", parse_mode=None)
        return

    client = get_binance_client()
    result = cancel_order(client, symbol, order_id)
    if result["success"]:
        await reply_safe(update, f"✅ Order `{order_id}` for `{symbol}` has been cancelled.")
    else:
        await reply_safe(update, f"❌ Error: {result['error']}", parse_mode=None)


# ─────────────────────────────────────────────
# /history <SYMBOL>
# ─────────────────────────────────────────────
@restricted
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply_safe(update, "Usage: /history `<SYMBOL>`\nExample: `/history BTCUSDT`")
        return
    symbol = context.args[0].upper()
    client = get_binance_client()
    result = get_order_history(client, symbol, limit=10)
    if result["success"]:
        orders = result["orders"]
        if not orders:
            await reply_safe(update, f"🕓 No order history found for `{symbol}`.")
            return
        lines = [f"🕓 *Recent Orders for {symbol}:*\n"]
        for o in orders[-10:]:
            price_val = float(o.get("price") or 0)
            price_str = f"${price_val:,.4f}" if price_val > 0 else "market"
            lines.append(
                f"• ID: `{o['orderId']}` | {o['side']} {o['type']}\n"
                f"  Qty: `{o['executedQty']}` @ `{price_str}` | `{o['status']}`"
            )
        await reply_safe(update, "\n".join(lines))
    else:
        await reply_safe(update, f"❌ Error: {result['error']}", parse_mode=None)


# ─────────────────────────────────────────────
# /candles <SYMBOL> [INTERVAL]
# ─────────────────────────────────────────────
@restricted
async def candles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply_safe(update, "Usage: /candles `<SYMBOL> [INTERVAL]`\nExample: `/candles BTCUSDT 1h`")
        return
    symbol = context.args[0].upper()
    interval = context.args[1] if len(context.args) > 1 else "1h"
    valid_intervals = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"]
    if interval not in valid_intervals:
        await reply_safe(
            update,
            f"❌ Invalid interval. Choose from: {', '.join(valid_intervals)}",
            parse_mode=None,
        )
        return

    client = get_binance_client()
    result = get_klines(client, symbol, interval, limit=5)
    if result["success"]:
        lines = [f"🕯 *{symbol} — Last 5 Candles ({interval}):*\n"]
        for k in result["klines"]:
            lines.append(
                f"O: `{k['open']}` H: `{k['high']}` L: `{k['low']}` C: `{k['close']}` V: `{k['volume']}`"
            )
        await reply_safe(update, "\n".join(lines))
    else:
        await reply_safe(update, f"❌ Error: {result['error']}", parse_mode=None)
