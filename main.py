import os
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.requests import MarketOrderRequest, TrailingStopOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# --- 1. CONFIGURATION ---
API_KEY = os.getenv('ALPACA_API_KEY')
SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
MF_EMAIL = os.getenv('MAGIC_FORMULA_EMAIL')
MF_PASS = os.getenv('MAGIC_FORMULA_PASSWORD')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

CASH_PER_STOCK = 1000 
TRAIL_PERCENT = 10.0 

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

# --- 2. THE ROBUST SCRAPER ---
def get_official_mf_tickers():
    print("🔐 Attempting Login to MagicFormulaInvesting.com...")
    session = requests.Session()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.magicformulainvesting.com/Account/LogOn"
    }
    
    login_url = "https://www.magicformulainvesting.com/Account/LogOn"
    
    try:
        session.get(login_url, headers=headers)
        
        login_data = {
            "Email": MF_EMAIL, 
            "Password": MF_PASS, 
            "RememberMe": "false"
        }
        login_response = session.post(login_url, data=login_data, headers=headers)
        
        if "Log Off" not in login_response.text:
            print("❌ Login Failed. Check your GitHub Secrets for Email/Password typos.")
            return []
        
        print("✅ Login Successful. Requesting 50 Stocks (Market Cap > 50M)...")

        screen_url = "https://www.magicformulainvesting.com/Screening/StockScreen"
        screen_params = {
            "MinimumMarketCap": "50",
            "Select30": "false", 
            "Submit": "Get Stocks"
        }
        
        response = session.post(screen_url, data=screen_params, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        tickers = []
        for link in soup.find_all('a'):
            href = link.get('href', '')
            if '/Screening/StockDetails/' in href:
                ticker = link.text.strip()
                if ticker and ticker not in tickers:
                    tickers.append(ticker)
        
        print(f"📋 Scraper found {len(tickers)} tickers: {tickers}")
        return tickers

    except Exception as e:
        print(f"⚠️ Scraper Error: {e}")
        return []

# --- 3. TREND FILTER (200-MA) ---
def is_above_200_ma(symbol):
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        symbol = symbol.replace('.', '-')
        
        request = StockBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame.Day, start=start_date, end=end_date)
        bars = data_client.get_stock_bars(request).df
        
        current_price = bars['close'].iloc[-1]
        ma200 = bars['close'].rolling(window=200).mean().iloc[-1]
        
        return current_price > ma200
    except Exception as e:
        # If we can't get data for a specific ticker, we skip it for safety
        print(f"Skipping {symbol}: No data found for 200-MA check.")
        return False

# --- 4. EXECUTION ENGINE ---
def run_strategy():
    send_telegram_msg("🕵️‍♂️ **Magic Momentum Scan Started**...")
    
    official_list = get_official_mf_tickers()
    
    if not official_list:
        send_telegram_msg("⚠️ **System Error**: Scraper returned 0 stocks. Check GitHub Action logs.")
        return
        
    # Send the full list to Telegram for your confirmation
    send_telegram_msg(f"📋 **Official MF List Found**: {', '.join(official_list[:10])}... (See logs for all 50)")

    final_picks = []
    for t in official_list:
        if is_above_200_ma(t):
            final_picks.append(t)
            if len(final_picks) >= 5: 
                break
    
    if not final_picks:
        send_telegram_msg("📊 Scan complete. Found high-quality stocks, but none are currently in a 200-day uptrend. Staying in cash.")
        return

    summary = "🚀 **Trades Executed**\n"
    for ticker in final_picks:
        try:
            trading_client.submit_order(MarketOrderRequest(
                symbol=ticker, notional=CASH_PER_STOCK, side=OrderSide.BUY, time_in_force=TimeInForce.DAY
            ))
            time.sleep(2) 
            pos = trading_client.get_open_position(ticker)
            trading_client.submit_order(TrailingStopOrderRequest(
                symbol=ticker, qty=pos.qty, side=OrderSide.SELL, 
                time_in_force=TimeInForce.GTC, trail_percent=TRAIL_PERCENT
            ))
            summary += f"✅ **{ticker}**\n"
        except Exception as e:
            summary += f"❌ **{ticker}**: {e}\n"
    
    send_telegram_msg(summary)

def send_telegram_msg(text):
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.get(url, params={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"})

if __name__ == "__main__":
    run_strategy()
