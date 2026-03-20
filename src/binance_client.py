"""
Binance API client wrapper for the Telegram Trader Bot.
Handles all interactions with the Binance REST API.
"""

import os
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceOrderException
from dotenv import load_dotenv

load_dotenv()


def get_client() -> Client:
    """Initialize and return the Binance API client."""
    api_key = os.getenv("BINANCE_API_KEY", "")
    api_secret = os.getenv("BINANCE_API_SECRET", "")
    use_testnet = os.getenv("USE_TESTNET", "True").lower() == "true"

    client = Client(api_key, api_secret, testnet=use_testnet)
    return client


def get_account_balance(client: Client) -> dict:
    """Fetch all non-zero asset balances from the account."""
    try:
        account = client.get_account()
        balances = [
            b for b in account["balances"]
            if float(b["free"]) > 0 or float(b["locked"]) > 0
        ]
        return {"success": True, "balances": balances}
    except BinanceAPIException as e:
        return {"success": False, "error": str(e)}


def get_ticker_price(client: Client, symbol: str) -> dict:
    """Get the latest price for a trading pair symbol."""
    try:
        ticker = client.get_symbol_ticker(symbol=symbol.upper())
        return {"success": True, "symbol": ticker["symbol"], "price": ticker["price"]}
    except BinanceAPIException as e:
        return {"success": False, "error": str(e)}


def get_24h_stats(client: Client, symbol: str) -> dict:
    """Get 24-hour price change statistics for a symbol."""
    try:
        stats = client.get_ticker(symbol=symbol.upper())
        return {
            "success": True,
            "symbol": stats["symbol"],
            "price_change": stats["priceChange"],
            "price_change_pct": stats["priceChangePercent"],
            "high": stats["highPrice"],
            "low": stats["lowPrice"],
            "volume": stats["volume"],
            "last_price": stats["lastPrice"],
        }
    except BinanceAPIException as e:
        return {"success": False, "error": str(e)}


def place_market_order(client: Client, symbol: str, side: str, quantity: float) -> dict:
    """Place a market buy or sell order."""
    try:
        order = client.order_market(
            symbol=symbol.upper(),
            side=side.upper(),
            quantity=quantity,
        )
        return {"success": True, "order": order}
    except (BinanceAPIException, BinanceOrderException) as e:
        return {"success": False, "error": str(e)}


def place_limit_order(client: Client, symbol: str, side: str, quantity: float, price: float) -> dict:
    """Place a limit buy or sell order."""
    try:
        order = client.order_limit(
            symbol=symbol.upper(),
            side=side.upper(),
            quantity=quantity,
            price=str(price),
            timeInForce=Client.TIME_IN_FORCE_GTC,
        )
        return {"success": True, "order": order}
    except (BinanceAPIException, BinanceOrderException) as e:
        return {"success": False, "error": str(e)}


def get_open_orders(client: Client, symbol: str = None) -> dict:
    """Get all open orders, optionally filtered by symbol."""
    try:
        if symbol:
            orders = client.get_open_orders(symbol=symbol.upper())
        else:
            orders = client.get_open_orders()
        return {"success": True, "orders": orders}
    except BinanceAPIException as e:
        return {"success": False, "error": str(e)}


def cancel_order(client: Client, symbol: str, order_id: int) -> dict:
    """Cancel an open order by symbol and order ID."""
    try:
        result = client.cancel_order(symbol=symbol.upper(), orderId=order_id)
        return {"success": True, "result": result}
    except BinanceAPIException as e:
        return {"success": False, "error": str(e)}


def get_order_history(client: Client, symbol: str, limit: int = 10) -> dict:
    """Fetch recent order history for a given symbol."""
    try:
        orders = client.get_all_orders(symbol=symbol.upper(), limit=limit)
        return {"success": True, "orders": orders}
    except BinanceAPIException as e:
        return {"success": False, "error": str(e)}


def get_klines(client: Client, symbol: str, interval: str = "1h", limit: int = 10) -> dict:
    """Fetch candlestick/kline data for a symbol."""
    try:
        klines = client.get_klines(symbol=symbol.upper(), interval=interval, limit=limit)
        formatted = []
        for k in klines:
            formatted.append({
                "open_time": k[0],
                "open": k[1],
                "high": k[2],
                "low": k[3],
                "close": k[4],
                "volume": k[5],
            })
        return {"success": True, "klines": formatted}
    except BinanceAPIException as e:
        return {"success": False, "error": str(e)}
