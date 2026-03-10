import os
import time
import random
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# Import yfinance for historical data
import yfinance as yf

from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.requests import MarketOrderRequest, TrailingStopOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
import json

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
PORTFOLIO_FILE = "portfolio.json"

# Initialize Alpaca Clients (only for trading, data will come from yfinance)
trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)

# --- Helper Functions for Portfolio Management ---
def load_portfolio():
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, "r") as f:
            return json.load(f)
    return []

def save_portfolio(portfolio):
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(portfolio, f, indent=4)

def get_current_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d")
        if not hist.empty:
            return hist["Close"].iloc[-1]
    except Exception as e:
        print(f"Error getting current price for {symbol}: {e}")
    return None

def send_telegram_message(message):
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        try:
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=10)
        except Exception as e:
            print(f"Error sending Telegram message: {e}")

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

        # Relaxed login verification: Check if redirected to screening page or if \'Log Off\' is present
        if screen_url in login_response.url or "Log Off" in login_response.text:
            print("✅ Login successful (redirected to screening page or \'Log Off\' found).")
        else:
            print(f"❌ Login Check Failed. Final URL: {login_response.url}")
            if "Invalid" in login_response.text:
                return None, "💔 Login failed: Invalid email or password."
            print("DEBUG: First 1000 chars of login_response.text if \'Log Off\' not found:")
            print(login_response.text[:1000])
            return None, "💔 Login failed: Neither redirected to screening page nor \'Log Off\' link found."
            
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
        # Use yfinance to get historical data
        ticker = yf.Ticker(symbol)
        # Fetch data for a longer period to ensure 200 data points are available
        hist = ticker.history(period="1y") 
        
        if hist.empty or len(hist) < 200:
            print(f"⚠️ Not enough data for {symbol} to calculate 200-MA.")
            return False
            
        current_price = hist["Close"].iloc[-1]
        ma200 = hist["Close"].rolling(window=200).mean().iloc[-1]
        
        return current_price > ma200
    except Exception as e:
        print(f"Error calculating MA for {symbol} using yfinance: {e}")
        return False

