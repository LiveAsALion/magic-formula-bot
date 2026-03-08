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
    
    # We add 'Headers' to look like a real Chrome browser
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.magicformulainvesting.com/Account/LogOn"
    }
    
    login_url = "https://www.magicformulainvesting.com/Account/LogOn"
    
    try:
        # Step 1: Get the login page first to handle cookies/tokens
        session.get(login_url, headers=headers)
        
        # Step 2: Post Login Data
        login_data = {
            "Email": MF_EMAIL, 
            "Password": MF_PASS, 
            "RememberMe": "false"
        }
        login_response = session.post(login_url, data=login_data, headers=headers)
        
        # Check if login worked by looking for "Log Off" in the HTML
        if "Log Off" not in login_response.text:
            print("❌ Login Failed. Check your GitHub Secrets for Email/Password typos.")
            return []
        
        print("✅ Login Successful. Requesting 50 Stocks (Market Cap > 50M)...")

        # Step 3: Get the Screen Results
        screen_url = "https://www.magicformulainvesting.com/Screening/StockScreen"
        screen_params = {
            "MinimumMarketCap": "50",
            "Select30": "false", # This toggle is what chooses 50 stocks vs 30
            "Submit": "Get Stocks"
        }
        
        response = session.post(screen_url, data=screen_params, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Step 4: Extract Tickers from the table
        tickers = []
        # The site usually wraps tickers in <td> tags with a specific class or near a link
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
        # Handle ticker formatting for Alpaca (e.g., BRK-B)
        symbol = symbol.replace('.', '-')
        
        request = StockBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame.Day, start=start_date, end=end_date)
        bars = data_client.get_stock_bars(request).df
        
        current_price = bars['close'].iloc[-1]
        ma200 = bars['close'].rolling(window=200).mean().iloc[-1]
        
        return current_price > ma200
    except Exception as e:
        # If
