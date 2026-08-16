import os
import time
import datetime
import json
import subprocess
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOptionContractsRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, AssetClass, QueryOrderStatus
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

def get_furthest_atm_calls_sorted(symbol, current_price):
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
        return []

    available_dates = sorted(list(set(c.expiration_date for c in contracts.option_contracts)))
    if not available_dates:
        return []
    
    furthest_date = available_dates[-1]
    
    furthest_contracts = [c for c in contracts.option_contracts if c.expiration_date == furthest_date]
    furthest_contracts.sort(key=lambda c: abs(float(c.strike_price) - current_price))
    return furthest_contracts

def get_furthest_atm_call(symbol, current_price):
    contracts = get_furthest_atm_calls_sorted(symbol, current_price)
    return contracts[0] if contracts else None

def place_order(symbol, qty, side, reason="", silent=False):
    req = MarketOrderRequest(
        symbol=symbol,
        qty=abs(qty),
        side=side,
        time_in_force=TimeInForce.DAY
    )
    res = trading_client.submit_order(order_data=req)
    msg = f"🟢 <b>TRADE EXECUTED</b>\nSide: {side.name}\nQty: {abs(qty)}\nSymbol: {symbol}\nReason: {reason}\nOrder ID: {res.id}"
    print(msg.replace('<b>', '').replace('</b>', ''))
    if not silent:
        send_telegram_message(msg)
    return res

def buy_leaps_with_retry(symbol_base, current_price, reason):
    contracts = get_furthest_atm_calls_sorted(symbol_base, current_price)
    for contract in contracts[:3]: # Try up to 3 closest strikes
        res = place_order(contract.symbol, 1, OrderSide.BUY, f"{reason} (Strike {contract.strike_price})", silent=True)
        
        # Wait up to 30s for fill
        filled = False
        for _ in range(30):
            time.sleep(1)
            try:
                order = trading_client.get_order_by_id(res.id)
                if order.status == "filled":
                    filled = True
                    break
                if order.status in ["canceled", "rejected", "expired"]:
                    break
            except Exception:
                pass
                
        if filled:
            msg = f"🟢 <b>TRADE FILLED</b>\nSide: BUY\nQty: 1\nSymbol: {contract.symbol}\nReason: {reason}\nOrder ID: {res.id}"
            send_telegram_message(msg)
            print(f"Order filled for {contract.symbol}")
            return contract
        else:
            print(f"Order for {contract.symbol} not filled. Canceling and trying next strike.")
            try:
                trading_client.cancel_order_by_id(res.id)
            except Exception as e:
                print(f"Error canceling order: {e}")
    return None

def check_leaps_strategy(clock):
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

    if current_week != state.get("last_buy_week"):
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

    # 1% Daily Drop logic
    if clock.is_open:
        now = datetime.datetime.now(datetime.timezone.utc)
        time_to_close = (clock.next_close - now).total_seconds()
        
        # Check if we are in the final hour of trading
        if 0 < time_to_close <= 3600:
            today_str = today.strftime("%Y-%m-%d")
            if state.get("last_daily_drop_buy_date") != today_str:
                from alpaca.data.requests import StockSnapshotRequest
                try:
                    req = StockSnapshotRequest(symbol_or_symbols=[SYMBOL])
                    snap = stock_data_client.get_stock_snapshot(req)
                    if SYMBOL in snap:
                        spy_snap = snap[SYMBOL]
                        prev_close = spy_snap.previous_daily_bar.close
                        current_price = spy_snap.latest_quote.ask_price
                        
                        if prev_close > 0:
                            drop_pct = (prev_close - current_price) / prev_close
                            if drop_pct > 0.01:
                                msg = f"🚨 Detected >1% drop today in final hour. Drop: {drop_pct*100:.2f}%. Prev Close: {prev_close}, Current: {current_price}"
                                print(msg)
                                send_telegram_message(msg)
                                
                                contract = buy_leaps_with_retry(SYMBOL, current_price, "Daily >1% drop in final hour")
                                if contract:
                                    state["last_daily_drop_buy_date"] = today_str
                                    state["positions_buy_dates"][contract.symbol] = today_str
                                    save_state(state)
                                else:
                                    print("Failed to buy LEAPS for daily drop condition even after retries.")
                except Exception as e:
                    print(f"Error checking daily drop condition: {e}")

