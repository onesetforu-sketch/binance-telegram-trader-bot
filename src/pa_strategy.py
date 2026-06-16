"""
Price-Action Strategy for PAXG/USDT
====================================

Replaces the macro regime engine with a rule-based price-action strategy:

  1. Key levels (marked before every trade check):
       - Yesterday High / Low (prior UTC day)
       - Asian Session High / Low (00:00-09:00 UTC of current day)
       - Round-number levels every $25 around the current price
  2. Session VWAP anchored at 00:00 UTC, computed from 15-minute klines.
       - Price > VWAP → LONG bias
       - Price < VWAP → SHORT bias
  3. Volume confirmation: last closed candle volume must be >= 1.5× the
     20-bar average to qualify as a real breakout.
  4. Session filter: only London (07-16 UTC) or US (12-21 UTC).
     Asian / off-hours → NO_SETUP.
  5. Candle confirmation: last closed 15m candle must close on the side of
     the breakout (bullish for LONG, bearish for SHORT).

Signals are ALERT-ONLY in this first iteration — no orders are placed.
Auto-execution can be added later once the strategy is validated.

All data is fetched from the Binance klines endpoint (already available
through the existing ``src.binance_client`` wrapper). No new APIs needed.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from binance.client import Client

logger = logging.getLogger(__name__)


_market_client: Optional[Client] = None


def get_market_client() -> Client:
    """Public market-data client that always talks to Binance mainnet.

    The regular ``get_client()`` honours ``USE_TESTNET`` so trade orders go to
    the sandbox. But PAXG/USDT is not consistently listed on the Binance
    testnet, and klines/ticker endpoints are public (no API key required),
    so we keep a separate mainnet client purely for market data.
    """
    global _market_client
    if _market_client is None:
        _market_client = Client("", "", testnet=False)
    return _market_client


# ─────────────────────────────────────────────────────────────────────────────
# Configuration (overridable via environment variables)
# ─────────────────────────────────────────────────────────────────────────────

SYMBOL = os.getenv("PA_SYMBOL", "PAXGUSDT")
SIGNAL_INTERVAL = "15m"


def _safe_float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "")
    if not raw:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        logger.warning("Invalid float for %s=%r; using default %s", name, raw, default)
        return default


ROUND_STEP = _safe_float_env("PA_ROUND_STEP", 25.0)
VOLUME_SPIKE_MULT = _safe_float_env("PA_VOLUME_SPIKE_MULT", 1.5)
RR_RATIO = _safe_float_env("PA_RR_RATIO", 2.0)
RISK_PCT = _safe_float_env("PA_RISK_PCT", 1.0)  # % account risk per trade

# Session windows (UTC). Asian 00-09 is by user configuration.
ASIAN_START_HOUR, ASIAN_END_HOUR = 0, 9
LONDON_START_HOUR, LONDON_END_HOUR = 7, 16
US_START_HOUR, US_END_HOUR = 12, 21

# Persisted state (alert throttling, enabled flag)
_DEFAULT_PA_STATE_FILE = str(
    Path(__file__).resolve().parent.parent / "data" / "pa_state.json"
)
PA_STATE_FILE = Path(os.getenv("PA_STATE_FILE", _DEFAULT_PA_STATE_FILE))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def active_session(dt: Optional[datetime] = None) -> tuple[bool, str]:
    """Return (is_trading_session, session_label)."""
    dt = dt or _now_utc()
    h = dt.hour
    in_london = LONDON_START_HOUR <= h < LONDON_END_HOUR
    in_us = US_START_HOUR <= h < US_END_HOUR
    if in_london and in_us:
        return True, "LONDON_US_OVERLAP"
    if in_london:
        return True, "LONDON"
    if in_us:
        return True, "US"
    if ASIAN_START_HOUR <= h < ASIAN_END_HOUR:
        return False, "ASIAN"
    return False, "OFF_HOURS"


def _fetch_klines(client, interval: str, limit: int) -> list:
    """Return raw klines — caller handles the indices.

    Raises ``RuntimeError`` on empty response so callers don't quietly produce
    None-valued signals.
    """
    klines = client.get_klines(symbol=SYMBOL, interval=interval, limit=limit)
    if not klines:
        raise RuntimeError(f"Empty klines for {SYMBOL} {interval}")
    return klines


def round_levels_around(price: float, step: float = None, window: int = 3) -> list[float]:
    """Return ``2*window + 1`` round-number levels spanning the current price."""
    step = step if step is not None else ROUND_STEP
    if step <= 0:
        return []
    base = round(price / step) * step
    return [round(base + i * step, 2) for i in range(-window, window + 1)]


# ─────────────────────────────────────────────────────────────────────────────
# Key levels
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class KeyLevels:
    current_price: float
    yesterday_high: Optional[float]
    yesterday_low: Optional[float]
    asian_high: Optional[float]
    asian_low: Optional[float]
    round_levels: list[float]
    session_vwap: Optional[float]
    timestamp: str

    def as_dict(self) -> dict:
        return {
            "current_price": self.current_price,
            "yesterday_high": self.yesterday_high,
            "yesterday_low": self.yesterday_low,
            "asian_high": self.asian_high,
            "asian_low": self.asian_low,
            "round_levels": self.round_levels,
            "session_vwap": self.session_vwap,
            "timestamp": self.timestamp,
        }

    def candidates(self) -> list[float]:
        out = []
        for v in (
            self.yesterday_high,
            self.yesterday_low,
            self.asian_high,
            self.asian_low,
        ):
            if v is not None:
                out.append(v)
        out.extend(self.round_levels)
        return out


def _yesterday_high_low(client) -> tuple[Optional[float], Optional[float]]:
    daily = _fetch_klines(client, "1d", limit=3)
    # Last entry is the in-progress day; the one before is yesterday.
    if len(daily) < 2:
        return None, None
    y = daily[-2]
    try:
        return float(y[2]), float(y[3])
    except (IndexError, ValueError, TypeError):
        return None, None


def _asian_session_high_low(client) -> tuple[Optional[float], Optional[float]]:
    now = _now_utc()
    today = now.date()
    hourly = _fetch_klines(client, "1h", limit=48)
    asian = []
    for c in hourly:
        ts = datetime.fromtimestamp(c[0] / 1000, timezone.utc)
        if ts.date() != today:
            continue
        if ASIAN_START_HOUR <= ts.hour < ASIAN_END_HOUR:
            asian.append(c)
    if not asian:
        return None, None
    highs = [float(c[2]) for c in asian]
    lows = [float(c[3]) for c in asian]
    return max(highs), min(lows)


def _session_vwap(client) -> Optional[float]:
    """Daily-anchored session VWAP from 15m klines since 00:00 UTC."""
    now = _now_utc()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    klines = _fetch_klines(client, "15m", limit=96)  # 96 * 15m ≈ 24h

    num = 0.0
    den = 0.0
    for c in klines:
        ts = datetime.fromtimestamp(c[0] / 1000, timezone.utc)
        if ts < today_start:
            continue
        high = float(c[2])
        low = float(c[3])
        close = float(c[4])
        vol = float(c[5])
        typical = (high + low + close) / 3.0
        num += typical * vol
        den += vol

    if den <= 0:
        return None
    return num / den


def _current_price(client) -> float:
    ticker = client.get_symbol_ticker(symbol=SYMBOL)
    return float(ticker["price"])


def compute_key_levels(client=None) -> KeyLevels:
    """Fetch all key levels in one shot. Caller owns the Binance client."""
    if client is None:
        client = get_market_client()

    price = _current_price(client)
    y_high, y_low = _yesterday_high_low(client)
    a_high, a_low = _asian_session_high_low(client)
    vwap = _session_vwap(client)
    rounds = round_levels_around(price, ROUND_STEP, 3)

    return KeyLevels(
        current_price=price,
        yesterday_high=y_high,
        yesterday_low=y_low,
        asian_high=a_high,
        asian_low=a_low,
        round_levels=rounds,
        session_vwap=vwap,
        timestamp=_now_utc().isoformat(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Signal engine
# ─────────────────────────────────────────────────────────────────────────────

def _avg_volume_excluding_current(klines: list, lookback: int = 20) -> float:
    """Average volume over the last ``lookback`` *closed* candles."""
    if len(klines) < 2:
        return 0.0
    closed = klines[:-1]  # drop in-progress candle
    tail = closed[-lookback:] if len(closed) >= lookback else closed
    if not tail:
        return 0.0
    return sum(float(c[5]) for c in tail) / len(tail)


def _nearest_above(price: float, candidates: list[float]) -> Optional[float]:
    above = [c for c in candidates if c is not None and c > price]
    return min(above) if above else None


def _nearest_below(price: float, candidates: list[float]) -> Optional[float]:
    below = [c for c in candidates if c is not None and c < price]
    return max(below) if below else None


def _detect_crossed_level(
    prev_close: float, last_close: float, candidates: list[float], direction: str
) -> Optional[float]:
    """Return the level crossed by the last closed candle, if any.

    direction="up":   prev_close <= level < last_close
    direction="down": prev_close >= level > last_close
    """
    crossed = []
    for lvl in candidates:
        if lvl is None:
            continue
        if direction == "up" and prev_close <= lvl < last_close:
            crossed.append(lvl)
        elif direction == "down" and prev_close >= lvl > last_close:
            crossed.append(lvl)
    if not crossed:
        return None
    # Return the nearest (most recently broken) level.
    return max(crossed) if direction == "up" else min(crossed)


def compute_signal(client=None) -> dict:
    """Evaluate the current PA signal for ``SYMBOL``.

    Returns a dict with at least: ``bias``, ``reason``, ``session``, ``levels``.
    When a setup is found, also includes ``entry``, ``stop_loss``,
    ``take_profit``, ``risk_per_unit``, ``rr``, ``broken_level``.
    """
    if client is None:
        client = get_market_client()

    now = _now_utc()
    in_session, session = active_session(now)
    levels = compute_key_levels(client)

    base = {
        "session": session,
        "in_session": in_session,
        "levels": levels.as_dict(),
        "timestamp": now.isoformat(),
    }

    if not in_session:
        return {
            **base,
            "bias": "NO_SETUP",
            "reason": (
                f"Off-hours ({session}). Strategy only trades London "
                f"(07-16 UTC) or US (12-21 UTC) sessions."
            ),
        }

    price = levels.current_price
    vwap = levels.session_vwap
    if vwap is None:
        return {
            **base,
            "bias": "NO_SETUP",
            "reason": "Session VWAP unavailable (no 15m data since 00:00 UTC).",
        }

    long_bias = price > vwap
    candidates = levels.candidates()
    nearest_res = _nearest_above(price, candidates)
    nearest_sup = _nearest_below(price, candidates)

    klines = _fetch_klines(client, SIGNAL_INTERVAL, limit=30)
    if len(klines) < 22:
        return {
            **base,
            "bias": "NO_SETUP",
            "reason": "Not enough 15m history yet (<22 bars).",
        }

    # Last CLOSED candle is the second-to-last entry (last is in-progress).
    last_closed = klines[-2]
    prev_closed = klines[-3]

    last_open = float(last_closed[1])
    last_high = float(last_closed[2])
    last_low = float(last_closed[3])
    last_close = float(last_closed[4])
    last_volume = float(last_closed[5])
    prev_close = float(prev_closed[4])

    avg_vol = _avg_volume_excluding_current(klines, 20)
    volume_spike = avg_vol > 0 and last_volume >= VOLUME_SPIKE_MULT * avg_vol
    vol_ratio = (last_volume / avg_vol) if avg_vol > 0 else 0.0

    bullish_candle = last_close > last_open
    bearish_candle = last_close < last_open

    # Breakout detection uses the last closed candle crossing a level.
    up_broken = _detect_crossed_level(prev_close, last_close, candidates, "up")
    down_broken = _detect_crossed_level(prev_close, last_close, candidates, "down")

    checklist = {
        "trend_vwap": "LONG" if long_bias else "SHORT",
        "breakout": None,
        "volume_confirm": volume_spike,
        "candle_confirm": None,
    }

    long_invalidated = (
        long_bias and up_broken is not None and price < up_broken
    )
    short_invalidated = (
        (not long_bias) and down_broken is not None and price > down_broken
    )

    if (
        long_bias
        and up_broken is not None
        and volume_spike
        and bullish_candle
        and not long_invalidated
    ):
        sl = round(min(last_low, up_broken * 0.998), 2)
        risk = price - sl
        if risk <= 0:
            # Pathological geometry — abort rather than emit a bad signal.
            return {
                **base,
                "bias": "NO_SETUP",
                "reason": (
                    f"LONG invalidated: entry ${price:,.2f} is not above broken "
                    f"level ${up_broken:,.2f} after geometry check."
                ),
                "vwap": round(vwap, 2),
                "volume_ratio": round(vol_ratio, 2),
                "checklist": checklist,
            }
        # Target the next resistance; if RR < 2, override with 1:2 target.
        tp_candidate = nearest_res if nearest_res is not None and nearest_res > price else None
        if tp_candidate is None or (tp_candidate - price) / risk < RR_RATIO:
            tp = round(price + RR_RATIO * risk, 2)
        else:
            tp = round(tp_candidate, 2)
        rr = (tp - price) / risk if risk > 0 else None
        checklist["breakout"] = f"Broke ${up_broken:.2f}"
        checklist["candle_confirm"] = "BULLISH_CLOSE"
        return {
            **base,
            "bias": "LONG",
            "entry": round(price, 2),
            "stop_loss": sl,
            "take_profit": tp,
            "risk_per_unit": round(risk, 4),
            "rr": round(rr, 2) if rr is not None else None,
            "broken_level": round(up_broken, 2),
            "nearest_resistance": round(nearest_res, 2) if nearest_res else None,
            "nearest_support": round(nearest_sup, 2) if nearest_sup else None,
            "vwap": round(vwap, 2),
            "volume_ratio": round(vol_ratio, 2),
            "checklist": checklist,
            "reason": (
                f"LONG setup: price ${price:,.2f} > VWAP ${vwap:,.2f}, "
                f"broke ${up_broken:,.2f} on bullish 15m close, "
                f"volume {vol_ratio:.1f}× avg. Session: {session}."
            ),
        }

    if (
        (not long_bias)
        and down_broken is not None
        and volume_spike
        and bearish_candle
        and not short_invalidated
    ):
        sl = round(max(last_high, down_broken * 1.002), 2)
        risk = sl - price
        if risk <= 0:
            return {
                **base,
                "bias": "NO_SETUP",
                "reason": (
                    f"SHORT invalidated: entry ${price:,.2f} is not below broken "
                    f"level ${down_broken:,.2f} after geometry check."
                ),
                "vwap": round(vwap, 2),
                "volume_ratio": round(vol_ratio, 2),
                "checklist": checklist,
            }
        tp_candidate = nearest_sup if nearest_sup is not None and nearest_sup < price else None
        if tp_candidate is None or (price - tp_candidate) / risk < RR_RATIO:
            tp = round(price - RR_RATIO * risk, 2)
        else:
            tp = round(tp_candidate, 2)
        rr = (price - tp) / risk if risk > 0 else None
        checklist["breakout"] = f"Broke ${down_broken:.2f}"
        checklist["candle_confirm"] = "BEARISH_CLOSE"
        return {
            **base,
            "bias": "SHORT",
            "entry": round(price, 2),
            "stop_loss": sl,
            "take_profit": tp,
            "risk_per_unit": round(risk, 4),
            "rr": round(rr, 2) if rr is not None else None,
            "broken_level": round(down_broken, 2),
            "nearest_resistance": round(nearest_res, 2) if nearest_res else None,
            "nearest_support": round(nearest_sup, 2) if nearest_sup else None,
            "vwap": round(vwap, 2),
            "volume_ratio": round(vol_ratio, 2),
            "checklist": checklist,
            "reason": (
                f"SHORT setup: price ${price:,.2f} < VWAP ${vwap:,.2f}, "
                f"broke ${down_broken:,.2f} on bearish 15m close, "
                f"volume {vol_ratio:.1f}× avg. Session: {session}."
            ),
        }

    # No high-conviction setup — return the bias + missing checklist items.
    missing = []
    if long_bias and up_broken is None:
        missing.append("no bullish breakout")
    if (not long_bias) and down_broken is None:
        missing.append("no bearish breakout")
    if not volume_spike:
        missing.append(f"volume only {vol_ratio:.1f}× avg (need ≥{VOLUME_SPIKE_MULT}×)")
    if long_bias and not bullish_candle:
        missing.append("last 15m candle not bullish")
    if (not long_bias) and not bearish_candle:
        missing.append("last 15m candle not bearish")
    if long_invalidated:
        missing.append("price pulled back below broken level (invalidated)")
    if short_invalidated:
        missing.append("price pulled back above broken level (invalidated)")

    return {
        **base,
        "bias": "NO_SETUP",
        "reason": (
            f"Bias {'LONG' if long_bias else 'SHORT'} (price "
            f"{'>' if long_bias else '<'} VWAP ${vwap:,.2f}), "
            f"but missing: {', '.join(missing) or 'nothing'}."
        ),
        "nearest_resistance": round(nearest_res, 2) if nearest_res else None,
        "nearest_support": round(nearest_sup, 2) if nearest_sup else None,
        "vwap": round(vwap, 2),
        "volume_ratio": round(vol_ratio, 2),
        "checklist": checklist,
    }


# ─────────────────────────────────────────────────────────────────────────
# Persisted alert state
# ─────────────────────────────────────────────────────────────────────────


def _default_pa_state() -> dict:
    return {
        "alerts_enabled": False,
        "last_signal_bias": "NO_SETUP",
        "last_signal_broken_level": None,
        "last_alert_time": None,
        "signals_seen": 0,
        "last_error_message": None,
        "last_error_time": None,
    }


def load_pa_state() -> dict:
    if PA_STATE_FILE.exists():
        try:
            with open(PA_STATE_FILE) as f:
                loaded = json.load(f)
            merged = _default_pa_state()
            merged.update(loaded)
            return merged
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(
                "Failed to load PA state from %s (%s); using defaults",
                PA_STATE_FILE,
                e,
            )
    return _default_pa_state()


def save_pa_state(state: dict) -> None:
    try:
        PA_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PA_STATE_FILE.with_suffix(PA_STATE_FILE.suffix + ".tmp")
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        tmp.replace(PA_STATE_FILE)
    except OSError as e:
        logger.error("Failed to save PA state to %s: %s", PA_STATE_FILE, e)


def set_alerts_enabled(enabled: bool) -> None:
    state = load_pa_state()
    state["alerts_enabled"] = enabled
    save_pa_state(state)


def is_new_signal(signal: dict, state: dict) -> bool:
    """Return True if this signal is a new bias/level not just re-emitted."""
    if signal.get("bias") == "NO_SETUP":
        return False
    bias_changed = signal.get("bias") != state.get("last_signal_bias")
    level_changed = signal.get("broken_level") != state.get("last_signal_broken_level")
    return bias_changed or level_changed
