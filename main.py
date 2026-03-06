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

# Expanded list to ensure we find momentum
value_candidates = ["GDDY", "EXPE", "BKNG", "GIB", "CTSH", "YOU", "ADBE", "STLD", "AMAT", "HCA"]

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

# --- 2. NOTIFICATION SYSTEM ---
def send_telegram_msg(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.get(url, params=params)

# --- 3. THE STRATEGY ENGINE ---
def get_6m_momentum(symbol):
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=180)
        request = StockBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame.Day, start=start_date, end=end_date)
        bars = data_client.get_stock_bars(request).df
        # Formula: (Price Now / Price 6 Months Ago) - 1
        return (bars['close'].iloc[-1] / bars['close'].iloc[0]) - 1
    except:
        return -99

def run_strategy():
    summary = "🚨 **Magic Momentum Execution Report**\n\n"
    
    scored_list = []
    for ticker in value_candidates:
        score = get_6m_momentum(ticker)
        # Only add to list if momentum is positive (> 0)
        if score > 0:
            scored_list.append({'ticker': ticker, 'score': score})
    
    # --- SAFETY CHECK ---
    if not scored_list:
        send_telegram_msg("⚠️ **Bot Update**: No stocks in the current list have positive 6-month momentum. No trades were executed.")
        return

    top_picks = pd.DataFrame(scored_list).sort_values(by='score', ascending=False).head(PORTFOLIO_SIZE)
    
    for ticker in top_picks['ticker']:
        try:
            # 1. Buy
            trading_client.submit_order(MarketOrderRequest(
                symbol=ticker, notional=CASH_PER_STOCK, side=OrderSide.BUY, time_in_force=TimeInForce.DAY
            ))
            
            # 2. Protect
            time.sleep(5) 
            pos = trading_client.get_open_position(ticker)
            trading_client.submit_order(TrailingStopOrderRequest(
                symbol=ticker, qty=pos.qty, side=OrderSide.SELL, 
                time_in_force=TimeInForce.GTC, trail_percent=TRAIL_PERCENT
            ))
            summary += f"✅ **{ticker}**: Bought & Protected\n"
        except Exception as e:
            summary += f"❌ **{ticker}**: Error: {str(e)}\n"

    send_telegram_msg(summary)

if __name__ == "__main__":
    run_strategy()
