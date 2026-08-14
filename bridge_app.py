"""Protected HTTP bridge for the PAXG Trader Control mobile app.

Run this service instead of ``main.py`` when the Android dashboard needs live
bot data. It starts the Telegram bot, scheduler, and authenticated dashboard
API in one process so they share the same guarded trading state.
"""

import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel
from telegram.ext import Application, ApplicationBuilder, CommandHandler

from src.binance_client import get_client, get_ticker_price
from src.handlers import balance, buy, cancel, candles, help_command, history, limitbuy, limitsell, openorders, price, sell, start, stats
from src.macro_data import get_full_macro_snapshot
from src.paxg_handlers import autotrade, dry_run, gold_analysis, gold_regime, gold_risks, gold_score, paxg_position, trade_config, trade_history
from src.paxg_trader import SYMBOL, get_portfolio_summary, get_state, set_auto_trade
from src.regime_engine import compute_gold_score
from src.scheduler import start_scheduler

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class AutoTradeControl(BaseModel):
    enabled: bool


def _require_dashboard_key(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = os.getenv("DASHBOARD_ACCESS_KEY", "")
    if not expected:
        logger.error("DASHBOARD_ACCESS_KEY is not configured")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Dashboard bridge is not configured.")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Dashboard authentication required.")
    token = authorization.removeprefix("Bearer ").strip()
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Dashboard authentication failed.")


DashboardAuth = Annotated[None, Depends(_require_dashboard_key)]


def _register_handlers(app: Application) -> None:
    """Register existing bot commands for the long-running bridge process."""
    for command, handler in [
        ("start", start), ("help", help_command), ("price", price), ("stats", stats),
        ("balance", balance), ("buy", buy), ("sell", sell), ("limitbuy", limitbuy),
        ("limitsell", limitsell), ("openorders", openorders), ("cancel", cancel),
        ("history", history), ("candles", candles), ("goldanalysis", gold_analysis),
        ("goldscore", gold_score), ("goldregime", gold_regime), ("paxgposition", paxg_position),
        ("autotrade", autotrade), ("tradeconfig", trade_config), ("dryrun", dry_run),
        ("goldrisks", gold_risks), ("tradehistory", trade_history),
    ]:
        app.add_handler(CommandHandler(command, handler))


def _build_analysis() -> tuple[dict[str, Any], dict[str, Any]]:
    client = get_client()
    snapshot = get_full_macro_snapshot(client)
    score = compute_gold_score(snapshot)
    return snapshot, score


def _macro_payload(score: dict[str, Any]) -> dict[str, Any]:
    factors = [
        {
            "id": key,
            "label": value["note"].split("|")[0].strip(),
            "weight": value["weight"],
            "score": value["score"],
            "detail": value["note"],
        }
        for key, value in score["factors"].items()
    ]
    return {
        "compositeScore": score["composite_score"],
        "signal": score["signal"],
        "regimeCode": score["regime_code"],
        "regimeDescription": score["regime_desc"],
        "factors": factors,
        "riskFlags": score["risk_flags"],
    }


def _status_payload(snapshot: dict[str, Any], score: dict[str, Any]) -> dict[str, Any]:
    state = get_state()
    positioning = snapshot.get("positioning", {})
    ticker = get_ticker_price(get_client(), SYMBOL)
    paxg_price = positioning.get("price") or (float(ticker["price"]) if ticker.get("success") else 0.0)
    return {
        "service": "online",
        "paxgPrice": paxg_price,
        "currency": "USDT",
        "compositeScore": score["composite_score"],
        "signal": score["signal"],
        "regimeCode": score["regime_code"],
        "regimeDescription": score["regime_desc"],
        "autoTradeEnabled": state.get("auto_trade_enabled", False),
        "lastAnalysisAt": snapshot.get("timestamp"),
    }


def _position_payload() -> dict[str, Any]:
    summary = get_portfolio_summary()
    state = get_state()
    events = []
    for index, event in enumerate(state.get("trade_history", [])[-10:][::-1]):
        action = event.get("action", "event").lower()
        qty = event.get("qty")
        detail = event.get("reason") or f"{event.get('action', 'EVENT')} {qty or ''} PAXG"
        events.append({
            "id": f"{event.get('time', 'event')}-{index}",
            "time": event.get("time", ""),
            "type": action,
            "detail": detail.strip(),
        })
    return {
        "quantity": summary["position_qty"],
        "averageEntryPrice": summary["avg_entry_price"],
        "currentPrice": summary["current_price"],
        "currentValue": summary["current_value_usdt"],
        "unrealizedPnl": summary["unrealized_pnl_usdt"],
        "unrealizedPnlPercent": summary["unrealized_pct"],
        "realizedPnl": summary["realized_pnl_usdt"],
        "tradeCount": summary["trade_count"],
        "events": events,
    }


def _envelope(data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "updatedAt": datetime.now(timezone.utc).isoformat(), "data": data}


@asynccontextmanager
async def _lifespan(_: FastAPI):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN must be configured on the server.")

    telegram_app = ApplicationBuilder().token(token).build()
    _register_handlers(telegram_app)
    await telegram_app.initialize()
    await telegram_app.start()
    if telegram_app.updater:
        await telegram_app.updater.start_polling()
    scheduler = start_scheduler(telegram_app.bot)
    logger.info("PAXG bot, scheduler, and protected dashboard bridge are running.")
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        if telegram_app.updater:
            await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()


app = FastAPI(
    title="PAXG Trader Control Bridge",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    lifespan=_lifespan,
)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "paxg-dashboard-bridge"}


@app.get("/v1/status")
async def get_status(_: DashboardAuth) -> dict[str, Any]:
    try:
        snapshot, score = await asyncio.to_thread(_build_analysis)
        return _envelope(_status_payload(snapshot, score))
    except Exception:
        logger.exception("Dashboard status request failed")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Dashboard status is temporarily unavailable.")


@app.get("/v1/macro")
async def get_macro(_: DashboardAuth) -> dict[str, Any]:
    try:
        _, score = await asyncio.to_thread(_build_analysis)
        return _envelope(_macro_payload(score))
    except Exception:
        logger.exception("Dashboard macro request failed")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Macro analysis is temporarily unavailable.")


@app.get("/v1/position")
async def get_position(_: DashboardAuth) -> dict[str, Any]:
    try:
        return _envelope(await asyncio.to_thread(_position_payload))
    except Exception:
        logger.exception("Dashboard position request failed")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Position data is temporarily unavailable.")


@app.get("/v1/history")
async def get_history(_: DashboardAuth) -> dict[str, Any]:
    try:
        return _envelope({"events": (await asyncio.to_thread(_position_payload))["events"]})
    except Exception:
        logger.exception("Dashboard history request failed")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Trade history is temporarily unavailable.")


@app.post("/v1/control/analysis")
async def request_analysis(_: DashboardAuth) -> dict[str, Any]:
    try:
        snapshot, score = await asyncio.to_thread(_build_analysis)
        return _envelope(_status_payload(snapshot, score))
    except Exception:
        logger.exception("Immediate analysis request failed")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Immediate analysis could not be completed.")


@app.post("/v1/control/auto-trade")
async def control_auto_trade(request: AutoTradeControl, _: DashboardAuth) -> dict[str, Any]:
    try:
        await asyncio.to_thread(set_auto_trade, request.enabled)
        snapshot, score = await asyncio.to_thread(_build_analysis)
        return _envelope(_status_payload(snapshot, score))
    except Exception:
        logger.exception("Auto-trade control request failed")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auto-trade state could not be updated.")