# --- 4. EXECUTION ENGINE ---
def run_strategy():
    current_date = datetime.now()
    portfolio = load_portfolio()
    updated_portfolio = []
    
    summary_messages = []
    errors_encountered = []

    # --- Portfolio Rebalancing and Exit Strategy ---
    print("📊 Evaluating existing portfolio positions...")
    summary_messages.append("📊 *Portfolio Rebalancing:*")
    
    positions_to_sell = []
    positions_to_re_evaluate = []
    positions_to_hold = []

    for position in portfolio:
        symbol = position["symbol"]
        purchase_date = datetime.fromisoformat(position["purchase_date"])
        purchase_price = position["purchase_price"]
        quantity = position["quantity"]
        
        current_price = get_current_price(symbol)
        if current_price is None:
            errors_encountered.append(f"⚠️ Could not get current price for {symbol}. Skipping re-evaluation.")
            positions_to_hold.append(position) # Keep if price cannot be fetched
            continue
            
        gain_loss_percent = ((current_price - purchase_price) / purchase_price) * 100
        days_held = (current_date - purchase_date).days
        
        print(f"  - {symbol}: Days held={days_held}, Gain/Loss={gain_loss_percent:.2f}%")

        # Rule 1: Sell overall loss after 360 days
        if gain_loss_percent < 0 and days_held >= 360:
            positions_to_sell.append({"symbol": symbol, "reason": "loss after 360 days"})
            summary_messages.append(f"  - 📉 Selling {symbol} (loss after 360 days).")
            
        # Rule 2 & 3: Re-evaluate gains after 366 days
        elif gain_loss_percent >= 0 and days_held >= 366:
            positions_to_re_evaluate.append(position)
            summary_messages.append(f"  - 📈 Re-evaluating {symbol} (gain after 366 days).")
        else:
            # Hold if not yet at re-evaluation point
            positions_to_hold.append(position)
            
    # Execute sales for positions_to_sell
    for sale_item in positions_to_sell:
        symbol = sale_item["symbol"]
        try:
            trading_client.close_position(symbol)
            # Position is removed from portfolio implicitly by not being added to updated_portfolio
        except Exception as e:
            errors_encountered.append(f"❌ Error selling {symbol}: {e}")
            # If sale fails, keep in portfolio for next run
            for p in portfolio:
                if p["symbol"] == symbol:
                    positions_to_hold.append(p)
                    break

    # --- New Stock Screening and Buying ---
    mf_tickers, status_msg = get_official_mf_tickers()
    if mf_tickers is None:
        errors_encountered.append(f"❌ Magic Formula Scraper Error: {status_msg}")
        summary_messages.append(f"🛑 Run ended prematurely due to scraper error.")
        send_telegram_message("\n".join(summary_messages + errors_encountered))
        return

    # Filter MF tickers by 200-MA and get top 10 for re-evaluation
    print(f"🔍 Screening {len(mf_tickers)} stocks for 200-MA trend...")
    screened_mf_picks = []
    for t in mf_tickers:
        if is_above_200_ma(t):
            screened_mf_picks.append(t)
    
    if not screened_mf_picks:
        summary_messages.append("📊 No Magic Formula stocks above 200-MA found in the current list.")

    # --- Re-evaluation of Gaining Positions against New MF List ---
    summary_messages.append("\n📈 *Gaining Positions Re-evaluation:*")
    for position in positions_to_re_evaluate:
        symbol = position["symbol"]
        
        # Check if it\'s in the top 10 of the newly screened MF list
        if symbol in screened_mf_picks[:10]: # Top 10 of the new MF list
            summary_messages.append(f"  - ✅ Holding {symbol} for another year (still a top MF pick).")
            # Update purchase date to effectively reset the 366-day timer for re-evaluation
            position["purchase_date"] = current_date.isoformat()
            positions_to_hold.append(position)
        else:
            summary_messages.append(f"  - ❌ Selling {symbol} (gain but not in top MF picks after 366 days).")
            try:
                trading_client.close_position(symbol)
            except Exception as e:
                errors_encountered.append(f"❌ Error selling {symbol}: {e}")
                positions_to_hold.append(position) # Keep if sale fails
            
    save_portfolio(positions_to_hold) # Save portfolio after re-evaluation and sales

    # --- Buy New Stocks ---
    summary_messages.append("\n🛒 *New Stock Purchases:*")
    current_holdings = [p["symbol"] for p in positions_to_hold]
    new_picks_to_buy = []
    for t in screened_mf_picks:
        if t not in current_holdings:
            new_picks_to_buy.append(t)
        if len(new_picks_to_buy) >= 5: # Limit to 5 new picks for now
            break

    if not new_picks_to_buy:
        summary_messages.append("  - 📊 No new stocks to buy based on current screening and portfolio.")
    else:
        print(f"🚀 Executing trades for new picks: {new_picks_to_buy}")
        for ticker in new_picks_to_buy:
            try:
                symbol = ticker.replace(".", "-")
                # Place Market Order
                order = trading_client.submit_order(MarketOrderRequest(
                    symbol=symbol, notional=CASH_PER_STOCK, side=OrderSide.BUY, time_in_force=TimeInForce.DAY
                ))
                time.sleep(5) # Wait for fill
                
                # Assuming order is filled, add to portfolio
                current_price_at_buy = get_current_price(symbol)
                if current_price_at_buy:
                    new_position = {
                        "symbol": symbol,
                        "purchase_date": current_date.isoformat(),
                        "purchase_price": current_price_at_buy,
                        "quantity": CASH_PER_STOCK / current_price_at_buy # Approximate quantity
                    }
                    positions_to_hold.append(new_position)
                    save_portfolio(positions_to_hold)

                # Place Trailing Stop
                trading_client.submit_order(TrailingStopOrderRequest(
                    symbol=symbol, qty=new_position["quantity"], side=OrderSide.SELL, time_in_force=TimeInForce.GTC, trail_percent=TRAIL_PERCENT
                ))
                summary_messages.append(f"  - ✅ Purchased **{ticker}** (Qty: {new_position['quantity']:.2f} @ ${new_position['purchase_price']:.2f}).")
            except Exception as e:
                errors_encountered.append(f"❌ Error purchasing {ticker}: {e}")
    
    # Final Summary Message
    final_summary = f"*Magic Formula Bot Run Summary - {current_date.strftime('%Y-%m-%d %H:%M')} EST*\n\n" + "\n".join(summary_messages)
    if errors_encountered:
        final_summary += "\n\n⚠️ *Errors/Warnings:*
" + "\n".join(errors_encountered)
    
    send_telegram_message(final_summary)

if __name__ == "__main__":
    run_strategy()
