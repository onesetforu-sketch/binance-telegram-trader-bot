# 🤖 Binance Telegram Trader Bot

A private, secure Telegram bot that lets you trade and monitor your Binance account directly from Telegram — built in Python.

---

## ✨ Features

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

Edit `.env` with your values:
```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_ALLOWED_USER_ID=your_telegram_user_id
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret
USE_TESTNET=True   # Set to False for live trading
```

> ⚠️ **Never commit your `.env` file.** It is already in `.gitignore`.

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

---

## 📱 PAXG Trader Control Android Dashboard

The mobile dashboard connects through a **protected bridge service**. It never stores `BINANCE_API_KEY`, `BINANCE_API_SECRET`, or `TELEGRAM_BOT_TOKEN` in the APK. Configure those values only in your deployment host’s environment variables.

To run the Telegram bot, scheduler, and authenticated mobile bridge together, deploy this command instead of `python main.py`:

```bash
uvicorn bridge_app:app --host 0.0.0.0 --port ${PORT:-8000}
```

In addition to the existing bot variables, set a new long and random `DASHBOARD_ACCESS_KEY`. Enter the deployment’s HTTPS URL and this **separate dashboard key** in the PAXG Trader Control app’s Secure Connection screen. Do not enter Binance or Telegram credentials in the mobile app.

For persistent P&L and trade history, mount a server volume and set `PAXG_STATE_FILE=/data/paxg_state.json`. The `health` route is public for host health checks; every `/v1/*` dashboard route requires `Authorization: Bearer <DASHBOARD_ACCESS_KEY>`.

---

## 🛡️ Security

- The bot is **restricted to a single Telegram user** via `TELEGRAM_ALLOWED_USER_ID`. Any other user will be denied access.
- Always start with `USE_TESTNET=True` to test without risking real funds.
- Never share your `.env` file or API keys.

---

## ☁️ Deployment (Keep Bot Running 24/7)

### Option A: Railway (Recommended — Free Tier)
1. Push this repo to GitHub.
2. Go to [railway.app](https://railway.app) and create a new project from your GitHub repo.
3. Add all environment variables from `.env` in the Railway dashboard.
4. Set the start command to: `python main.py`

### Option B: Render
1. Push to GitHub.
2. Create a new **Background Worker** on [render.com](https://render.com).
3. Set build command: `pip install -r requirements.txt`
4. Set start command: `python main.py`
5. Add environment variables in the Render dashboard.

### Option C: VPS (e.g., DigitalOcean, Linode)
```bash
# Install dependencies and run with screen or systemd
screen -S traderbot
python main.py
# Press Ctrl+A then D to detach
```

---

## 📁 Project Structure

```
binance-telegram-trader-bot/
├── main.py              # Bot entry point
├── src/
│   ├── __init__.py
│   ├── binance_client.py  # Binance API wrapper
│   └── handlers.py        # Telegram command handlers
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## ⚠️ Disclaimer

This bot is for **educational and personal use only**. Cryptocurrency trading carries significant financial risk. Always test with the Binance Testnet before using real funds. The author is not responsible for any financial losses.

---

*Built with [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) and [python-binance](https://github.com/sammchardy/python-binance)*
