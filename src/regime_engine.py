"""
Regime Detection & Scoring Engine
===================================
Implements the 5-factor gold framework:

  Gold Price ≈ f(Real Yield, USD, Liquidity, Risk Premium, Official Demand, Positioning)

Weights (impact strength):
  1. Real Yield      — weight 30
  2. USD Direction   — weight 25
  3. Liquidity/Policy— weight 20
  4. Risk Premium    — weight 15
  5. Positioning     — weight 10

Score range: -100 (maximum bearish) to +100 (maximum bullish)

Regimes:
  A — Disinflation + falling real yields  (best for gold)
  B — High inflation + aggressive tightening
  C — Crisis / safe-haven shock
  D — Growth / risk-on
  MIXED — Conflicting signals
"""

import logging
from typing import Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Factor Scoring Functions (each returns -1.0 to +1.0)
# ─────────────────────────────────────────────────────────────────────────────

def score_real_yield(ry: dict) -> Tuple[float, str]:
    """Score Factor 1: Real Yield. Falling real yields = bullish gold."""
    if not ry.get("success"):
        return 0.0, "No data"

    trend = ry.get("trend", "STABLE")
    chg_bps = ry.get("real_yield_5d_chg_bps", 0)
    level = ry.get("real_yield", 0)

    # Trend-based score
    trend_map = {
        "FALLING_FAST": 1.0,
        "FALLING": 0.6,
        "STABLE": 0.0,
        "RISING": -0.6,
        "RISING_FAST": -1.0,
    }
    score = trend_map.get(trend, 0.0)

    # Elasticity penalty: if real yield > 2%, gold is under structural pressure
    if level > 2.0:
        score -= 0.2
    elif level < 0:
        score += 0.2

    score = max(-1.0, min(1.0, score))
    note = f"Real yield {ry['real_yield']:.2f}% | 5d chg {chg_bps:+.0f}bps | {trend}"
    return score, note


def score_usd(usd: dict) -> Tuple[float, str]:
    """Score Factor 2: USD Direction. Falling USD = bullish gold."""
    if not usd.get("success"):
        return 0.0, "No data"

    trend = usd.get("trend", "FLAT")
    chg_5d = usd.get("chg_5d_pct", 0)
    chg_20d = usd.get("chg_20d_pct", 0) or 0

    trend_map = {
        "STRONG_DOWN": 1.0,
        "DOWN": 0.5,
        "FLAT": 0.0,
        "UP": -0.5,
        "STRONG_UP": -1.0,
    }
    score = trend_map.get(trend, 0.0)

    # Longer-term confirmation: if 20d also falling, add confidence
    if chg_20d < -1.0:
        score = min(1.0, score + 0.2)
    elif chg_20d > 1.0:
        score = max(-1.0, score - 0.2)

    note = f"DXY {usd['dxy']:.2f} | 5d {chg_5d:+.2f}% | 20d {chg_20d:+.2f}% | {trend}"
    return score, note


def score_liquidity(liq: dict) -> Tuple[float, str]:
    """Score Factor 3: Global Liquidity. Easing/risk-off = bullish gold."""
    if not liq.get("success"):
        return 0.0, "No data"

    liq_score = liq.get("liquidity_score", 0)
    tlt_trend = liq.get("tlt_trend", "FLAT")

    # Normalize liquidity_score (-2 to +2) → (-1 to +1)
    score = liq_score / 2.0

    note = f"Liquidity score {liq_score:+d} | Bonds: {tlt_trend}"
    return score, note


def score_risk_premium(rp: dict) -> Tuple[float, str]:
    """Score Factor 4: Risk Premium / VIX. High fear = bullish gold."""
    if not rp.get("success"):
        return 0.0, "No data"

    regime = rp.get("regime", "NORMAL")
    spike = rp.get("spike", False)
    vix = rp.get("vix", 20)

    regime_map = {
        "CRISIS": 1.0,
        "ELEVATED_FEAR": 0.6,
        "NORMAL": 0.0,
        "COMPLACENCY": -0.4,
    }
    score = regime_map.get(regime, 0.0)

    # Spike adds urgency (short-term safe-haven burst)
    if spike:
        score = min(1.0, score + 0.3)

    note = f"VIX {vix:.1f} | {regime}{' (SPIKE)' if spike else ''}"
    return score, note


def score_positioning(pos: dict) -> Tuple[float, str]:
    """Score Factor 5: PAXG Positioning/Momentum. Crowded long = correction risk."""
    if not pos.get("success"):
        return 0.0, "No data"

    momentum = pos.get("momentum", "RANGING")
    crowded = pos.get("crowded_long", False)
    chg_5d = pos.get("chg_5d_pct", 0)

    momentum_map = {
        "STRONG_UPTREND": 0.8,
        "UPTREND": 0.4,
        "RANGING": 0.0,
        "DOWNTREND": -0.4,
        "STRONG_DOWNTREND": -0.8,
    }
    score = momentum_map.get(momentum, 0.0)

    # Crowded long is a correction risk — reduce score
    if crowded:
        score -= 0.4

    score = max(-1.0, min(1.0, score))
    note = f"PAXG {pos['price']:.2f} | {momentum}{' ⚠ CROWDED' if crowded else ''} | 5d {chg_5d:+.2f}%"
    return score, note


# ─────────────────────────────────────────────────────────────────────────────
# Regime Classifier
# ─────────────────────────────────────────────────────────────────────────────