def get_open_lots(symbol, current_qty):
    req = GetOrdersRequest(
        status=QueryOrderStatus.CLOSED,
        symbols=[symbol],
        side=OrderSide.BUY,
        limit=100
    )
    orders = trading_client.get_orders(req)
    filled_orders = [o for o in orders if o.status == "filled"]
    filled_orders.sort(key=lambda x: x.filled_at, reverse=True)
    
    lots = []
    remaining_qty = int(current_qty)
    for o in filled_orders:
        if remaining_qty <= 0:
            break
        qty = int(o.filled_qty)
        if qty > remaining_qty:
            qty = remaining_qty
            
        lots.append({
            "buy_date": o.filled_at.strftime("%Y-%m-%d"),
            "qty": qty,
            "entry_price": float(o.filled_avg_price)
        })
        remaining_qty -= qty
        
    lots.reverse()
    return lots

def send_daily_summary():
    positions = trading_client.get_all_positions()
    open_leaps = []
    
    for pos in positions:
        if pos.asset_class == AssetClass.US_OPTION and pos.symbol.startswith(SYMBOL) and int(pos.qty) > 0:
            open_leaps.append(pos)
            
    summary_lines = ["📈 <b>Daily P/L Report</b>"]
    if not open_leaps:
        summary_lines.append("No open positions.")
    else:
        for pos in open_leaps:
            intraday_plpc = float(pos.unrealized_intraday_plpc) * 100
            intraday_pl = float(pos.unrealized_intraday_pl)
            summary_lines.append(f"• {pos.symbol}: ${intraday_pl:+.2f} ({intraday_plpc:+.2f}%) today")
            
    summary_msg = "\n".join(summary_lines)
    send_telegram_message(summary_msg)
    print("Sent daily summary.")

def send_weekly_summary():
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
            current_value = float(pos.current_price)
            current_qty = int(pos.qty)
            lots = get_open_lots(pos.symbol, current_qty)
            
            if lots:
                for lot in lots:
                    entry = lot["entry_price"]
                    qty = lot["qty"]
                    buy_date = lot["buy_date"]
                    if entry > 0:
                        profit_pct = ((current_value - entry) / entry) * 100
                    else:
                        profit_pct = 0.0
                    summary_lines.append(f"• {pos.symbol} (Opened {buy_date}, Qty {qty}): {profit_pct:+.2f}%")
            else:
                # Fallback if no lots found
                avg_entry = float(pos.avg_entry_price)
                if avg_entry > 0:
                    profit_pct = ((current_value - avg_entry) / avg_entry) * 100
                else:
                    profit_pct = 0.0
                summary_lines.append(f"• {pos.symbol}: {profit_pct:+.2f}%")
            
    summary_msg = "\n".join(summary_lines)
    send_telegram_message(summary_msg)
    print("Sent weekly summary.")

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

def get_git_commit():
    try:
        return subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], stderr=subprocess.STDOUT).decode('utf-8').strip()
    except Exception:
        return "unknown"

def init_telegram_polling():
    if not TELEGRAM_BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    try:
        resp = requests.get(url, timeout=5)
        data = resp.json()
        if data.get("ok") and data["result"]:
            return data["result"][-1]["update_id"]
    except:
        pass
    return None

def send_current_positions():
    try:
        positions = trading_client.get_all_positions()
        open_leaps = []
        for pos in positions:
            if pos.asset_class == AssetClass.US_OPTION and pos.symbol.startswith(SYMBOL) and int(pos.qty) > 0:
                open_leaps.append(pos)
                
        summary_lines = ["📈 <b>Current Positions</b>"]
        if not open_leaps:
            summary_lines.append("No open positions.")
        else:
            for pos in open_leaps:
                market_value = float(pos.market_value)
                unrealized_pl = float(pos.unrealized_pl)
                unrealized_plpc = float(pos.unrealized_plpc) * 100
                summary_lines.append(f"• {pos.symbol}: Value ${market_value:.2f} | P/L: ${unrealized_pl:+.2f} ({unrealized_plpc:+.2f}%)")
                
        send_telegram_message("\n".join(summary_lines))
    except Exception as e:
        send_telegram_message(f"Error fetching positions: {e}")

