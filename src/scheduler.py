"""
Background Scheduler
=====================
Runs periodic macro analysis and sends Telegram alerts when:
  - The regime changes
  - A new trade signal is generated
  - A stop-loss is triggered
  - Risk flags are newly detected

Runs every ANALYSIS_INTERVAL_MINUTES (default: 60 minutes).
"""

import os
import logging
import asyncio
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

from src.binance_client import get_client
from src.macro_data import get_full_macro_snapshot
from src.regime_engine import compute_gold_score
from src.paxg_trader import execute_auto_trade, get_state

logger = logging.getLogger(__name__)

ANALYSIS_INTERVAL_MINUTES = int(os.getenv("ANALYSIS_INTERVAL_MINUTES", "60"))
TELEGRAM_ALLOWED_USER_ID = int(os.getenv("TELEGRAM_ALLOWED_USER_ID", "0"))

# Track last regime to detect changes
_last_regime = None
_last_signal = None
_last_risk_flags = []


async def run_analysis_cycle(bot: Bot):
    """
    Core analysis cycle:
    1. Fetch macro snapshot
    2. Compute gold score
    3. Execute auto-trade if enabled
    4. Send Telegram alert if signal/regime changed or risks detected
    """
    global _last_regime, _last_signal, _last_risk_flags

    if not TELEGRAM_ALLOWED_USER_ID:
        logger.warning("TELEGRAM_ALLOWED_USER_ID not set — skipping alerts")
        return

    try:
        logger.info("Running scheduled macro analysis cycle...")
        client = get_client()
        snapshot = get_full_macro_snapshot(client)
        result = compute_gold_score(snapshot)

        signal = result["signal"]
        regime = result["regime_code"]
        score = result["composite_score"]
        risk_flags = result["risk_flags"]

        # ── Determine if we should send an alert ──────────────────────────
        regime_changed = regime != _last_regime
        signal_changed = signal != _last_signal
        new_risks = [f for f in risk_flags if f not in _last_risk_flags]
        strong_signal = signal in ("STRONG_BUY", "STRONG_SELL")

        should_alert = regime_changed or signal_changed or new_risks or strong_signal

        # ── Execute auto-trade if enabled ──────────────────────────────────
        state = get_state()
        trade_result = None
        if state.get("auto_trade_enabled"):
            trade_result = execute_auto_trade(result, dry_run=False)
            trade_acted = trade_result.get("action") not in ("SKIPPED", "HOLD", "ERROR")
            if trade_acted:
                should_alert = True

        # ── Send alert if warranted ────────────────────────────────────────
        if should_alert:
            msg = _build_alert_message(result, trade_result, regime_changed, signal_changed, new_risks)
            await bot.send_message(
                chat_id=TELEGRAM_ALLOWED_USER_ID,
                text=msg,
                parse_mode="Markdown"
            )
            logger.info(f"Alert sent: regime={regime}, signal={signal}, score={score}")

        # Update tracking state
        _last_regime = regime
        _last_signal = signal
        _last_risk_flags = risk_flags

    except Exception as e:
        logger.error(f"Analysis cycle failed: {e}")
        try:
            await bot.send_message(
                chat_id=TELEGRAM_ALLOWED_USER_ID,
                text=f"⚠️ Scheduled analysis cycle failed: `{e}`",
                parse_mode="Markdown"
            )
        except Exception:
            pass


def _build_alert_message(result: dict, trade_result: dict, regime_changed: bool,
                          signal_changed: bool, new_risks: list) -> str:
    """Build a concise Telegram alert message."""
    signal_emoji = result["signal_emoji"]
    lines = [
        f"🔔 *PAXG Macro Alert*",
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
        f"",
    ]

    if regime_changed:
        lines.append(f"🏛 *Regime Change → `{result['regime_code']}`*")
        lines.append(f"_{result['regime_desc']}_")
        lines.append("")

    if signal_changed or result["signal"] in ("STRONG_BUY", "STRONG_SELL"):
        lines.append(f"{signal_emoji} *Signal: `{result['signal']}`*")
        lines.append(f"Score: `{result['composite_score']:+.1f}` | _{result['action']}_")
        lines.append("")

    if new_risks:
        lines.append("*New Risk Flags:*")
        for r in new_risks:
            lines.append(r)
        lines.append("")

    if trade_result:
        action = trade_result.get("action", "")
        if action in ("BUY", "SELL", "STOP_LOSS_SELL"):
            emoji = "🟢" if action == "BUY" else "🔴"
            lines.append(f"{emoji} *Auto-Trade Executed: `{action}`*")
            lines.append(f"Qty: `{trade_result.get('qty', '?')} PAXG` @ `${trade_result.get('price', 0):,.2f}`")
            if "pnl" in trade_result:
                lines.append(f"P&L: `${trade_result['pnl']:+.4f} USDT`")
            lines.append("")
        elif action == "SKIPPED":
            lines.append(f"⏸ Trade skipped: _{trade_result.get('reason', '')}_")

    lines.append(f"_Analysis time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}_")
    return "\n".join(lines)


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Initialize and start the APScheduler background job."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_analysis_cycle,
        trigger="interval",
        minutes=ANALYSIS_INTERVAL_MINUTES,
        args=[bot],
        id="macro_analysis",
        name="PAXG Macro Analysis",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started — analysis every {ANALYSIS_INTERVAL_MINUTES} minutes")
    return scheduler
