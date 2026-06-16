# 🤖 Binance Telegram Trader Bot

A private, secure Telegram bot that lets you trade and monitor your Binance
account directly from Telegram — built in Python.

Ships with a rule-based **Price-Action (PA) Strategy** for PAXG/USDT (gold)
that marks key liquidity levels, computes session VWAP, confirms breakouts
with volume, and pushes Telegram alerts when a fresh LONG / SHORT setup
appears. Alerts only — no orders are placed from the strategy.

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

### PAXG Price-Action Strategy

A simple, rule-based intraday strategy for **PAXGUSDT**:

1. **Key levels** are marked before every check:
   - Yesterday High / Low (prior UTC day)
   - Asian session High / Low (00:00–09:00 UTC)
   - Round-number levels every $25 around the current price
2. **Session VWAP** is anchored at 00:00 UTC and computed from 15-minute klines.
   - Price **above** VWAP → LONG bias.
   - Price **below** VWAP → SHORT bias.
3. **Volume confirmation**: last closed 15m candle volume must be ≥ **1.5×** the 20-bar average.
4. **Candle confirmation**: the last closed 15m candle must close in the direction of the breakout.
5. **Session filter**: only trades during **London (07-16 UTC)** or **US (12-21 UTC)** sessions.

Risk-reward target is **1:2**; stop-loss is placed just beyond the broken
level / swing; take-profit uses the next opposing key level or a 2× risk
projection, whichever is further.

| Command | Description |
|---|---|
| `/palevels` | Today's key levels: Yesterday H/L, Asia H/L, round levels, session VWAP |
| `/pasignal` | Current bias (LONG / SHORT / NO_SETUP) with the full rule checklist |
| `/pastrategy on\|off\|status` | Toggle background alert broadcasting |

The background scheduler runs every `ANALYSIS_INTERVAL_MINUTES` minutes
(default: **15**, matching the signal timeframe). When `/pastrategy on` is
set, a fresh LONG / SHORT setup (new bias or newly broken level) triggers a
Telegram alert with entry, stop-loss, take-profit, and the full checklist.

> Note: market data comes from Binance's **public klines endpoint** — no
> API key is required for the strategy itself. API keys are only needed
> for manual `/buy`, `/sell`, `/balance` commands.

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

### 5. Get Binance API Keys (optional for PA strategy)
1. Log in to [Binance](https://www.binance.com)
2. Go to **Account → API Management**
3. Create a new API key with **Spot Trading** permissions
4. For testing, use the [Binance Testnet](https://testnet.binance.vision/)

The PA strategy uses Binance's public market-data endpoints and needs no
API key. Keys are only required for the manual trading commands.

### 6. Run the Bot
```bash
python main.py
```

On startup the bot prints a banner with the active mode (Testnet vs. Live
Mainnet), the scheduler interval, and whether `TELEGRAM_ALLOWED_USER_ID` is
set — check this output before sending commands.

### 7. Enable alerts
From Telegram:
```
/pastrategy on
```
You'll get a Telegram message each time a fresh LONG / SHORT setup appears.

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — (required) | Token from [@BotFather](https://t.me/BotFather). |
| `TELEGRAM_ALLOWED_USER_ID` | `0` (open) | Your numeric Telegram user ID. **Leave unset only for local testing** — if empty, anyone can invoke commands. |
| `BINANCE_API_KEY` | — | Binance Spot API key. Only required for manual `/buy`, `/sell`, `/balance`. |
| `BINANCE_API_SECRET` | — | Binance Spot API secret. |
| `USE_TESTNET` | `True` | `True` = Binance Testnet (paper). `False` = live mainnet with real funds. PA strategy always reads market data from mainnet. |
| `PA_SYMBOL` | `PAXGUSDT` | Symbol analysed by the PA strategy. |
| `PA_ROUND_STEP` | `25` | Round-number level spacing in USD. |
| `PA_VOLUME_SPIKE_MULT` | `1.5` | Breakout volume must be ≥ this × 20-bar average. |
| `PA_RR_RATIO` | `2.0` | Minimum risk-reward ratio on auto-generated TPs. |
| `PA_RISK_PCT` | `1.0` | Account risk per trade (informational — auto-execute not yet implemented). |
| `ANALYSIS_INTERVAL_MINUTES` | `15` | How often the background analysis runs. |
| `PA_STATE_FILE` | `./data/pa_state.json` | Where alert state (enabled flag, last bias / level) is persisted. **Point at a persistent volume in production** — `/tmp` is wiped on reboot. |
| `LOG_LEVEL` | `INFO` | Python log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

> ⚠ **Never commit your `.env` file.** It is already in `.gitignore`.

---

## 🛡 Security

- The bot is **restricted to a single Telegram user** via `TELEGRAM_ALLOWED_USER_ID`. Any other user will be denied access, and the attempt is logged.
- Always start with `USE_TESTNET=True` to validate your setup without risking real funds.
- The PA strategy is **alert-only** — it never places orders on your behalf.
- Manual `/buy`, `/sell`, `/limitbuy`, `/limitsell` commands reject non-positive
  quantities / prices before sending anything to Binance.
- Never share your `.env` file or API keys.

---

## ☁️ Deployment (Keep Bot Running 24/7)

### Option A: Railway (free tier)
1. Push this repo to GitHub.
2. Go to [railway.app](https://railway.app) and create a new project from your GitHub repo.
3. Add all environment variables from `.env` in the Railway dashboard.
4. Set the start command to: `python main.py`
5. Attach a volume at `/app/data` (or similar) and set `PA_STATE_FILE=/app/data/pa_state.json` so alert state survives redeploys.

### Option B: Render
1. Push to GitHub.
2. Create a new **Background Worker** on [render.com](https://render.com).
3. Set build command: `pip install -r requirements.txt`
4. Set start command: `python main.py`
5. Add environment variables in the Render dashboard. Point `PA_STATE_FILE` at a persistent disk.

### Option C: VPS (e.g., DigitalOcean, Linode)
```bash
# Run under systemd or screen — /tmp is often wiped, so keep PA_STATE_FILE
# under a persistent path like /var/lib/trader-bot/pa_state.json.
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
│   ├── pa_strategy.py       # Price-action engine (key levels, VWAP, signals)
│   ├── pa_handlers.py       # PA Telegram command handlers
│   └── scheduler.py         # APScheduler periodic analysis + alerts
├── data/                    # (created at runtime) persisted PA state
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

The previous `macro_data.py`, `regime_engine.py`, `paxg_trader.py`, and
`paxg_handlers.py` modules from the PAXG macro engine are no longer wired
into `main.py`; the bot now runs the PA strategy exclusively.

---

## ⚠️ Disclaimer

This bot is for **educational and personal use only**. Cryptocurrency trading
carries significant financial risk. Always test with the Binance Testnet
before using real funds. The author is not responsible for any financial
losses.

---

*Built with [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) and [python-binance](https://github.com/sammchardy/python-binance)*