def execute_adhoc_buy():
    print("Executing ad-hoc buy...")
    send_telegram_message("⏳ Checking for furthest ATM call to purchase...")
    try:
        current_price = get_current_price(SYMBOL)
        contract = get_furthest_atm_call(SYMBOL, current_price)
        if contract:
            print(f"Ad-hoc buy: placing order for {contract.symbol}")
            res = place_order(contract.symbol, 1, OrderSide.BUY, "Adhoc User Telegram Command")
            state = load_state()
            today_str = datetime.date.today().strftime("%Y-%m-%d")
            state["positions_buy_dates"][contract.symbol] = today_str
            save_state(state)
            print(f"Ad-hoc buy executed and state updated for {contract.symbol}")
        else:
            print("Ad-hoc buy: failed to find suitable contract.")
            send_telegram_message("❌ Failed to find a suitable contract.")
    except Exception as e:
        print(f"Error executing ad-hoc buy: {e}")
        send_telegram_message(f"Error executing buy: {e}")

def do_adhoc_buy():
    print("Received ad-hoc buy request from Telegram.")
    try:
        clock = trading_client.get_clock()
        if not clock.is_open:
            print("Market is closed. Queuing ad-hoc buy for next open.")
            send_telegram_message("🕒 Market is currently closed. Queuing your ad-hoc buy order for market open.")
            state = load_state()
            state["queued_adhoc_buy"] = True
            save_state(state)
        else:
            execute_adhoc_buy()
    except Exception as e:
        print(f"Error handling ad-hoc buy request: {e}")
        send_telegram_message(f"Error handling ad-hoc buy: {e}")

def handle_telegram_updates(last_update_id):
    if not TELEGRAM_BOT_TOKEN:
        return last_update_id
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"timeout": 5}
    if last_update_id:
        params["offset"] = last_update_id + 1
        
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("ok"):
            for update in data["result"]:
                update_id = update["update_id"]
                last_update_id = update_id
                
                msg = update.get("message", {})
                if not msg:
                    continue
                    
                text = msg.get("text", "").strip()
                chat_id = msg.get("chat", {}).get("id")
                
                if str(chat_id) != str(TELEGRAM_CHAT_ID):
                    print(f"Ignoring message from unknown chat_id: {chat_id}")
                    continue
                    
                print(f"Received command: {text}")
                if text.lower() in ["/positions", "positions", "/position", "position"]:
                    send_current_positions()
                elif text.lower() in ["/buy", "buy"]:
                    do_adhoc_buy()
        else:
            print(f"Telegram polling returned not ok: {data}")
                    
    except Exception as e:
        print(f"Telegram polling error: {e}")
        
    return last_update_id

def main():
    if not trading_client:
        print("Please configure your Alpaca API keys in .env file.")
        return

    commit_hash = get_git_commit()
    startup_msg = f"🚀 Starting LEAPS Strategy for {SYMBOL} on Alpaca Paper: {PAPER}\nVersion (Commit): {commit_hash}"
    print(startup_msg)
    send_telegram_message(startup_msg)
    last_update_id = init_telegram_polling()
    last_strategy_check = 0
    
    while True:
        last_update_id = handle_telegram_updates(last_update_id)
        
        now_ts = time.time()
        if now_ts - last_strategy_check >= 600:
            last_strategy_check = now_ts
            try:
                clock = trading_client.get_clock()
                
                # Check for end of day summaries (Daily & Weekly)
                now = datetime.datetime.now(datetime.timezone.utc)
                time_to_open = (clock.next_open - now).total_seconds()
                
                is_after_market_close = not clock.is_open and time_to_open > 12 * 3600
                
                if is_after_market_close:
                    state = load_state()
                    today_str = datetime.date.today().strftime("%Y-%m-%d")
                    
                    if state.get("last_daily_summary_date") != today_str:
                        send_daily_summary()
                        state["last_daily_summary_date"] = today_str
                        save_state(state)
                        
                    if datetime.date.today().weekday() == 4 and state.get("last_weekly_summary_date") != today_str:
                        send_weekly_summary()
                        state["last_weekly_summary_date"] = today_str
                        save_state(state)
                    
                if clock.is_open:
                    state = load_state()
                    if state.get("queued_adhoc_buy"):
                        print("Market is open. Executing queued ad-hoc buy...")
                        send_telegram_message("🔔 Market is now open! Processing your queued ad-hoc buy...")
                        execute_adhoc_buy()
                        state["queued_adhoc_buy"] = False
                        save_state(state)
                        
                    log_positions_status()
                    check_leaps_strategy(clock)
                    
            except Exception as e:
                print(f"Error: {e}")
                
        time.sleep(2)

if __name__ == "__main__":
    main()
