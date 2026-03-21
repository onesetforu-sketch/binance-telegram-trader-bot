"""
PAXG Auto-Trading Strategy Engine
====================================
Translates macro regime scores into concrete PAXG/USDT trade actions on Binance.

Strategy Logic:
  - Uses the composite gold score from regime_engine.py
  - Applies position sizing based on signal strength
  - Enforces risk management: stop-loss, max drawdown, cooldown periods
  - Tracks open positions and P&L in memory (persistent via JSON state file)

Position Sizing:
  STRONG_BUY  → 100% of configured trade budget
  BUY         → 60% of budget
  WEAK_BUY    → 30% of budget
  NEUTRAL     → Hold / no action
  WEAK_SELL   → Close 30% of position
  SELL        → Close 60% of position
  STRONG_SELL → Close 100% of position (full exit)

Risk Rules:
  1. No trade if last trade was within COOLDOWN_HOURS
  2. No new BUY if drawdown from peak > MAX_DRAWDOWN_PCT
  3. Auto stop-loss if price drops STOP_LOSS_PCT from entry
  4. Score must change by MIN_SCORE_DELTA to trigger a new trade
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from src.binance_client import get_client, place_market_order, get_ticker_price

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration (can be overridden via environment variables)
# ─────────────────────────────────────────────────────────────────────────────

TRADE_BUDGET_USDT = float(os.getenv("PAXG_TRADE_BUDGET_USDT", "100"))   # Max USDT per trade cycle
STOP_LOSS_PCT = float(os.getenv("PAXG_STOP_LOSS_PCT", "3.0"))           # Stop-loss %
MAX_DRAWDOWN_PCT = float(os.getenv("PAXG_MAX_DRAWDOWN_PCT", "8.0"))     # Max portfolio drawdown
COOLDOWN_HOURS = float(os.getenv("PAXG_COOLDOWN_HOURS", "4.0"))         # Min hours between trades
MIN_SCORE_DELTA = float(os.getenv("PAXG_MIN_SCORE_DELTA", "15.0"))      # Min score change to act
STATE_FILE = Path(os.getenv("PAXG_STATE_FILE", "/tmp/paxg_state.json"))

SYMBOL = "PAXGUSDT"


# ─────────────────────────────────────────────────────────────────────────────
# State Management
# ─────────────────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    """Load trading state from JSON file."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "position_qty": 0.0,
        "avg_entry_price": 0.0,
        "peak_value": 0.0,
        "last_trade_time": None,
        "last_score": 0.0,
        "last_signal": "NEUTRAL",
        "trade_history": [],
        "auto_trade_enabled": False,
        "total_pnl_usdt": 0.0,
    }


