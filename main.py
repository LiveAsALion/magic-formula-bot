import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.requests import MarketOrderRequest, TrailingStopOrderRequest, GetPortfolioHistoryRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# --- 1. CONFIGURATION ---
API_KEY = os.getenv('ALPACA_API_KEY')
SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

PORTFOLIO_SIZE = 5 
CASH_PER_STOCK = 1000 
TRAIL_PERCENT = 10.0 

# High-Quality Value Candidates (March 2026)
value_candidates = ["GDDY", "EXPE", "BKNG", "GIB", "CTSH", "YOU", "ADBE", "STLD", "AMAT", "HCA"]

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

# --- 2. NOTIFICATION SYSTEM ---
def send_telegram_msg(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": TELEGRAM_CHAT_ID, "text": f"🚨 **Magic Momentum Alert**\n{text}", "parse_mode": "Markdown"}
    requests.get(url, params=params)

# --- 3. THE PROFESSIONAL TREND FILTER ---
def is_above_200_ma(symbol):
    """Checks if the current price is above the 200-Day Moving Average."""
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365) # Get a year of data to calculate 200-MA
        
        request = StockBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame.Day, start=start_date, end=end_date)
        bars = data_client.get_stock_bars(request).df
        
        # Calculate the 200-Day Simple Moving Average
        current_price = bars['close'].iloc[-1]
        moving_average_200 = bars['close'].rolling(window=200).mean().iloc[-1]
        
        # Return True if price is above the line, else False
        return current_price > moving_average_200
    except:
        return False

def run_strategy():
    summary = ""
    success_count = 0
    
    # Filter for the Golden Line (200-MA)
    filtered_list = []
    for ticker in value_candidates:
        if is_above_200_ma(ticker):
            filtered_list.append(ticker)
    
    if not filtered_list:
        send_telegram_msg("System scan complete. No candidates are currently above their 200-day trend line. Staying in cash to protect capital.")
        return

    # Execute Trades for the first 5 healthy stocks
    for ticker in filtered_list[:PORTFOLIO_SIZE]:
        try:
            # Buy
            trading_client.submit_order(MarketOrderRequest(
                symbol=ticker, notional=CASH_PER_STOCK, side=OrderSide.BUY, time_in_force=TimeInForce.DAY
            ))
            
            # Safety delay then protect
            time.sleep(5) 
            pos = trading_client.get_open_position(ticker)
            trading_client.submit_order(TrailingStopOrderRequest(
                symbol=ticker, qty=pos.qty, side=OrderSide.SELL, 
                time_in_force=TimeInForce.GTC, trail_percent=TRAIL_PERCENT
            ))
            summary += f"✅ **{ticker}** (Added to Portfolio)\n"
            success_count += 1
        except Exception as e:
            summary += f"❌ **{ticker}** (Error: {str(e)})\n"

    if success_count > 0:
        send_telegram_msg(f"Trades Executed:\n{summary}\nSafety: 10% Trailing Stops Active.")

if __name__ == "__main__":
    run_strategy()
