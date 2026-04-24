"""
Price-Action Strategy — Telegram command handlers.

Commands
--------
    /palevels    — Show today's key levels and session VWAP.
    /pasignal    — Show the current PA bias (LONG / SHORT / NO SETUP) + checklist.
    /pastrategy  — Toggle alert broadcasting (on / off / status).

This iteration is ALERT-ONLY: the bot never places orders from the PA
strategy. The scheduled analysis cycle (see ``src.scheduler``) evaluates
the signal every N minutes and, when ``alerts_enabled`` is True and a new
qualifying setup appears, sends a Telegram message to the allowed user.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from src.auth import edit_safe, reply_safe, restricted
from src.pa_strategy import (
    ROUND_STEP,
    RR_RATIO,
    SYMBOL,
    active_session,
    compute_key_levels,
    compute_signal,
    load_pa_state,
    set_alerts_enabled,
)

logger = logging.getLogger(__name__)


def _fmt(value, spec: str = ".2f", fallback: str = "N/A") -> str:
    if value is None:
        return fallback
    try:
        return format(float(value), spec)
    except (TypeError, ValueError):
        return fallback


def _bias_emoji(bias: str) -> str:
    return {
        "LONG": "🟢",
        "SHORT": "🔴",
        "NO_SETUP": "⚪",
    }.get(bias, "⚪")


def format_signal_message(signal: dict, *, compact: bool = False) -> str:
    bias = signal.get("bias", "NO_SETUP")
    session = signal.get("session", "?")
    emoji = _bias_emoji(bias)

    if bias == "NO_SETUP":
        lines = [
            f"{emoji} *PA Signal — NO SETUP*",
            f"Session: `{session}`",
            f"_{signal.get('reason', 'No setup.')}_",
        ]
        vwap = signal.get("vwap") or signal.get("levels", {}).get("session_vwap")
        if vwap is not None:
            lines.append(f"VWAP: `${_fmt(vwap)}`")
        if signal.get("nearest_resistance") is not None:
            lines.append(f"Nearest R: `${_fmt(signal['nearest_resistance'])}`")
        if signal.get("nearest_support") is not None:
            lines.append(f"Nearest S: `${_fmt(signal['nearest_support'])}`")
        return "\n".join(lines)

    checklist = signal.get("checklist", {})
    lines = [
        f"{emoji} *PA {bias} SETUP* — {SYMBOL}",
        f"Session: `{session}`",
        "",
        f"Entry:      `${_fmt(signal.get('entry'))}`",
        f"Stop-Loss:  `${_fmt(signal.get('stop_loss'))}`",
        f"Take-Profit:`${_fmt(signal.get('take_profit'))}`",
        f"Risk / unit:`${_fmt(signal.get('risk_per_unit'), '.4f')}`",
        f"RR:         `{_fmt(signal.get('rr'))}` (target ≥ {RR_RATIO:.1f})",
        "",
        f"Broken level: `${_fmt(signal.get('broken_level'))}`",
        f"VWAP:         `${_fmt(signal.get('vwap'))}`",
        f"Volume:       `{_fmt(signal.get('volume_ratio'))}× 20-bar avg`",
        "",
        "*Checklist*",
        f"  • Trend (VWAP): `{checklist.get('trend_vwap', '?')}`",
        f"  • Breakout:     `{checklist.get('breakout', '?')}`",
        f"  • Volume:       `{'YES' if checklist.get('volume_confirm') else 'NO'}`",
        f"  • Candle:       `{checklist.get('candle_confirm', '?')}`",
        "",
        "_Alert-only. No orders placed._",
    ]
    return "\n".join(lines)


def _format_levels_message(levels: dict) -> str:
    session_ok, session = active_session()
    header = "✅ Trading session" if session_ok else "⛔ Off-hours"
    price = levels.get("current_price")
    vwap = levels.get("session_vwap")
    bias = "—"
    if price is not None and vwap is not None:
        bias = "LONG" if price > vwap else ("SHORT" if price < vwap else "NEUTRAL")

    lines = [
        f"📍 *PA Key Levels — {SYMBOL}*",
        f"{header}: `{session}`",
        "",
        f"Price:        `${_fmt(price)}`",
        f"Session VWAP: `${_fmt(vwap)}`  → bias *{bias}*",
        "",
        f"Yesterday H:  `${_fmt(levels.get('yesterday_high'))}`",
        f"Yesterday L:  `${_fmt(levels.get('yesterday_low'))}`",
        f"Asia H (00-09 UTC): `${_fmt(levels.get('asian_high'))}`",
        f"Asia L (00-09 UTC): `${_fmt(levels.get('asian_low'))}`",
        "",
        f"Round levels (step ${ROUND_STEP:.0f}):",
    ]
    for lvl in levels.get("round_levels", []) or []:
        marker = "👉" if price is not None and abs(lvl - price) < ROUND_STEP / 2 else "  "
        lines.append(f"  {marker} `${_fmt(lvl)}`")
    return "\n".join(lines)


@restricted
async def pa_levels_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/palevels` — show today's key levels + VWAP."""
    msg = await update.message.reply_text("📍 Fetching PA key levels...")
    try:
        levels = compute_key_levels()
        await edit_safe(msg, _format_levels_message(levels.as_dict()))
    except Exception as exc:
        logger.exception("/palevels failed")
        await edit_safe(msg, f"❌ Failed to compute levels: {exc}")


@restricted
async def pa_signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/pasignal` — show current PA bias with checklist."""
    msg = await update.message.reply_text("🔎 Evaluating PA signal...")
    try:
        signal = compute_signal()
        await edit_safe(msg, format_signal_message(signal))
    except Exception as exc:
        logger.exception("/pasignal failed")
        await edit_safe(msg, f"❌ Failed to compute signal: {exc}")


@restricted
async def pa_strategy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/pastrategy on|off|status` — toggle PA alert broadcasting."""
    args = [a.lower() for a in (context.args or [])]
    state = load_pa_state()

    if not args or args[0] == "status":
        status_text = (
            "🟢 *ENABLED*" if state.get("alerts_enabled") else "🔴 *DISABLED*"
        )
        last_bias = state.get("last_signal_bias", "NO_SETUP")
        last_level = state.get("last_signal_broken_level")
        last_alert = state.get("last_alert_time") or "never"
        seen = state.get("signals_seen", 0)
        text = (
            f"📡 *PA Strategy Alerts*\n"
            f"Status: {status_text}\n"
            f"Last bias: `{last_bias}`\n"
            f"Last broken level: `${_fmt(last_level)}`\n"
            f"Last alert: `{last_alert}`\n"
            f"Signals seen this session: `{seen}`\n\n"
            f"_Usage: `/pastrategy on` | `/pastrategy off` | `/pastrategy status`_"
        )
        await reply_safe(update, text)
        return

    if args[0] == "on":
        set_alerts_enabled(True)
        await reply_safe(
            update,
            "🟢 PA alerts *enabled*. You'll be notified when a fresh LONG/SHORT setup appears.\n"
            "_Alert-only mode: no orders are placed._",
        )
        return

    if args[0] == "off":
        set_alerts_enabled(False)
        await reply_safe(update, "🔴 PA alerts *disabled*.")
        return

    await reply_safe(
        update,
        "Usage: `/pastrategy on` | `/pastrategy off` | `/pastrategy status`",
    )
