import os
import time
import random
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
# It's recommended to use environment variables for security.
API_KEY = os.getenv('ALPACA_API_KEY')
SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
MF_EMAIL = os.getenv('MF_EMAIL') # New: Your magicformulainvesting.com email
MF_PASSWORD = os.getenv('MF_PASSWORD') # New: Your magicformulainvesting.com password
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# UPDATED USER-AGENT for better compatibility
MY_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

CASH_PER_STOCK = 1000
TRAIL_PERCENT = 10.0

# Initialize Alpaca Clients
trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

# --- 2. THE IMPROVED SCRAPER ---
def get_official_mf_tickers():
    """
    Robustly scrapes magicformulainvesting.com by simulating a full login session.
    This bypasses simple cookie-based detection by handling the CSRF tokens and session state.
    """
    print("🚀 Starting Strategy Run...")
    
    if not MF_EMAIL or not MF_PASSWORD:
        return None, "❌ Error: MF_EMAIL or MF_PASSWORD environment variables are missing."

    base_url = "https://www.magicformulainvesting.com"
    login_url = f"{base_url}/Account/LogOn"
    screen_url = f"{base_url}/Screening/StockScreening"
    
    headers = {
        "User-Agent": MY_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Origin": base_url,
        "Referer": login_url,
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }
    
    session = requests.Session()
    
    try:
        # Step 1: Get Login Page to retrieve CSRF token
        print("📡 Step 1: Fetching login page...")
        response = session.get(login_url, headers=headers, timeout=15)
        if response.status_code != 200:
            return None, f"❌ Failed to load login page: {response.status_code}"
            
        soup = BeautifulSoup(response.text, 'html.parser')
        token_tag = soup.find('input', {'name': '__RequestVerificationToken'})
        if not token_tag:
            return None, "⚠️ CSRF token not found on login page."
        
        token = token_tag['value']
        
        # Step 2: Perform Login
        print("📡 Step 2: Logging in to Magic Formula...")
        login_payload = {
            "Email": MF_EMAIL,
            "Password": MF_PASSWORD,
            "__RequestVerificationToken": token,
            "login": "Login"
        }
        
        # Add a small delay to mimic human behavior
        time.sleep(random.uniform(1.0, 3.0))
        
        login_response = session.post(login_url, data=login_payload, headers=headers, timeout=15)
        
        # Check if login was successful (usually redirects or "Log Off" appears)
        if "Log Off" not in login_response.text:
            print(f"❌ Login Check Failed. URL: {login_response.url}")
            return None, "💔 Login failed. Check credentials or site status."
            
        print("✅ Login successful.")
        
        # Step 3: Get Screening Page (to get the specific token for the screening form)
        print("📡 Step 3: Fetching screening page...")
        screen_page_response = session.get(screen_url, headers=headers, timeout=15)
        screen_soup = BeautifulSoup(screen_page_response.text, 'html.parser')
        
        screen_token_tag = screen_soup.find('input', {'name': '__RequestVerificationToken'})
        if not screen_token_tag:
            return None, "⚠️ CSRF token not found on screening page."
        
        screen_token = screen_token_tag['value']
        
        # Step 4: Post Screening Request for 50 stocks
        print("📡 Step 4: Requesting stock list (Top 50)...")
        screen_payload = {
            "MinimumMarketCap": "50", 
            "Select30": "false",      # false selects 50 stocks
            "Submit": "Get Stocks",
            "__RequestVerificationToken": screen_token
        }
        
        # Update referer for the post request
        headers["Referer"] = screen_url
        
        time.sleep(random.uniform(1.0, 2.0))
        result_response = session.post(screen_url, data=screen_payload, headers=headers, timeout=15)
        
        if result_response.status_code != 200:
            return None, f"❌ Failed to get screening results: {result_response.status_code}"
            
        # Step 5: Parse Results
        print("📡 Step 5: Parsing results...")
        result_soup = BeautifulSoup(result_response.text, 'html.parser')
        
        tickers = []
        # Find all links that point to stock details (the ticker text is inside)
        for link in result_soup.find_all('a'):
            href = link.get('href', '')
            if '/Screening/StockDetails/' in href:
                ticker = link.text.strip()
                if ticker and ticker not in tickers:
                    tickers.append(ticker)
        
        # Backup: try parsing the table rows if link method fails
        if not tickers:
            table = result_soup.find('table', {'class': 'screeningdata'})
            if table:
                rows = table.find_all('tr')[1:] # Skip header
                for row in rows:
                    cols = row.find_all('td')
                    if len(cols) > 1:
                        ticker = cols[1].text.strip()
                        if ticker:
                            tickers.append(ticker)
                            
        if not tickers:
            return None, "📋 Table empty or layout changed. No tickers found."
            
        print(f"✅ Success! Found {len(tickers)} tickers.")
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
        
        if bars.empty or len(bars) < 200:
            return False
            
        current_price = bars['close'].iloc[-1]
        ma200 = bars['close'].rolling(window=200).mean().iloc[-1]
        return current_price > ma200
    except Exception as e:
        print(f"Error calculating MA for {symbol}: {e}")
        return False

# --- 4. EXECUTION ENGINE ---
def run_strategy():
    tickers, status_msg = get_official_mf_tickers()
    
    # Heartbeat to Telegram
    if TELEGRAM_TOKEN:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        try:
            requests.get(url, params={"chat_id": TELEGRAM_CHAT_ID, "text": f"💓 **Heartbeat**: {status_msg}", "parse_mode": "Markdown"}, timeout=10)
        except:
            pass
    
    if not tickers:
        print("🛑 Run ended: No tickers retrieved.")
        return

    # Find the top 5 that are currently in an uptrend
    print(f"🔍 Screening {len(tickers)} stocks for 200-MA trend...")
    final_picks = []
    for t in tickers:
        if is_above_200_ma(t):
            print(f"✅ {t} is above 200-MA.")
            final_picks.append(t)
            if len(final_picks) >= 5:
                break
        else:
            # print(f"❌ {t} is below 200-MA.")
            pass
    
    if not final_picks:
        print("📊 No stocks above 200-MA found in the current list.")
        return

    print(f"🚀 Executing trades for: {final_picks}")
    summary = "🚀 **Trades Executed**\n"
    for ticker in final_picks:
        try:
            symbol = ticker.replace('.', '-')
            # Place Market Order
            trading_client.submit_order(MarketOrderRequest(
                symbol=symbol, notional=CASH_PER_STOCK, side=OrderSide.BUY, time_in_force=TimeInForce.DAY
            ))
            time.sleep(5) # Wait for fill
            
            # Place Trailing Stop
            pos = trading_client.get_open_position(symbol)
            trading_client.submit_order(TrailingStopOrderRequest(
                symbol=symbol, qty=pos.qty, side=OrderSide.SELL, time_in_force=TimeInForce.GTC, trail_percent=TRAIL_PERCENT
            ))
            summary += f"✅ **{ticker}**\n"
        except Exception as e:
            summary += f"❌ **{ticker}**: {e}\n"
    
    if TELEGRAM_TOKEN and "✅" in summary:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.get(url, params={"chat_id": TELEGRAM_CHAT_ID, "text": summary, "parse_mode": "Markdown"}, timeout=10)

if __name__ == "__main__":
    run_strategy()
