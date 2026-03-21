"""
PAXG Gold Auto-Trader — Telegram Command Handlers
===================================================
New commands added to the bot:

  /goldanalysis  — Full 5-factor macro analysis + regime + signal
  /goldscore     — Quick composite score and signal
  /goldregime    — Current regime classification
  /paxgposition  — Current PAXG position and unrealized P&L
  /autotrade     — Enable/disable auto-trading (on/off/status)
  /tradeconfig   — View current auto-trade configuration
  /dryrun        — Run a simulated trade based on current macro score
  /goldrisks     — Show current risk flags and bearish triggers
  /tradehistory  — Show recent auto-trade history
"""

import os
import logging
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes

from src.binance_client import get_client
from src.macro_data import get_full_macro_snapshot
from src.regime_engine import compute_gold_score
from src.paxg_trader import (
    execute_auto_trade,
    get_portfolio_summary,
    get_state,
    set_auto_trade,
    TRADE_BUDGET_USDT,
    STOP_LOSS_PCT,
    MAX_DRAWDOWN_PCT,
    COOLDOWN_HOURS,
    MIN_SCORE_DELTA,
    SYMBOL,
)

logger = logging.getLogger(__name__)
ALLOWED_USER_ID = int(os.getenv("TELEGRAM_ALLOWED_USER_ID", "0"))


