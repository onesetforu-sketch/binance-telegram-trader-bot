"""
Integration smoke-test for the PA strategy.

Runs the full pipeline end-to-end (compute_key_levels → compute_signal →
format_signal_message → is_new_signal → state save/load) against a
deterministic mock Binance client. Does NOT hit the network, does NOT
require API keys, and does NOT require any environment variables.

Run with:  python tests/test_pa_integration.py
(or use pytest: pytest tests/ -v)
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone


FAILURES: list[str] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


# ─────────────────────────────────────────────────────────────────────────────
# Mock Binance client
# ─────────────────────────────────────────────────────────────────────────────

class MockClient:
    """Deterministic klines/ticker data for PA tests."""

    def __init__(
        self,
        price: float = 2352.0,
        breakout: bool = True,
        volume_spike: bool = True,
        bullish_close: bool = True,
    ) -> None:
        self.price = price
        self.breakout = breakout
        self.volume_spike = volume_spike
        self.bullish_close = bullish_close

    def get_symbol_ticker(self, symbol: str) -> dict:
        return {"symbol": symbol, "price": str(self.price)}

    def get_klines(self, symbol: str, interval: str, limit: int) -> list:
        now = datetime.now(timezone.utc)
        if interval == "1d":
            out = []
            base = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
            for i in range(3):
                ts_ms = (base - (2 - i) * 86400) * 1000
                out.append([ts_ms, "2320", "2345", "2310", "2340", "1500", ts_ms + 86399000])
            return out

        if interval == "1h":
            out = []
            for h_offset in range(47, -1, -1):
                dt = now - timedelta(hours=h_offset)
                ts_ms = int(dt.replace(minute=0, second=0, microsecond=0).timestamp() * 1000)
                out.append([ts_ms, "2330", "2342", "2320", "2335", "50"])
            return out

        if interval == "15m":
            out = []
            for i in range(30):
                dt = now - timedelta(minutes=(29 - i) * 15)
                ts_ms = int(dt.replace(second=0, microsecond=0).timestamp() * 1000)
                o, h, l, c, v = 2342, 2348, 2340, 2345, 100
                if i == 28:  # last closed candle — the breakout candle
                    if self.breakout:
                        o, h, l, c = 2346, 2360, 2344, 2358 if self.bullish_close else 2347
                    else:
                        o, h, l, c = 2346, 2349, 2344, 2347
                    v = 500 if self.volume_spike else 80
                if i == 27:  # prev closed — below the level we'll break
                    o, h, l, c, v = 2342, 2348, 2340, 2346, 100
                if i == 29:  # in-progress
                    o, h, l, c, v = 2358, 2360, 2355, 2357, 120
                out.append([ts_ms, str(o), str(h), str(l), str(c), str(v)])
            return out

        return []


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_round_levels_around(pa):
    print("\n[round_levels_around]")
    levels = pa.round_levels_around(2352.0, 25.0, 3)
    _check("7 levels returned", len(levels) == 7)
    _check("contains 2350", 2350.0 in levels)
    _check("contains 2325", 2325.0 in levels)
    _check("step=0 returns empty list", pa.round_levels_around(2352.0, 0, 3) == [])


def test_compute_key_levels(pa):
    print("\n[compute_key_levels]")
    lv = pa.compute_key_levels(MockClient())
    _check("current_price present", lv.current_price == 2352.0)
    _check("yesterday_high = 2345", lv.yesterday_high == 2345.0)
    _check("yesterday_low  = 2310", lv.yesterday_low == 2310.0)
    _check("round_levels non-empty", bool(lv.round_levels))
    _check("VWAP positive", lv.session_vwap is not None and lv.session_vwap > 0)
    _check("timestamp is ISO", "T" in lv.timestamp)


def test_signal_long_breakout(pa):
    print("\n[compute_signal: LONG setup w/ breakout + volume + bullish close]")
    pa.active_session = lambda *a, **kw: (True, "LONDON")
    signal = pa.compute_signal(MockClient(price=2352.0, breakout=True, volume_spike=True, bullish_close=True))
    _check("bias == LONG", signal.get("bias") == "LONG", f"got {signal.get('bias')}")
    _check("broken_level == 2350", signal.get("broken_level") == 2350.0)
    _check("SL < entry", signal.get("stop_loss", 0) < signal.get("entry", 0))
    _check("TP > entry", signal.get("take_profit", 0) > signal.get("entry", 0))
    _check("RR >= 2.0", (signal.get("rr") or 0) >= 2.0)
    _check("checklist.breakout set", bool(signal.get("checklist", {}).get("breakout")))
    _check("checklist.volume_confirm True", signal["checklist"]["volume_confirm"] is True)


def test_signal_no_volume(pa):
    print("\n[compute_signal: breakout but volume too low]")
    pa.active_session = lambda *a, **kw: (True, "LONDON")
    signal = pa.compute_signal(MockClient(price=2352.0, breakout=True, volume_spike=False, bullish_close=True))
    _check("bias == NO_SETUP", signal.get("bias") == "NO_SETUP", f"got {signal.get('bias')}")
    _check("reason mentions volume", "volume" in signal.get("reason", "").lower())


def test_signal_off_hours(pa):
    print("\n[compute_signal: off-hours rejects outright]")
    pa.active_session = lambda *a, **kw: (False, "ASIAN")
    signal = pa.compute_signal(MockClient())
    _check("bias == NO_SETUP", signal.get("bias") == "NO_SETUP")
    _check("session == ASIAN", signal.get("session") == "ASIAN")
    _check("reason mentions off-hours", "off-hours" in signal.get("reason", "").lower())


def test_signal_geometry_invalidation(pa):
    print("\n[compute_signal: price pulled back below broken level → invalidated]")
    pa.active_session = lambda *a, **kw: (True, "LONDON")
    signal = pa.compute_signal(MockClient(price=2348.0, breakout=True, volume_spike=True, bullish_close=True))
    _check("bias == NO_SETUP (invalidated)", signal.get("bias") == "NO_SETUP", f"got {signal.get('bias')}")


def test_format_signal_message(pa, ph):
    print("\n[format_signal_message: LONG output]")
    pa.active_session = lambda *a, **kw: (True, "LONDON")
    signal = pa.compute_signal(MockClient(price=2352.0))
    text = ph.format_signal_message(signal)
    _check("contains 'PA LONG SETUP'", "PA LONG SETUP" in text)
    _check("contains Entry", "Entry:" in text)
    _check("contains Stop-Loss", "Stop-Loss" in text)
    _check("mentions alert-only", "Alert-only" in text)

    print("\n[format_signal_message: NO_SETUP output]")
    pa.active_session = lambda *a, **kw: (False, "ASIAN")
    signal = pa.compute_signal(MockClient())
    text = ph.format_signal_message(signal)
    _check("contains 'NO SETUP'", "NO SETUP" in text)


def test_state_roundtrip(pa):
    print("\n[state: save/load roundtrip + is_new_signal]")
    from pathlib import Path
    tmp_dir = Path(tempfile.mkdtemp())
    tmp = tmp_dir / "pa_state.json"
    pa.PA_STATE_FILE = tmp

    pa.save_pa_state({"alerts_enabled": True, "last_signal_bias": "LONG",
                      "last_signal_broken_level": 2350.0, "last_alert_time": None,
                      "signals_seen": 1,
                      "last_error_message": None, "last_error_time": None})
    loaded = pa.load_pa_state()
    _check("alerts_enabled persisted", loaded["alerts_enabled"] is True)
    _check("last_signal_bias persisted", loaded["last_signal_bias"] == "LONG")

    same = {"bias": "LONG", "broken_level": 2350.0}
    _check("is_new_signal False for same", pa.is_new_signal(same, loaded) is False)
    diff = {"bias": "LONG", "broken_level": 2375.0}
    _check("is_new_signal True for new level", pa.is_new_signal(diff, loaded) is True)
    none = {"bias": "NO_SETUP", "broken_level": None}
    _check("is_new_signal False for NO_SETUP", pa.is_new_signal(none, loaded) is False)

    pa.set_alerts_enabled(False)
    _check("set_alerts_enabled persists", pa.load_pa_state()["alerts_enabled"] is False)

    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_module_wiring(pa, ph):
    print("\n[module wiring]")
    _check("pa_handlers exposes pa_levels_command", callable(getattr(ph, "pa_levels_command", None)))
    _check("pa_handlers exposes pa_signal_command", callable(getattr(ph, "pa_signal_command", None)))
    _check("pa_handlers exposes pa_strategy_command", callable(getattr(ph, "pa_strategy_command", None)))
    _check("pa_handlers SYMBOL matches pa_strategy.SYMBOL", ph.SYMBOL == pa.SYMBOL)
    _check("pa_handlers ROUND_STEP matches", ph.ROUND_STEP == pa.ROUND_STEP)

    import src.scheduler as sch
    _check("scheduler.format_signal_message", hasattr(sch, "format_signal_message"))
    _check("scheduler.compute_signal", hasattr(sch, "compute_signal"))
    _check("scheduler.ANALYSIS_INTERVAL_MINUTES > 0", sch.ANALYSIS_INTERVAL_MINUTES > 0)

    import main as m
    _check("main imports pa_levels_command", hasattr(m, "pa_levels_command"))
    _check("main imports start_scheduler", hasattr(m, "start_scheduler"))


def main() -> int:
    os.environ.pop("PA_STATE_FILE", None)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import src.pa_strategy as pa
    import src.pa_handlers as ph

    test_round_levels_around(pa)
    test_compute_key_levels(pa)
    test_signal_long_breakout(pa)
    test_signal_no_volume(pa)
    test_signal_off_hours(pa)
    test_signal_geometry_invalidation(pa)
    test_format_signal_message(pa, ph)
    test_state_roundtrip(pa)
    test_module_wiring(pa, ph)

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} failure(s): {FAILURES}")
        return 1
    print("OK: All integration smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
