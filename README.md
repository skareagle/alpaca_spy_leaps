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

To start the trading bot, run the main Python script:

```bash
python leaps_spy.py
```

The bot will print its status to the console, checking the market and evaluating positions every 6 minutes while the market is open. Make sure to keep the script running on a server or a machine that stays on during market hours.

## Disclaimer

**This software is for educational and informational purposes only. Do not use this code to trade real money without understanding the risks.** Options trading involves significant risk and is not suitable for all investors. You are solely responsible for any trades executed by this software.