def _save_state(state: dict):
    """Persist trading state to JSON file."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")


def get_state() -> dict:
    return _load_state()


def set_auto_trade(enabled: bool):
    state = _load_state()
    state["auto_trade_enabled"] = enabled
    _save_state(state)


# ─────────────────────────────────────────────────────────────────────────────
# Position Sizing
# ─────────────────────────────────────────────────────────────────────────────

def _compute_buy_qty(signal: str, current_price: float) -> float:
    """Calculate how many PAXG to buy based on signal strength."""
    size_map = {
        "STRONG_BUY": 1.0,
        "BUY": 0.6,
        "WEAK_BUY": 0.3,
    }
    fraction = size_map.get(signal, 0.0)
    usdt_amount = TRADE_BUDGET_USDT * fraction
    qty = usdt_amount / current_price
    # Round to 4 decimal places (PAXG precision)
    return round(qty, 4)


def _compute_sell_qty(signal: str, position_qty: float) -> float:
    """Calculate how many PAXG to sell based on signal strength."""
    size_map = {
        "STRONG_SELL": 1.0,
        "SELL": 0.6,
        "WEAK_SELL": 0.3,
    }
    fraction = size_map.get(signal, 0.0)
    qty = position_qty * fraction
    return round(qty, 4)


# ─────────────────────────────────────────────────────────────────────────────
# Risk Checks
# ─────────────────────────────────────────────────────────────────────────────

def _check_cooldown(state: dict) -> tuple[bool, str]:
    """Returns (ok_to_trade, reason)."""
    last = state.get("last_trade_time")
    if last:
        last_dt = datetime.fromisoformat(last)
        elapsed = (datetime.utcnow() - last_dt).total_seconds() / 3600
        if elapsed < COOLDOWN_HOURS:
            remaining = COOLDOWN_HOURS - elapsed
            return False, f"Cooldown active — {remaining:.1f}h remaining"
    return True, "OK"


def _check_drawdown(state: dict, current_price: float) -> tuple[bool, str]:
    """Returns (ok_to_buy, reason). Blocks new buys if drawdown is too large."""
    pos_qty = state.get("position_qty", 0.0)
    peak = state.get("peak_value", 0.0)
    if pos_qty > 0 and peak > 0:
        current_value = pos_qty * current_price
        drawdown = ((peak - current_value) / peak) * 100
        if drawdown > MAX_DRAWDOWN_PCT:
            return False, f"Max drawdown breached ({drawdown:.1f}% > {MAX_DRAWDOWN_PCT}%)"
    return True, "OK"


def _check_stop_loss(state: dict, current_price: float) -> bool:
    """Returns True if stop-loss should be triggered."""
    entry = state.get("avg_entry_price", 0.0)
    pos_qty = state.get("position_qty", 0.0)
    if pos_qty > 0 and entry > 0:
        loss_pct = ((entry - current_price) / entry) * 100
        if loss_pct >= STOP_LOSS_PCT:
            return True
    return False


def _check_score_delta(state: dict, new_score: float) -> bool:
    """Returns True if score changed enough to warrant action."""
    last_score = state.get("last_score", 0.0)
    return abs(new_score - last_score) >= MIN_SCORE_DELTA


# ─────────────────────────────────────────────────────────────────────────────
# Core Trade Execution
# ─────────────────────────────────────────────────────────────────────────────

def execute_auto_trade(score_result: dict, dry_run: bool = False) -> dict:
    """
    Main auto-trade function. Given a score result from regime_engine,
    decides whether to buy, sell, or hold PAXG.

    Args:
        score_result: Output from regime_engine.compute_gold_score()
        dry_run: If True, simulate trade without placing real orders.

    Returns:
        dict with action taken, reasoning, and order details.
    """
    state = _load_state()

    if not state.get("auto_trade_enabled") and not dry_run:
        return {"action": "SKIPPED", "reason": "Auto-trading is disabled. Use /autotrade on to enable."}

    signal = score_result.get("signal", "NEUTRAL")
    composite = score_result.get("composite_score", 0.0)
    risk_flags = score_result.get("risk_flags", [])

    # Get current PAXG price
    client = get_client()
    price_result = get_ticker_price(client, SYMBOL)
    if not price_result.get("success"):
        return {"action": "ERROR", "reason": f"Cannot fetch PAXG price: {price_result.get('error')}"}

    current_price = float(price_result["price"])
    pos_qty = state.get("position_qty", 0.0)
    now_iso = datetime.utcnow().isoformat()

    # ── Stop-Loss Check (overrides everything) ─────────────────────────────
    if _check_stop_loss(state, current_price) and pos_qty > 0:
        sell_qty = round(pos_qty, 4)
        reason = f"🛑 STOP-LOSS triggered at ${current_price:.2f} (entry ${state['avg_entry_price']:.2f})"
        if not dry_run:
            order = place_market_order(client, SYMBOL, "SELL", sell_qty)
            if order.get("success"):
                pnl = (current_price - state["avg_entry_price"]) * sell_qty
                state["total_pnl_usdt"] = round(state.get("total_pnl_usdt", 0) + pnl, 4)
                state["position_qty"] = 0.0
                state["avg_entry_price"] = 0.0
                state["last_trade_time"] = now_iso
                state["last_signal"] = "STOP_LOSS"
                state["trade_history"].append({
                    "time": now_iso, "action": "SELL", "qty": sell_qty,
                    "price": current_price, "reason": "stop_loss", "pnl": round(pnl, 4)
                })
                _save_state(state)
                return {"action": "STOP_LOSS_SELL", "qty": sell_qty, "price": current_price,
                        "pnl": round(pnl, 4), "reason": reason}
        else:
            return {"action": "DRY_RUN_STOP_LOSS", "qty": sell_qty, "price": current_price, "reason": reason}

    # ── Cooldown Check ─────────────────────────────────────────────────────
    ok_cooldown, cooldown_reason = _check_cooldown(state)
    if not ok_cooldown:
        return {"action": "SKIPPED", "reason": cooldown_reason, "signal": signal, "score": composite}

    # ── Score Delta Check ──────────────────────────────────────────────────
    if not _check_score_delta(state, composite):
        return {
            "action": "SKIPPED",
            "reason": f"Score delta too small ({abs(composite - state['last_score']):.1f} < {MIN_SCORE_DELTA})",
            "signal": signal,
            "score": composite
        }

    # ── BUY Logic ─────────────────────────────────────────────────────────
    if signal in ("STRONG_BUY", "BUY", "WEAK_BUY"):
        ok_dd, dd_reason = _check_drawdown(state, current_price)
        if not ok_dd:
            return {"action": "BLOCKED", "reason": dd_reason, "signal": signal}

        buy_qty = _compute_buy_qty(signal, current_price)
        if buy_qty < 0.0001:
            return {"action": "SKIPPED", "reason": "Computed buy quantity too small (<0.0001 PAXG)"}

        if not dry_run:
            order = place_market_order(client, SYMBOL, "BUY", buy_qty)
            if not order.get("success"):
                return {"action": "ERROR", "reason": order.get("error"), "signal": signal}

            # Update state
            old_qty = state["position_qty"]
            old_entry = state["avg_entry_price"]
            new_qty = old_qty + buy_qty
            if new_qty > 0:
                state["avg_entry_price"] = round(
                    (old_qty * old_entry + buy_qty * current_price) / new_qty, 4
                )
            state["position_qty"] = round(new_qty, 4)
            state["peak_value"] = max(state.get("peak_value", 0), new_qty * current_price)
            state["last_trade_time"] = now_iso
            state["last_score"] = composite
            state["last_signal"] = signal
            state["trade_history"].append({
                "time": now_iso, "action": "BUY", "qty": buy_qty,
                "price": current_price, "signal": signal, "score": composite
            })
            _save_state(state)
            return {
                "action": "BUY", "qty": buy_qty, "price": current_price,
                "signal": signal, "score": composite,
                "new_position": state["position_qty"],
                "risk_flags": risk_flags,
            }
        else:
            return {
                "action": "DRY_RUN_BUY", "qty": buy_qty, "price": current_price,
                "signal": signal, "score": composite, "risk_flags": risk_flags,
            }

    # ── SELL Logic ────────────────────────────────────────────────────────
    elif signal in ("STRONG_SELL", "SELL", "WEAK_SELL"):
        if pos_qty <= 0:
            return {"action": "SKIPPED", "reason": "No position to sell", "signal": signal}

        sell_qty = _compute_sell_qty(signal, pos_qty)
        if sell_qty < 0.0001:
            return {"action": "SKIPPED", "reason": "Computed sell quantity too small"}

        if not dry_run:
            order = place_market_order(client, SYMBOL, "SELL", sell_qty)
            if not order.get("success"):
                return {"action": "ERROR", "reason": order.get("error"), "signal": signal}

            pnl = (current_price - state["avg_entry_price"]) * sell_qty
            state["position_qty"] = round(pos_qty - sell_qty, 4)
            state["total_pnl_usdt"] = round(state.get("total_pnl_usdt", 0) + pnl, 4)
            if state["position_qty"] <= 0:
                state["avg_entry_price"] = 0.0
                state["peak_value"] = 0.0
            state["last_trade_time"] = now_iso
            state["last_score"] = composite
            state["last_signal"] = signal
            state["trade_history"].append({
                "time": now_iso, "action": "SELL", "qty": sell_qty,
                "price": current_price, "signal": signal, "score": composite, "pnl": round(pnl, 4)
            })
            _save_state(state)
            return {
                "action": "SELL", "qty": sell_qty, "price": current_price,
                "signal": signal, "score": composite, "pnl": round(pnl, 4),
                "remaining_position": state["position_qty"],
                "risk_flags": risk_flags,
            }
        else:
            est_pnl = (current_price - state.get("avg_entry_price", current_price)) * sell_qty
            return {
                "action": "DRY_RUN_SELL", "qty": sell_qty, "price": current_price,
                "signal": signal, "score": composite, "est_pnl": round(est_pnl, 4),
                "risk_flags": risk_flags,
            }

    # ── NEUTRAL ───────────────────────────────────────────────────────────
    else:
        state["last_score"] = composite
        state["last_signal"] = "NEUTRAL"
        _save_state(state)
        return {"action": "HOLD", "reason": "Neutral signal — no trade", "signal": signal, "score": composite}


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio Summary
# ─────────────────────────────────────────────────────────────────────────────

def get_portfolio_summary() -> dict:
    """Return current PAXG position summary with unrealized P&L."""
    state = _load_state()
    client = get_client()

    price_result = get_ticker_price(client, SYMBOL)
    current_price = float(price_result["price"]) if price_result.get("success") else 0.0

    pos_qty = state.get("position_qty", 0.0)
    entry = state.get("avg_entry_price", 0.0)
    current_value = pos_qty * current_price
    cost_basis = pos_qty * entry
    unrealized_pnl = current_value - cost_basis
    unrealized_pct = ((current_price - entry) / entry * 100) if entry > 0 else 0.0

    return {
        "position_qty": pos_qty,
        "avg_entry_price": entry,
        "current_price": current_price,
        "current_value_usdt": round(current_value, 2),
        "unrealized_pnl_usdt": round(unrealized_pnl, 4),
        "unrealized_pct": round(unrealized_pct, 2),
        "realized_pnl_usdt": state.get("total_pnl_usdt", 0.0),
        "auto_trade_enabled": state.get("auto_trade_enabled", False),
        "last_signal": state.get("last_signal", "N/A"),
        "last_score": state.get("last_score", 0.0),
        "last_trade_time": state.get("last_trade_time", "Never"),
        "trade_count": len(state.get("trade_history", [])),
    }