def classify_regime(ry_score: float, usd_score: float, liq_score: float,
                    rp_score: float, pos_score: float, composite: float) -> Tuple[str, str]:
    """
    Classify the current macro regime for gold.

    Returns (regime_code, description)
    """
    vix_crisis = rp_score >= 0.6
    yields_falling = ry_score >= 0.5
    usd_falling = usd_score >= 0.4
    yields_rising = ry_score <= -0.5
    usd_rising = usd_score <= -0.4

    if vix_crisis and composite > 0:
        return "C", "Crisis / Safe-Haven Regime — Gold safe-haven bid active"
    if yields_falling and usd_falling:
        return "A", "Regime A — Disinflation + Falling Real Yields (Best for Gold)"
    if yields_rising and usd_rising:
        return "B", "Regime B — Tightening / USD Strength (Headwind for Gold)"
    if composite > 30:
        return "A+", "Regime A+ — Strong Macro Tailwinds for Gold"
    if composite < -30:
        return "B+", "Regime B+ — Strong Macro Headwinds for Gold"
    if liq_score > 0.3 and not yields_rising:
        return "A", "Regime A — Easing Liquidity Supports Gold"
    if composite > 10:
        return "MIXED_BULL", "Mixed Regime — Slight Bullish Bias"
    if composite < -10:
        return "MIXED_BEAR", "Mixed Regime — Slight Bearish Bias"
    return "D", "Regime D — Neutral / Range-Bound (Risk-On Dominates)"


# ─────────────────────────────────────────────────────────────────────────────
# Main Scoring Function
# ─────────────────────────────────────────────────────────────────────────────

WEIGHTS = {
    "real_yield": 30,
    "usd": 25,
    "liquidity": 20,
    "risk_premium": 15,
    "positioning": 10,
}


def compute_gold_score(snapshot: dict) -> dict:
    """
    Given a full macro snapshot, compute the composite gold score,
    classify the regime, and generate a trading signal.

    Returns a rich dict with scores, notes, regime, signal, and reasoning.
    """
    ry_score, ry_note = score_real_yield(snapshot.get("real_yield", {}))
    usd_score, usd_note = score_usd(snapshot.get("usd", {}))
    liq_score, liq_note = score_liquidity(snapshot.get("liquidity", {}))
    rp_score, rp_note = score_risk_premium(snapshot.get("risk_premium", {}))
    pos_score, pos_note = score_positioning(snapshot.get("positioning", {}))

    # Weighted composite score (-100 to +100)
    composite = (
        ry_score * WEIGHTS["real_yield"] +
        usd_score * WEIGHTS["usd"] +
        liq_score * WEIGHTS["liquidity"] +
        rp_score * WEIGHTS["risk_premium"] +
        pos_score * WEIGHTS["positioning"]
    )

    regime_code, regime_desc = classify_regime(
        ry_score, usd_score, liq_score, rp_score, pos_score, composite
    )

    # ── Signal Generation ──────────────────────────────────────────────────
    if composite >= 55:
        signal = "STRONG_BUY"
        signal_emoji = "🟢🟢"
        action = "Strong macro tailwinds. Consider full position."
    elif composite >= 25:
        signal = "BUY"
        signal_emoji = "🟢"
        action = "Macro supports gold. Consider building position."
    elif composite >= 5:
        signal = "WEAK_BUY"
        signal_emoji = "🔵"
        action = "Mild bullish bias. Small position or watch."
    elif composite <= -55:
        signal = "STRONG_SELL"
        signal_emoji = "🔴🔴"
        action = "Strong macro headwinds. Reduce or exit position."
    elif composite <= -25:
        signal = "SELL"
        signal_emoji = "🔴"
        action = "Macro headwinds building. Consider reducing exposure."
    elif composite <= -5:
        signal = "WEAK_SELL"
        signal_emoji = "🟠"
        action = "Mild bearish bias. Tighten stops."
    else:
        signal = "NEUTRAL"
        signal_emoji = "⚪"
        action = "No clear macro edge. Stay patient."

    # ── Risk Flags ─────────────────────────────────────────────────────────
    risk_flags = []
    rp_data = snapshot.get("risk_premium", {})
    ry_data = snapshot.get("real_yield", {})
    usd_data = snapshot.get("usd", {})
    pos_data = snapshot.get("positioning", {})

    if ry_data.get("real_yield_5d_chg_bps", 0) > 20:
        risk_flags.append("⚠ Real yields rising fast (+20 bps) — correction risk")
    if usd_data.get("trend") == "STRONG_UP":
        risk_flags.append("⚠ DXY breaking up strongly — gold downside pressure")
    if ry_data.get("real_yield_5d_chg_bps", 0) > 15 and usd_data.get("chg_5d_pct", 0) > 0.5:
        risk_flags.append("🚨 DUAL RISK: Real yields rising + USD strengthening simultaneously")
    if pos_data.get("crowded_long"):
        risk_flags.append("⚠ Crowded long positioning — small macro shift could trigger sharp drop")
    if rp_data.get("spike"):
        risk_flags.append("⚡ VIX spike detected — short-term volatility whipsaw risk")

    return {
        "composite_score": round(composite, 1),
        "signal": signal,
        "signal_emoji": signal_emoji,
        "action": action,
        "regime_code": regime_code,
        "regime_desc": regime_desc,
        "factors": {
            "real_yield": {"score": round(ry_score, 2), "weight": WEIGHTS["real_yield"], "note": ry_note},
            "usd": {"score": round(usd_score, 2), "weight": WEIGHTS["usd"], "note": usd_note},
            "liquidity": {"score": round(liq_score, 2), "weight": WEIGHTS["liquidity"], "note": liq_note},
            "risk_premium": {"score": round(rp_score, 2), "weight": WEIGHTS["risk_premium"], "note": rp_note},
            "positioning": {"score": round(pos_score, 2), "weight": WEIGHTS["positioning"], "note": pos_note},
        },
        "risk_flags": risk_flags,
        "timestamp": snapshot.get("timestamp", ""),
    }
