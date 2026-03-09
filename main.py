import os
import time
import random
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.requests import MarketOrderRequest, TrailingStopOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# --- 1. CONFIGURATION ---
API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
MF_EMAIL = os.getenv("MF_EMAIL") 
MF_PASSWORD = os.getenv("MF_PASSWORD")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

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
    Enhanced with detailed logging and multiple parsing strategies.
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
        # Step 1: Get Login Page
        print("📡 Step 1: Fetching login page...")
        response = session.get(login_url, headers=headers, timeout=15)
        if response.status_code != 200:
            return None, f"❌ Failed to load login page: {response.status_code}"
            
        soup = BeautifulSoup(response.text, "html.parser")
        token_tag = soup.find("input", {"name": "__RequestVerificationToken"})
        if not token_tag:
            return None, "⚠️ CSRF token not found on login page."
        
        token = token_tag["value"]
        
        # Step 2: Perform Login
        print(f"📡 Step 2: Logging in as {MF_EMAIL}...")
        login_payload = {
            "Email": MF_EMAIL,
            "Password": MF_PASSWORD,
            "__RequestVerificationToken": token,
            "login": "Login"
        }
        
        time.sleep(random.uniform(2.0, 4.0))
        login_response = session.post(login_url, data=login_payload, headers=headers, timeout=15)
        
        print(f"DEBUG: Login response final URL: {login_response.url}")
        print(f"DEBUG: Expected screen URL: {screen_url}")

        # Relaxed login verification: Check if redirected to screening page or if 'Log Off' is present
        if screen_url in login_response.url or "Log Off" in login_response.text:
            print("✅ Login successful (redirected to screening page or 'Log Off' found).")
        else:
            print(f"❌ Login Check Failed. Final URL: {login_response.url}")
            if "Invalid" in login_response.text:
                return None, "💔 Login failed: Invalid email or password."
            print("DEBUG: First 1000 chars of login_response.text if 'Log Off' not found:")
            print(login_response.text[:1000])
            return None, "💔 Login failed: Neither redirected to screening page nor 'Log Off' link found."
            
        # Step 3: Get Screening Page (even if we were redirected, ensure we have the latest page content)
        print("📡 Step 3: Fetching screening page...")
        screen_page_response = session.get(screen_url, headers=headers, timeout=15)
        screen_soup = BeautifulSoup(screen_page_response.text, "html.parser")
        
        screen_token_tag = screen_soup.find("input", {"name": "__RequestVerificationToken"})
        if not screen_token_tag:
            return None, "⚠️ CSRF token not found on screening page after login."
        
        screen_token = screen_token_tag["value"]
        
        # Step 4: Post Screening Request
        print("📡 Step 4: Requesting stock list (Top 50)...")
        screen_payload = {
            "MinimumMarketCap": "50", 
            "Select30": "false",      # false selects 50 stocks
            "Submit": "Get Stocks",
            "__RequestVerificationToken": screen_token
        }
        
        headers["Referer"] = screen_url
        time.sleep(random.uniform(2.0, 4.0))
        result_response = session.post(screen_url, data=screen_payload, headers=headers, timeout=15)
        
        if result_response.status_code != 200:
            return None, f"❌ Failed to get screening results: {result_response.status_code}"
            
        # Step 5: Parse Results
        print("📡 Step 5: Parsing results...")
        result_soup = BeautifulSoup(result_response.text, "html.parser")
        
        tickers = []
        
        # Strategy A: Find all links that point to stock details
        for link in result_soup.find_all("a"):
            href = link.get("href", "")
            if "/Screening/StockDetails/" in href:
                ticker = link.text.strip()
                if ticker and ticker not in tickers:
                    tickers.append(ticker)
        
        # Strategy B: If Strategy A fails, try parsing the table rows
        if not tickers:
            print("⚠️ Strategy A failed. Trying Strategy B (table parsing)...")
            # Look for common table classes or patterns
            table = result_soup.find("table", {"class": "screeningdata"}) or result_soup.find("table")
            if table:
                rows = table.find_all("tr")
                # Assuming header row and then data rows
                for row in rows[1:]:
                    cols = row.find_all("td")
                    if len(cols) >= 2:
                        # Ticker is usually in the second column (index 1)
                        ticker = cols[1].text.strip()
                        # Basic validation for a ticker (usually 1-5 uppercase letters)
                        if ticker and ticker.isupper() and 1 <= len(ticker) <= 5:
                            if ticker not in tickers:
                                tickers.append(ticker)
                            
        if not tickers:
            print("DEBUG: No tickers found. Printing first 1000 chars of result_response.text:")
            print(result_response.text[:1000])
            return None, "📋 No tickers found in the results. Layout might have changed or table is empty."
            
        print(f"✅ Success! Found {len(tickers)} tickers.")
        return list(set(tickers)), "💚 Session Healthy"

    except Exception as e:
        return None, f"⚠️ Error: {str(e)}"

# --- 3. TREND FILTER (200-MA) ---
def is_above_200_ma(symbol):
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        clean_symbol = symbol.replace(".", "-")
        request = StockBarsRequest(symbol_or_symbols=[clean_symbol], timeframe=TimeFrame.Day, start=start_date, end=end_date)
        bars = data_client.get_stock_bars(request).df
        
        if bars.empty or len(bars) < 200:
            return False
            
        current_price = bars["close"].iloc[-1]
        ma200 = bars["close"].rolling(window=200).mean().iloc[-1]
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
        print(f"🛑 Run ended: {status_msg}")
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
            symbol = ticker.replace(".", "-")
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
