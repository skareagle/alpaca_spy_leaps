# Alpaca SPY LEAPS Trading Strategy

This project contains a Python script (`leaps_spy.py`) that automates a LEAPS (Long-Term Equity Anticipation Securities) trading strategy for the SPDR S&P 500 ETF Trust (SPY) using the [Alpaca Trading API](https://alpaca.markets/). 

The bot runs continuously, executing weekly trades, managing active positions based on specific profit targets and holding periods, and sending notifications via a Telegram bot.

## Strategy Overview

The core strategy implemented by the bot is as follows:

1. **Weekly Purchases**: Once a week, the bot buys 1 contract of the furthest available at-the-money (ATM) call option for SPY, looking at least 180 days (approx. 6 months) into the future.
2. **Profit Taking**: The bot continuously monitors open LEAPS positions. If any position reaches a profit of **+170%**, the bot automatically sells the position to lock in the gains.
3. **Time Stop (Long Term Capital Gains)**: If a position is held for more than **366 days**, the bot will automatically close the position. Holding for over a year ensures that any profits are treated as long-term capital gains for tax purposes in the US.
4. **Monitoring**: The script checks the market and evaluates the strategy every 6 minutes while the market is open.

## Features

- **Automated Trading**: Fully automated order placement for options through the Alpaca API.
- **State Management**: Keeps track of purchase dates and the last time it bought/summarized using a local `leaps_state.json` file.
- **Telegram Notifications**: Sends real-time alerts when trades are executed and provides a weekly summary of open positions and their current PnL on Fridays.
- **Paper Trading Support**: Easily toggle between paper and live trading environments.

## Prerequisites

- Python 3.7+
- An [Alpaca Account](https://app.alpaca.markets/signup) with Options trading enabled.
- API Key and Secret Key from Alpaca.
- (Optional) A Telegram Bot Token and Chat ID for notifications.

## Installation

1. Clone or download this repository.
2. Create a virtual environment (optional but recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```
3. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

Create a `.env` file in the root directory of the project and populate it with your Alpaca and Telegram credentials:

```env
# Alpaca Configuration
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_SECRET_KEY=your_alpaca_secret_key
ALPACA_PAPER_TRADE=true  # Set to "false" to trade with real money

# Telegram Notifications (Optional)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
```

## Usage

To start the trading bot, run the launcher from anywhere:

```bash
./run.sh
```

`run.sh` changes to the repository root and runs `leaps_spy.py` with the `venv/` Python, so the virtual environment must exist at `venv/` (see Installation). You can also run `python leaps_spy.py` from the repository root with the venv activated.

The bot will print its status to the console, checking the market and evaluating positions every 6 minutes while the market is open. Make sure to keep the script running on a server or a machine that stays on during market hours.

## Run on startup

On Linux, `deploy/leaps-spy.service` is a systemd *user* unit that runs `run.sh`, restarts it 30 seconds after it exits, and logs to the journal.

> **Warning:** two running instances can double-buy. Stop any manually started bot first (`pgrep -af leaps_spy`).

Install and enable it:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/leaps-spy.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable leaps-spy     # start on next boot
systemctl --user start leaps-spy      # start now (only if no manual instance)
loginctl enable-linger "$USER"        # start at boot without logging in
```

Manage it:

```bash
systemctl --user status leaps-spy
systemctl --user stop leaps-spy
systemctl --user disable leaps-spy    # don't start on boot
journalctl --user -u leaps-spy -f     # follow logs
```

The unit contains absolute paths to this repository; if you move the repo, update `WorkingDirectory` and `ExecStart` in the copied unit and run `systemctl --user daemon-reload`. The service does not wait for the network at boot. A bot that starts offline does not exit: it keeps retrying on its own (Telegram polling every few seconds, Alpaca every 10 minutes), though its startup Telegram message may be lost; `Restart=always` only covers a crash. Also, Telegram commands sent while the bot was offline (including `/buy`) may be executed once the network comes up.

## Disclaimer

**This software is for educational and informational purposes only. Do not use this code to trade real money without understanding the risks.** Options trading involves significant risk and is not suitable for all investors. You are solely responsible for any trades executed by this software.
