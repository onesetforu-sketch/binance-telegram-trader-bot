"""
Macro Data Fetcher
==================
Fetches live macro indicators used by the gold regime engine:

  Factor 1 — Real Yield      : ^TNX (10Y nominal) - breakeven inflation (^T5YIE proxy)
  Factor 2 — USD Direction   : DX-Y.NYB (DXY Index)
  Factor 3 — Global Liquidity: Fed balance sheet proxy via M2 / SPX breadth (^VIX inverse)
  Factor 4 — Risk Premium    : ^VIX (CBOE Volatility Index)
  Factor 5 — Positioning     : PAXG/USDT price momentum & volume on Binance

All data is fetched from Yahoo Finance (free, no API key required) and Binance.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)


def _round(value, digits: int = 2):
    """Round ``value`` to ``digits`` places, preserving ``None``.

    Prefer this over ``round(x, n) if x else None`` — the latter wrongly maps
    ``0.0`` and ``False`` to ``None``.
    """
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch(ticker: str, period: str = "3mo", interval: str = "1d") -> Optional[pd.DataFrame]:
    """Download OHLCV data for a ticker. Returns None on failure."""
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
        if df.empty:
            logger.warning(f"No data returned for {ticker}")
            return None
        return df
    except Exception as e:
        logger.error(f"Failed to fetch {ticker}: {e}")
        return None


def _latest_close(df: Optional[pd.DataFrame]) -> Optional[float]:
    if df is None or df.empty:
        return None
    val = df["Close"].iloc[-1]
    # Handle MultiIndex columns from yfinance
    if hasattr(val, 'iloc'):
        val = val.iloc[0]
    return float(val)


def _pct_change(df: Optional[pd.DataFrame], days: int = 5) -> Optional[float]:
    """Return % change over last `days` periods."""
    if df is None or len(df) < days + 1:
        return None
    close = df["Close"]
    if hasattr(close.iloc[-1], 'iloc'):
        # MultiIndex — flatten
        close = close.iloc[:, 0]
    current = float(close.iloc[-1])
    past = float(close.iloc[-(days + 1)])
    if past == 0:
        return None
    return ((current - past) / past) * 100


# ─────────────────────────────────────────────────────────────────────────────
# Factor 1 — Real Yield
# ─────────────────────────────────────────────────────────────────────────────

def get_real_yield() -> dict:
    """
    Approximate real yield = 10Y nominal yield (^TNX) minus 10Y breakeven inflation.
    Breakeven proxy: RINF ETF (ProShares Inflation Expectations) or fallback to
    fixed 2.5% estimate if market data unavailable.
    Returns current level, 5-day change, and trend direction.
    """
    tnx = _fetch("^TNX", period="3mo")
    # Try multiple breakeven proxies
    t5yie = _fetch("RINF", period="3mo")  # ProShares Inflation Expectations ETF

    nominal = _latest_close(tnx)

    # For breakeven: use RINF price change as proxy, or fallback to 2.3% estimate
    if t5yie is not None:
        # RINF is an ETF — use its 5d momentum as inflation expectation proxy
        rinf_chg = _pct_change(t5yie, 20)
        # Estimate breakeven: baseline 2.3% adjusted by RINF momentum
        breakeven = 2.3 + (rinf_chg or 0) * 0.05
    else:
        breakeven = 2.3  # Conservative fallback estimate

    if nominal is None:
        return {"success": False, "error": "Could not fetch yield data"}

    real_yield = nominal - breakeven
    # Compute 5-day change in real yield (in bps) — use TNX change since breakeven is estimated
    if tnx is not None and len(tnx) > 5:
        tnx_close = tnx["Close"]
        if hasattr(tnx_close.iloc[-1], 'iloc'):
            tnx_close = tnx_close.iloc[:, 0]
        nominal_5d_ago = float(tnx_close.iloc[-6])
        # Real yield change ≈ nominal yield change (breakeven assumed stable short-term)
        real_yield_5d_chg_bps = (nominal - nominal_5d_ago) * 100
    else:
        real_yield_5d_chg_bps = 0.0

    # Bearish for gold if real yield rising > +20 bps over 5 days
    if real_yield_5d_chg_bps > 20:
        trend = "RISING_FAST"   # Bearish gold
    elif real_yield_5d_chg_bps > 5:
        trend = "RISING"        # Mildly bearish
    elif real_yield_5d_chg_bps < -20:
        trend = "FALLING_FAST"  # Very bullish gold
    elif real_yield_5d_chg_bps < -5:
        trend = "FALLING"       # Bullish gold
    else:
        trend = "STABLE"

    return {
        "success": True,
        "nominal_yield": round(nominal, 3),
        "breakeven": round(breakeven, 3),
        "real_yield": round(real_yield, 3),
        "real_yield_5d_chg_bps": round(real_yield_5d_chg_bps, 1),
        "trend": trend,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Factor 2 — USD Direction (DXY)
# ─────────────────────────────────────────────────────────────────────────────

def get_usd_direction() -> dict:
    """
    Fetch DXY index. Compute 5-day and 20-day trend.
    Rising DXY = bearish gold. Falling DXY = bullish gold.
    """
    dxy = _fetch("DX-Y.NYB", period="3mo")
    if dxy is None:
        return {"success": False, "error": "Could not fetch DXY data"}

    current = _latest_close(dxy)
    chg_5d = _pct_change(dxy, 5)
    chg_20d = _pct_change(dxy, 20)

    if chg_5d is None:
        return {"success": False, "error": "Insufficient DXY history"}

    if chg_5d > 0.8:
        trend = "STRONG_UP"    # Bearish gold
    elif chg_5d > 0.2:
        trend = "UP"           # Mildly bearish
    elif chg_5d < -0.8:
        trend = "STRONG_DOWN"  # Very bullish gold
    elif chg_5d < -0.2:
        trend = "DOWN"         # Bullish gold
    else:
        trend = "FLAT"

    return {
        "success": True,
        "dxy": _round(current, 3),
        "chg_5d_pct": _round(chg_5d, 2),
        "chg_20d_pct": _round(chg_20d, 2),
        "trend": trend,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Factor 3 — Global Liquidity / Policy Regime
# ─────────────────────────────────────────────────────────────────────────────

def get_liquidity_regime() -> dict:
    """
    Proxy for global liquidity using:
    - SPY 50d vs 200d MA (risk-on = tightening liquidity for gold)
    - TLT (20Y bond ETF) trend (rising = easing = bullish gold)
    """
    spy = _fetch("SPY", period="1y")
    tlt = _fetch("TLT", period="3mo")

    spy_close = None
    spy_ma50 = None
    spy_ma200 = None
    tlt_trend = "UNKNOWN"

    if spy is not None and len(spy) >= 200:
        close = spy["Close"]
        if hasattr(close.iloc[-1], 'iloc'):
            close = close.iloc[:, 0]
        spy_close = float(close.iloc[-1])
        spy_ma50 = float(close.rolling(50).mean().iloc[-1])
        spy_ma200 = float(close.rolling(200).mean().iloc[-1])

    tlt_chg = _pct_change(tlt, 10)
    if tlt_chg is not None:
        if tlt_chg > 1.5:
            tlt_trend = "RALLYING"    # Bonds rallying = easing = bullish gold
        elif tlt_chg > 0.3:
            tlt_trend = "RISING"
        elif tlt_chg < -1.5:
            tlt_trend = "SELLING_OFF" # Bonds selling = tightening = bearish gold
        elif tlt_chg < -0.3:
            tlt_trend = "FALLING"
        else:
            tlt_trend = "FLAT"

    # Liquidity score: +1 bullish, -1 bearish, 0 neutral
    score = 0
    if spy_ma50 and spy_ma200:
        if spy_close < spy_ma50:
            score += 1   # Risk-off = gold friendly
        else:
            score -= 1
    if tlt_trend in ("RALLYING", "RISING"):
        score += 1
    elif tlt_trend in ("SELLING_OFF", "FALLING"):
        score -= 1

    return {
        "success": True,
        "spy_price": _round(spy_close, 2),
        "spy_ma50": _round(spy_ma50, 2),
        "spy_ma200": _round(spy_ma200, 2),
        "tlt_10d_chg_pct": _round(tlt_chg, 2),
        "tlt_trend": tlt_trend,
        "liquidity_score": score,  # +2 = very bullish, -2 = very bearish
    }


# ─────────────────────────────────────────────────────────────────────────────
# Factor 4 — Risk Premium (VIX)
# ─────────────────────────────────────────────────────────────────────────────

def get_risk_premium() -> dict:
    """
    VIX level and trend as a proxy for fear / risk premium.
    High VIX = crisis regime = safe-haven bid for gold.
    """
    vix = _fetch("^VIX", period="3mo")
    if vix is None:
        return {"success": False, "error": "Could not fetch VIX data"}

    current = _latest_close(vix)
    chg_5d = _pct_change(vix, 5)

    if current >= 35:
        regime = "CRISIS"          # Strong safe-haven bid
    elif current >= 25:
        regime = "ELEVATED_FEAR"   # Moderate safe-haven bid
    elif current >= 18:
        regime = "NORMAL"          # Neutral
    else:
        regime = "COMPLACENCY"     # Risk-on, gold less supported

    spike = chg_5d is not None and chg_5d > 20

    return {
        "success": True,
        "vix": _round(current, 2),
        "chg_5d_pct": _round(chg_5d, 2),
        "regime": regime,
        "spike": spike,  # True = sudden fear spike
    }


# ─────────────────────────────────────────────────────────────────────────────
# Factor 5 — Positioning / Momentum (PAXG on Binance)
# ─────────────────────────────────────────────────────────────────────────────

def get_paxg_positioning(binance_client) -> dict:
    """
    Fetch PAXG/USDT price and volume data from Binance to assess momentum
    and positioning (crowded long = correction risk).
    """
    try:
        klines = binance_client.get_klines(symbol="PAXGUSDT", interval="1d", limit=30)
        if not klines:
            return {"success": False, "error": "No PAXG kline data"}

        closes = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]

        current_price = closes[-1]
        ma7 = sum(closes[-7:]) / 7
        ma20 = sum(closes[-20:]) / 20
        avg_vol_10d = sum(volumes[-10:]) / 10
        latest_vol = volumes[-1]

        # Momentum score
        if current_price > ma7 > ma20:
            momentum = "STRONG_UPTREND"
        elif current_price > ma20:
            momentum = "UPTREND"
        elif current_price < ma7 < ma20:
            momentum = "STRONG_DOWNTREND"
        elif current_price < ma20:
            momentum = "DOWNTREND"
        else:
            momentum = "RANGING"

        # Volume surge = potential crowded positioning
        vol_ratio = latest_vol / avg_vol_10d if avg_vol_10d > 0 else 1.0
        crowded = vol_ratio > 2.5 and momentum in ("STRONG_UPTREND", "UPTREND")

        # Price change
        chg_5d = ((closes[-1] - closes[-6]) / closes[-6]) * 100 if len(closes) >= 6 else 0
        chg_20d = ((closes[-1] - closes[-21]) / closes[-21]) * 100 if len(closes) >= 21 else 0

        return {
            "success": True,
            "price": round(current_price, 2),
            "ma7": round(ma7, 2),
            "ma20": round(ma20, 2),
            "chg_5d_pct": round(chg_5d, 2),
            "chg_20d_pct": round(chg_20d, 2),
            "vol_ratio": round(vol_ratio, 2),
            "momentum": momentum,
            "crowded_long": crowded,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Composite Macro Snapshot
# ─────────────────────────────────────────────────────────────────────────────

def get_full_macro_snapshot(binance_client) -> dict:
    """Fetch all 5 factors and return a unified snapshot dict."""
    return {
        "real_yield": get_real_yield(),
        "usd": get_usd_direction(),
        "liquidity": get_liquidity_regime(),
        "risk_premium": get_risk_premium(),
        "positioning": get_paxg_positioning(binance_client),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
