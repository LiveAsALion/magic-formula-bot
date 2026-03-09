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
from alpaca.trading.requests import MarketOrderRequest, TrailingStopOrderRequest, GetPortfolioHistoryRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# --- 1. CONFIGURATION ---
API_KEY = os.getenv('ALPACA_API_KEY')
SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
MF_COOKIE_VAL = os.getenv('MF_COOKIE')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

CASH_PER_STOCK = 1000
TRAIL_PERCENT = 10.0

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

# --- 2. THE PRECISION SCRAPER ---
def get_official_mf_tickers():
    print("🚀 Starting Strategy Run...")
    print("🍪 Step 1: Synchronizing Session...")
    session = requests.Session()
    
    url = "https://www.magicformulainvesting.com/Screening/StockScreen"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Referer": "https://www.magicformulainvesting.com/",
        "DNT": "1"
    }
    
    if not MF_COOKIE_VAL:
        return None, "❌ Error: MF_COOKIE Secret is missing."

    # Clean cookie and inject into session
    clean_val = MF_COOKIE_VAL.strip().replace('"', '').replace("'", "")
    session.cookies.set("mfi", clean_val, domain="www.magicformulainvesting.com")
    
    try:
        print(f"📡 Step 2: Accessing {url}...")
        initial_page = session.get(url, headers=headers, timeout=15, allow_redirects=True)
        
        if "Log Off" not in initial_page.text:
            print(f"❌ Landing Page Check Failed. Final URL: {initial_page.url}")
            return None, "💔 Session Expired (Redirected or Logged Out)"
        
        print("✅ Step 3: Page Loaded. Extracting Form Data...")
        soup = BeautifulSoup(initial_page.text, 'html.parser')
        token_tag = soup.find('input', {'name': '__RequestVerificationToken'})
        
        if not token_tag:
            return None, "⚠️ Security Token Missing from page"
            
        token = token_tag['value']
        
        payload = {
            "MinimumMarketCap": "50",
            "Select30": "false", 
            "Submit": "Get Stocks",
            "__RequestVerificationToken": token
        }
        
        print("📡 Step 4: Posting Screening Request...")
        response = session.post(url, data=payload, headers=headers, timeout=15)
        
        result_soup = BeautifulSoup(response.text, 'html.parser')
        tickers = []
        for link in result_soup.find_all('a'):
            href = link.get('href', '')
            if '/Screening/StockDetails/' in href:
                ticker = link.text.strip()
                if ticker and ticker not in tickers:
                    tickers.append(ticker)
        
        if not tickers:
            return None, "📋 Table empty or layout changed."
            
        print(f"✅ Step 5: Success! Found {len(tickers)} tickers.")
        return list(set(tickers)), "💚 Session Healthy"

    except Exception as e:
        return None, f"⚠️ Error: {str(e)}"

# --- 3. TREND FILTER (200-MA) ---
def is_above_200_ma(symbol):
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        clean_symbol = symbol.replace('.', '-')
        request = StockBarsRequest(symbol_or_symbols=[clean_symbol], timeframe=TimeFrame.Day, start=start_date, end=end_date)
        bars = data_client.get_stock_bars(request).df
        current_price = bars['close'].iloc[-1]
        ma200 = bars['close'].rolling(window=200).mean().iloc[-1]
        return current_price > ma200
    except:
        return False

# --- 4. EXECUTION ENGINE ---
def run_strategy():
    tickers, status_msg = get_official_mf_tickers()
    send_telegram_msg(f"💓 **Heartbeat**: {status_msg}")
    
    if not tickers:
        print("🛑 Run ended: No tickers retrieved.")
        return

    final_picks = []
    for t in tickers:
        if is_above_200_ma(t):
            final_picks.append(t)
            if len(final_picks) >= 5:
                break
    
    if not final_picks:
        send_telegram_msg(f"📊 Scan of {len(tickers)} stocks complete. No candidates are above the 200-MA. Holding cash.")
        return

    summary = "🚀 **Trades Executed**\n"
    for ticker in final_picks:
        try:
            symbol = ticker.replace('.', '-')
            trading_client.submit_order(MarketOrderRequest(
                symbol=symbol, notional=CASH_PER_STOCK, side=OrderSide.BUY, time_in_force=TimeInForce.DAY
            ))
            time.sleep(5) 
            pos = trading_client.get_open_position(symbol)
            trading_client.submit_order(TrailingStopOrderRequest(
                symbol=symbol, qty=pos.qty, side=OrderSide.SELL, time_in_force=TimeInForce.GTC, trail_percent=TRAIL_PERCENT
            ))
            summary += f"✅ **{ticker}**\n"
        except Exception as e:
            summary += f"❌ **{ticker}**: {e}\n"
    
    send_telegram_msg(summary)

def send_telegram_msg(text):
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.get(url, params={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except:
        pass

if __name__ == "__main__":
    run_strategy()
