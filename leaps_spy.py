import os
import time
import datetime
import json
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOptionContractsRequest
from alpaca.trading.enums import OrderSide, TimeInForce, AssetClass
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from dotenv import load_dotenv
import requests

load_dotenv()

API_KEY = os.environ.get("ALPACA_API_KEY", "your_api_key_here")
SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "your_secret_key_here")
PAPER = os.environ.get("ALPACA_PAPER_TRADE", "true").lower() == "true"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# We only init clients if API key is provided, to avoid crash on empty
if API_KEY and API_KEY != "your_new_api_key_here":
    trading_client = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)
    stock_data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
else:
    trading_client = None
    stock_data_client = None

SYMBOL = "SPY"
STATE_FILE = "leaps_state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {
        "last_buy_week": None,
        "last_summary_week": None,
        "positions_buy_dates": {} # { "symbol": "YYYY-MM-DD" }
    }

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

def get_current_price(symbol):
    request = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
    quote = stock_data_client.get_stock_latest_quote(request)
    return quote[symbol].ask_price

def get_furthest_atm_call(symbol, current_price):
    future_date = datetime.date.today() + datetime.timedelta(days=180) # Look at least 6 months out
    req = GetOptionContractsRequest(
        underlying_symbols=[symbol],
        status="active",
        type="call",
        expiration_date_gte=future_date.strftime('%Y-%m-%d'),
        limit=10000
    )
    
    contracts = trading_client.get_option_contracts(req)
    if not contracts or not contracts.option_contracts:
        return None

    available_dates = sorted(list(set(c.expiration_date for c in contracts.option_contracts)))
    if not available_dates:
        return None
    
    furthest_date = available_dates[-1]
    
    best_contract = None
    min_diff = float('inf')
    for contract in contracts.option_contracts:
        if contract.expiration_date == furthest_date:
            diff = abs(float(contract.strike_price) - current_price)
            if diff < min_diff:
                min_diff = diff
                best_contract = contract

    return best_contract

def place_order(symbol, qty, side, reason=""):
    req = MarketOrderRequest(
        symbol=symbol,
        qty=abs(qty),
        side=side,
        time_in_force=TimeInForce.DAY
    )
    res = trading_client.submit_order(order_data=req)
    msg = f"🟢 <b>TRADE EXECUTED</b>\nSide: {side.name}\nQty: {abs(qty)}\nSymbol: {symbol}\nReason: {reason}\nOrder ID: {res.id}"
    print(msg.replace('<b>', '').replace('</b>', ''))
    send_telegram_message(msg)
    return res

def check_leaps_strategy():
    state = load_state()
    today = datetime.date.today()
    current_week = f"{today.year}-W{today.isocalendar()[1]}"
    
    positions = trading_client.get_all_positions()
    open_leaps = []
    
    for pos in positions:
        if pos.asset_class == AssetClass.US_OPTION and pos.symbol.startswith(SYMBOL) and int(pos.qty) > 0:
            open_leaps.append(pos)
            
    for pos in open_leaps:
        avg_entry = float(pos.avg_entry_price)
        current_value = float(pos.current_price)
        
        if avg_entry > 0:
            profit_pct = (current_value - avg_entry) / avg_entry
        else:
            profit_pct = 0
            
        if profit_pct >= 1.70:
            msg = f"Closing position {pos.symbol} for +170% profit. (Current PnL: {profit_pct*100:.2f}%)"
            print(msg)
            place_order(pos.symbol, int(pos.qty), OrderSide.SELL, "Hit +170% Target")
            continue
            
        buy_date_str = state["positions_buy_dates"].get(pos.symbol)
        if buy_date_str:
            buy_date = datetime.datetime.strptime(buy_date_str, "%Y-%m-%d").date()
            if (today - buy_date).days >= 366:
                msg = f"Closing position {pos.symbol} because it is older than 366 days."
                print(msg)
                place_order(pos.symbol, int(pos.qty), OrderSide.SELL, "Position >= 366 days old")
                continue

    if current_week != state["last_buy_week"]:
        current_price = get_current_price(SYMBOL)
        print(f"New week {current_week} detected. Current {SYMBOL} price: {current_price}")
        
        contract = get_furthest_atm_call(SYMBOL, current_price)
        if contract:
            place_order(contract.symbol, 1, OrderSide.BUY, f"Weekly LEAPS purchase. Furthest ATM call.")
            state["last_buy_week"] = current_week
            state["positions_buy_dates"][contract.symbol] = today.strftime("%Y-%m-%d")
            save_state(state)
        else:
            print("Failed to find suitable contract to buy.")

def send_weekly_summary():
    state = load_state()
    today = datetime.date.today()
    current_week = f"{today.year}-W{today.isocalendar()[1]}"
    
    if current_week == state["last_summary_week"]:
        return # Already sent this week

    positions = trading_client.get_all_positions()
    open_leaps = []
    
    for pos in positions:
        if pos.asset_class == AssetClass.US_OPTION and pos.symbol.startswith(SYMBOL) and int(pos.qty) > 0:
            open_leaps.append(pos)
            
    summary_lines = ["📊 <b>Weekly Open Positions Summary</b>"]
    if not open_leaps:
        summary_lines.append("No open positions.")
    else:
        for pos in open_leaps:
            avg_entry = float(pos.avg_entry_price)
            current_value = float(pos.current_price)
            if avg_entry > 0:
                profit_pct = ((current_value - avg_entry) / avg_entry) * 100
            else:
                profit_pct = 0.0
            summary_lines.append(f"• {pos.symbol}: {profit_pct:+.2f}%")
            
    summary_msg = "\n".join(summary_lines)
    send_telegram_message(summary_msg)
    print("Sent weekly summary.")
    
    state["last_summary_week"] = current_week
    save_state(state)

def log_positions_status():
    try:
        positions = trading_client.get_all_positions()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not positions:
            print(f"[{now_str}] Market is open. Checking positions: No open positions.")
            return
        
        print(f"[{now_str}] Market is open. Checking positions:")
        for pos in positions:
            print(f"  - {pos.symbol}: Qty {pos.qty}, Market Value: {pos.market_value}, Unrealized PnL: {pos.unrealized_pl} ({float(pos.unrealized_plpc)*100:.2f}%)")
    except Exception as e:
        print(f"Error checking positions: {e}")

def main():
    if not trading_client:
        print("Please configure your Alpaca API keys in .env file.")
        return

    print(f"Starting LEAPS Strategy for {SYMBOL} on Alpaca Paper: {PAPER}")
    while True:
        try:
            clock = trading_client.get_clock()
            
            # Send summary on Friday (weekday 4)
            # We do it regardless of market open/close (in case it's a holiday we still want it or just late Friday)
            if datetime.date.today().weekday() == 4:
                send_weekly_summary()
                
            if not clock.is_open:
                next_open = clock.next_open
                now = datetime.datetime.now(datetime.timezone.utc)
                time_to_open = (next_open - now).total_seconds()
                
                sleep_time = time_to_open - 3600
                if sleep_time > 0:
                    print(f"[{datetime.datetime.now()}] Markets are closed. Next open is at {next_open}. Sleeping for {sleep_time:.0f} seconds till within 1 hour of next market open.")
                    time.sleep(sleep_time)
                else:
                    print(f"[{datetime.datetime.now()}] Markets are closed, but within 1 hour of next open ({next_open}). Sleeping for 60 seconds.")
                    time.sleep(60)
                continue
                
            log_positions_status()
            check_leaps_strategy()
                
        except Exception as e:
            print(f"Error: {e}")
            
        time.sleep(600) # Check every 10 minutes

if __name__ == "__main__":
    main()
