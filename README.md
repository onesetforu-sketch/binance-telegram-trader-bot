# 🤖 Binance Telegram Trader Bot

A private, secure Telegram bot that lets you trade and monitor your Binance
account directly from Telegram — built in Python.

In addition to standard Binance trading commands, the bot ships with a
**PAXG Gold Auto-Trader**: a 5-factor macro engine that continuously scores
gold (PAXG/USDT) against real-yield, USD, liquidity, risk-premium, and
momentum factors and can auto-enter / auto-exit positions on your behalf.

---

## ✨ Features

### Standard Trading Commands

| Command | Description |
|---|---|
| `/start` or `/help` | Show all available commands |
| `/price <SYMBOL>` | Get the latest price of a trading pair |
| `/stats <SYMBOL>` | View 24-hour market statistics |
| `/balance` | View all account balances |
| `/buy <SYMBOL> <QTY>` | Place a market buy order |
| `/sell <SYMBOL> <QTY>` | Place a market sell order |
| `/limitbuy <SYMBOL> <QTY> <PRICE>` | Place a limit buy order |
| `/limitsell <SYMBOL> <QTY> <PRICE>` | Place a limit sell order |
| `/openorders [SYMBOL]` | List all open orders |
| `/cancel <SYMBOL> <ORDER_ID>` | Cancel an open order |
| `/history <SYMBOL>` | View recent order history |
| `/candles <SYMBOL> [INTERVAL]` | View candlestick data |

### PAXG Gold Auto-Trader

A 5-factor macro engine that scores gold (PAXG/USDT) on each scheduled cycle
and can automatically enter/exit positions based on the composite regime score.

| Command | Description |
|---|---|
| `/goldanalysis` | Full 5-factor macro analysis (real yields, USD, liquidity, risk premium, momentum) |
| `/goldscore` | Quick composite gold score and signal |
| `/goldregime` | Current market regime (A / A+ / B / B+ / C / D / MIXED) with guidance |
| `/goldrisks` | Active bearish triggers and structural risk checklist |
| `/paxgposition` | Current PAXG position, realized + unrealized P&L |
| `/autotrade on\|off\|status` | Enable, disable, or inspect auto-trading |
| `/dryrun` | Simulate a trade based on the current macro score (no real order) |
| `/tradeconfig` | Show current risk / sizing configuration |
| `/tradehistory` | Last 10 auto-trade entries with P&L |

A background scheduler also pushes Telegram alerts when the regime or signal
changes, when a new risk flag appears, or when an auto-trade is executed.

---

## 🚀 Setup & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/YOUR_USERNAME/binance-telegram-trader-bot.git
cd binance-telegram-trader-bot
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy the example file and fill in your credentials:
```bash
cp .env.example .env
```

See the full environment variable reference below.

### 4. Get Your Telegram User ID
Message [@userinfobot](https://t.me/userinfobot) on Telegram to get your numeric user ID.

### 5. Get Binance API Keys
1. Log in to [Binance](https://www.binance.com)
2. Go to **Account → API Management**
3. Create a new API key with **Spot Trading** permissions
4. For testing, use the [Binance Testnet](https://testnet.binance.vision/)

### 6. Run the Bot
```bash
python main.py
```

On startup the bot prints a banner with the active mode (Testnet vs. Live
Mainnet), the scheduler interval, and whether `TELEGRAM_ALLOWED_USER_ID` is
set — check this output before sending commands.

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — (required) | Token from [@BotFather](https://t.me/BotFather). |
| `TELEGRAM_ALLOWED_USER_ID` | `0` (open) | Your numeric Telegram user ID. **Leave unset only for local testing** — if empty, anyone can invoke commands. |
| `BINANCE_API_KEY` | — (required) | Binance Spot API key. |
| `BINANCE_API_SECRET` | — (required) | Binance Spot API secret. |
| `USE_TESTNET` | `True` | `True` = Binance Testnet (paper). `False` = live mainnet with real funds. |
| `PAXG_TRADE_BUDGET_USDT` | `100` | Max USDT budget per auto-trade cycle. |
| `PAXG_STOP_LOSS_PCT` | `3.0` | Stop-loss percentage from average entry price. |
| `PAXG_MAX_DRAWDOWN_PCT` | `8.0` | Max portfolio drawdown (from peak) before new buys are blocked. |
| `PAXG_COOLDOWN_HOURS` | `4.0` | Minimum hours between consecutive auto-trades. |
| `PAXG_MIN_SCORE_DELTA` | `15.0` | Composite-score delta required to trigger a new trade. |
| `ANALYSIS_INTERVAL_MINUTES` | `60` | How often the background macro analysis runs. |
| `PAXG_STATE_FILE` | `./data/paxg_state.json` | Where position / P&L history is persisted. **Set this to a persistent volume in production** — `/tmp` is wiped on reboot on most hosts. |
| `LOG_LEVEL` | `INFO` | Python log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

> ⚠ **Never commit your `.env` file.** It is already in `.gitignore`.

---

## 🛡 Security

- The bot is **restricted to a single Telegram user** via `TELEGRAM_ALLOWED_USER_ID`. Any other user will be denied access, and the attempt is logged.
- Always start with `USE_TESTNET=True` to validate your setup without risking real funds. Flipping to mainnet triggers additional warnings in `/autotrade on` and `/tradeconfig`.
- Never share your `.env` file or API keys.

---

## ☁️ Deployment (Keep Bot Running 24/7)

### Option A: Railway (free tier)
1. Push this repo to GitHub.
2. Go to [railway.app](https://railway.app) and create a new project from your GitHub repo.
3. Add all environment variables from `.env` in the Railway dashboard.
4. Set the start command to: `python main.py`
5. Attach a volume at `/app/data` (or similar) and set `PAXG_STATE_FILE=/app/data/paxg_state.json` so position state survives redeploys.

### Option B: Render
1. Push to GitHub.
2. Create a new **Background Worker** on [render.com](https://render.com).
3. Set build command: `pip install -r requirements.txt`
4. Set start command: `python main.py`
5. Add environment variables in the Render dashboard. Point `PAXG_STATE_FILE` at a persistent disk.

### Option C: VPS (e.g., DigitalOcean, Linode)
```bash
# Run under systemd or screen — /tmp is often wiped, so keep PAXG_STATE_FILE
# under a persistent path like /var/lib/trader-bot/state.json.
screen -S traderbot
python main.py
# Press Ctrl+A then D to detach
```

---

## 📁 Project Structure

```
binance-telegram-trader-bot/
├── main.py                  # Bot entry point + startup banner + error handler
├── src/
│   ├── __init__.py
│   ├── auth.py              # Shared @restricted + safe-reply helpers
│   ├── binance_client.py    # Binance API wrapper (all success/error dicts)
│   ├── handlers.py          # Standard Binance Telegram command handlers
│   ├── macro_data.py        # Factor data fetchers (Yahoo Finance + Binance)
│   ├── regime_engine.py     # 5-factor composite scoring / regime classifier
│   ├── paxg_trader.py       # Auto-trade execution, state, risk gates
│   ├── paxg_handlers.py     # PAXG Telegram command handlers
│   └── scheduler.py         # APScheduler macro-analysis cycle + alerts
├── data/                    # (created at runtime) persisted PAXG state
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## ⚠️ Disclaimer

This bot is for **educational and personal use only**. Cryptocurrency trading
carries significant financial risk. Always test with the Binance Testnet
before using real funds. The author is not responsible for any financial
losses.

---

*Built with [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) and [python-binance](https://github.com/sammchardy/python-binance)*