def restricted(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if ALLOWED_USER_ID and user_id != ALLOWED_USER_ID:
            await update.message.reply_text("⛔ Unauthorized.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped


def _score_bar(score: float) -> str:
    """Visual score bar from -100 to +100."""
    filled = int((score + 100) / 200 * 20)
    filled = max(0, min(20, filled))
    bar = "█" * filled + "░" * (20 - filled)
    return f"[{bar}] {score:+.1f}"


# ─────────────────────────────────────────────────────────────────────────────
# /goldanalysis — Full 5-factor report
# ─────────────────────────────────────────────────────────────────────────────

@restricted
async def gold_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 Running full 5-factor macro analysis... (may take 10–15s)")
    try:
        client = get_client()
        snapshot = get_full_macro_snapshot(client)
        result = compute_gold_score(snapshot)

        factors = result["factors"]
        ry = factors["real_yield"]
        usd = factors["usd"]
        liq = factors["liquidity"]
        rp = factors["risk_premium"]
        pos = factors["positioning"]

        def fmt_factor(name, f):
            bar = "▓" * int(abs(f["score"]) * 5)
            direction = "+" if f["score"] >= 0 else "-"
            return f"`{name:<14}` {direction}{bar:<5} score {f['score']:+.2f} (w:{f['weight']})\n  _{f['note']}_"

        text = (
            f"📊 *PAXG Gold Macro Analysis*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏛 *Regime:* `{result['regime_code']}`\n"
            f"_{result['regime_desc']}_\n\n"
            f"*Composite Score:*\n`{_score_bar(result['composite_score'])}`\n\n"
            f"*Signal:* {result['signal_emoji']} `{result['signal']}`\n"
            f"_{result['action']}_\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"*Factor Breakdown:*\n\n"
            f"{fmt_factor('1.RealYield', ry)}\n\n"
            f"{fmt_factor('2.USD/DXY', usd)}\n\n"
            f"{fmt_factor('3.Liquidity', liq)}\n\n"
            f"{fmt_factor('4.RiskPrem', rp)}\n\n"
            f"{fmt_factor('5.Momentum', pos)}\n\n"
        )

        if result["risk_flags"]:
            text += "━━━━━━━━━━━━━━━━━━━━━━━━\n*Risk Flags:*\n"
            for flag in result["risk_flags"]:
                text += f"{flag}\n"

        text += f"\n_Updated: {result['timestamp']}_"
        await msg.edit_text(text, parse_mode="Markdown")

    except Exception as e:
        await msg.edit_text(f"❌ Analysis failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# /goldscore — Quick score summary
# ─────────────────────────────────────────────────────────────────────────────

@restricted
async def gold_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⚡ Fetching quick gold score...")
    try:
        client = get_client()
        snapshot = get_full_macro_snapshot(client)
        result = compute_gold_score(snapshot)

        text = (
            f"{result['signal_emoji']} *Gold Score: {result['composite_score']:+.1f}/100*\n\n"
            f"Signal: `{result['signal']}`\n"
            f"Regime: `{result['regime_code']}`\n"
            f"Action: _{result['action']}_\n\n"
            f"`{_score_bar(result['composite_score'])}`"
        )
        if result["risk_flags"]:
            text += "\n\n*Risks:*\n" + "\n".join(result["risk_flags"])

        await msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# /goldregime — Regime classification
# ─────────────────────────────────────────────────────────────────────────────

@restricted
async def gold_regime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🏛 Detecting market regime...")
    try:
        client = get_client()
        snapshot = get_full_macro_snapshot(client)
        result = compute_gold_score(snapshot)

        regime_emojis = {
            "A": "🟢", "A+": "🟢🟢", "B": "🔴", "B+": "🔴🔴",
            "C": "🟡", "D": "⚪", "MIXED_BULL": "🔵", "MIXED_BEAR": "🟠",
        }
        emoji = regime_emojis.get(result["regime_code"], "⚪")

        text = (
            f"{emoji} *Regime: {result['regime_code']}*\n\n"
            f"_{result['regime_desc']}_\n\n"
            f"*What this means for PAXG:*\n"
        )

        regime_guidance = {
            "A": "Disinflation + falling real yields. *Best environment for gold.* Trend up strongly expected.",
            "A+": "Strong macro tailwinds across all factors. *Maximum bullish setup for gold.*",
            "B": "Tightening regime. Nominal yields jumping, USD strong. *Gold can stall or chop.*",
            "B+": "Aggressive tightening signals. *Strong headwind — reduce exposure.*",
            "C": "Crisis / fear shock. *Safe-haven bid active — gold spikes but with whipsaw risk.*",
            "D": "Risk-on dominates. Equities/crypto outperform. *Gold underperforms or ranges.*",
            "MIXED_BULL": "Conflicting signals with slight bullish bias. *Trade smaller, watch closely.*",
            "MIXED_BEAR": "Conflicting signals with slight bearish bias. *Tighten stops, reduce size.*",
        }
        text += regime_guidance.get(result["regime_code"], "Mixed signals — proceed with caution.")
        text += f"\n\nScore: `{result['composite_score']:+.1f}` | Signal: `{result['signal']}`"

        await msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# /paxgposition — Current position and P&L
# ─────────────────────────────────────────────────────────────────────────────

@restricted
async def paxg_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        summary = get_portfolio_summary()
        pnl_emoji = "📈" if summary["unrealized_pnl_usdt"] >= 0 else "📉"
        auto_status = "✅ ON" if summary["auto_trade_enabled"] else "❌ OFF"

        if summary["position_qty"] == 0:
            pos_text = "_No open PAXG position_"
        else:
            pos_text = (
                f"Qty:        `{summary['position_qty']} PAXG`\n"
                f"Avg Entry:  `${summary['avg_entry_price']:,.2f}`\n"
                f"Current:    `${summary['current_price']:,.2f}`\n"
                f"Value:      `${summary['current_value_usdt']:,.2f} USDT`\n"
                f"Unreal P&L: {pnl_emoji} `${summary['unrealized_pnl_usdt']:+,.4f} ({summary['unrealized_pct']:+.2f}%)`"
            )

        text = (
            f"💎 *PAXG Position Summary*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{pos_text}\n\n"
            f"Realized P&L:  `${summary['realized_pnl_usdt']:+,.4f} USDT`\n"
            f"Trade Count:   `{summary['trade_count']}`\n"
            f"Last Signal:   `{summary['last_signal']}`\n"
            f"Last Score:    `{summary['last_score']:+.1f}`\n"
            f"Last Trade:    `{summary['last_trade_time']}`\n\n"
            f"Auto-Trade:    {auto_status}"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# /autotrade on|off|status
# ─────────────────────────────────────────────────────────────────────────────

@restricted
async def autotrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        state = get_state()
        status = "✅ ENABLED" if state.get("auto_trade_enabled") else "❌ DISABLED"
        await update.message.reply_text(
            f"🤖 *Auto-Trade Status:* {status}\n\n"
            f"Use `/autotrade on` or `/autotrade off` to toggle.\n"
            f"Use `/dryrun` to simulate a trade without real orders.",
            parse_mode="Markdown"
        )
        return

    cmd = context.args[0].lower()
    if cmd == "on":
        set_auto_trade(True)
        await update.message.reply_text(
            "✅ *Auto-trading ENABLED.*\n\n"
            "The bot will now automatically trade PAXG/USDT based on the macro regime score.\n"
            "⚠️ Ensure your Binance API key has Spot Trading permissions.\n"
            "Use `/tradeconfig` to review risk settings.",
            parse_mode="Markdown"
        )
    elif cmd == "off":
        set_auto_trade(False)
        await update.message.reply_text("❌ *Auto-trading DISABLED.* No new orders will be placed.", parse_mode="Markdown")
    else:
        await update.message.reply_text("Usage: `/autotrade on` | `/autotrade off` | `/autotrade status`", parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────────────────────
# /tradeconfig — Show risk configuration
# ─────────────────────────────────────────────────────────────────────────────

@restricted
async def trade_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"⚙️ *Auto-Trade Configuration*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Symbol:          `{SYMBOL}`\n"
        f"Trade Budget:    `${TRADE_BUDGET_USDT:.2f} USDT`\n"
        f"Stop-Loss:       `{STOP_LOSS_PCT:.1f}%`\n"
        f"Max Drawdown:    `{MAX_DRAWDOWN_PCT:.1f}%`\n"
        f"Cooldown:        `{COOLDOWN_HOURS:.1f} hours`\n"
        f"Min Score Delta: `{MIN_SCORE_DELTA:.1f} pts`\n\n"
        f"*Position Sizing:*\n"
        f"STRONG\\_BUY  → 100% of budget\n"
        f"BUY         → 60% of budget\n"
        f"WEAK\\_BUY   → 30% of budget\n"
        f"STRONG\\_SELL → 100% of position\n"
        f"SELL        → 60% of position\n"
        f"WEAK\\_SELL  → 30% of position\n\n"
        f"_Override via environment variables in .env_"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────────────────────
# /dryrun — Simulate a trade
# ─────────────────────────────────────────────────────────────────────────────

@restricted
async def dry_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🧪 Running dry-run simulation...")
    try:
        client = get_client()
        snapshot = get_full_macro_snapshot(client)
        result = compute_gold_score(snapshot)
        trade = execute_auto_trade(result, dry_run=True)

        action = trade.get("action", "UNKNOWN")
        text = (
            f"🧪 *Dry-Run Simulation Result*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Signal:  `{result['signal']}` ({result['composite_score']:+.1f})\n"
            f"Regime:  `{result['regime_code']}`\n\n"
            f"*Simulated Action:* `{action}`\n"
        )
        if "qty" in trade:
            text += f"Qty:     `{trade['qty']} PAXG`\n"
            text += f"Price:   `${trade.get('price', 0):,.2f}`\n"
        if "est_pnl" in trade:
            text += f"Est P&L: `${trade['est_pnl']:+,.4f}`\n"
        if "reason" in trade:
            text += f"Reason:  _{trade['reason']}_\n"
        if trade.get("risk_flags"):
            text += "\n*Risk Flags:*\n" + "\n".join(trade["risk_flags"])

        text += "\n\n_No real order was placed. Use `/autotrade on` to enable live trading._"
        await msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ Dry-run failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# /goldrisks — Risk flag report
# ─────────────────────────────────────────────────────────────────────────────

@restricted
async def gold_risks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 Scanning for risk triggers...")
    try:
        client = get_client()
        snapshot = get_full_macro_snapshot(client)
        result = compute_gold_score(snapshot)

        ry = snapshot.get("real_yield", {})
        usd = snapshot.get("usd", {})

        text = (
            f"🗺 *Gold Risk Map*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"*Bearish Macro Triggers (ranked):*\n\n"
            f"1️⃣ Real Yields: `{ry.get('real_yield', 'N/A'):.2f}%` | 5d chg: `{ry.get('real_yield_5d_chg_bps', 0):+.0f} bps`\n"
            f"   {'🔴 RISING FAST — correction risk elevated' if ry.get('real_yield_5d_chg_bps', 0) > 20 else '✅ Within normal range'}\n\n"
            f"2️⃣ USD/DXY: `{usd.get('dxy', 'N/A'):.2f}` | 5d: `{usd.get('chg_5d_pct', 0):+.2f}%`\n"
            f"   {'🔴 STRONG UP — gold downside pressure' if usd.get('trend') == 'STRONG_UP' else '✅ No breakout detected'}\n\n"
        )

        if result["risk_flags"]:
            text += "*Active Risk Flags:*\n"
            for flag in result["risk_flags"]:
                text += f"{flag}\n"
        else:
            text += "✅ *No active risk flags detected.*\n"

        text += (
            f"\n*Structural Bearish Checklist:*\n"
            f"{'🔴' if ry.get('real_yield_5d_chg_bps', 0) > 15 else '✅'} Real yields rising persistently\n"
            f"{'🔴' if usd.get('chg_5d_pct', 0) > 0.8 else '✅'} USD trend breakout\n"
            f"{'⚠' if result['composite_score'] < -20 else '✅'} Macro score deteriorating\n"
            f"{'🔴' if snapshot.get('positioning', {}).get('crowded_long') else '✅'} Crowded long positioning\n"
        )

        await msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# /tradehistory — Recent auto-trade log
# ─────────────────────────────────────────────────────────────────────────────

@restricted
async def trade_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = get_state()
    history = state.get("trade_history", [])

    if not history:
        await update.message.reply_text("📋 No auto-trade history yet.")
        return

    lines = ["📋 *Recent Auto-Trade History (last 10):*\n"]
    for t in history[-10:]:
        action_emoji = "🟢" if t["action"] == "BUY" else "🔴"
        pnl_str = f" | P&L: `${t['pnl']:+.4f}`" if "pnl" in t else ""
        lines.append(
            f"{action_emoji} `{t['action']}` {t.get('qty', '?')} PAXG @ `${t.get('price', 0):,.2f}`"
            f"{pnl_str}\n"
            f"  Signal: `{t.get('signal', 'N/A')}` | Score: `{t.get('score', 0):+.1f}`\n"
            f"  _{t['time']}_\n"
        )

    total_pnl = state.get("total_pnl_usdt", 0.0)
    lines.append(f"\n*Total Realized P&L:* `${total_pnl:+.4f} USDT`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
