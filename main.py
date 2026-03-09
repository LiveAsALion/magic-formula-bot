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
MF_COOKIE_VAL = os.getenv('MF_COOKIE')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

MY_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

def get_official_mf_tickers():
    print("🚀 Starting Strategy Run...")
    session = requests.Session()
    url = "https://www.magicformulainvesting.com/Screening/StockScreen"
    
    headers = {
        "User-Agent": MY_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.magicformulainvesting.com/Account/LogOn",
        "Upgrade-Insecure-Requests": "1"
    }
    
    if not MF_COOKIE_VAL:
        return None, "❌ Error: MF_COOKIE Secret is missing."

    clean_val = MF_COOKIE_VAL.strip().replace('"', '').replace("'", "")
    session.cookies.set("mfi", clean_val, domain="www.magicformulainvesting.com")
    
    try:
        print(f"📡 Step 2: Accessing {url}...")
        initial_page = session.get(url, headers=headers, timeout=15)
        
        # --- DEBUG BLOCK: SEEING WHAT THE BOT SEES ---
        if "Log Off" not in initial_page.text:
            print("❌ Landing Page Check Failed.")
            print("--- DEBUG DATA START ---")
            print(f"Status Code: {initial_page.status_code}")
            # This helps us see if there is a 'Cloudflare' or 'Access Denied' message
            print(f"HTML Snippet: {initial_page.text[:1000]}") 
            print("--- DEBUG DATA END ---")
            return None, "💔 Session Expired"
        
        print("✅ Step 3: Session Valid. Extracting token...")
        soup = BeautifulSoup(initial_page.text, 'html.parser')
        token = soup.find('input', {'name': '__RequestVerificationToken'})['value']
        
        payload = {
            "MinimumMarketCap": "50",
            "Select30": "false", 
            "Submit": "Get Stocks",
            "__RequestVerificationToken": token
        }
        
        response = session.post(url, data=payload, headers=headers, timeout=15)
        result_soup = BeautifulSoup(response.text, 'html.parser')
        tickers = [a.text.strip() for a in result_soup.find_all('a') if '/Screening/StockDetails/' in a.get('href', '')]
        
        return list(set(tickers)), "💚 Session Healthy"

    except Exception as e:
        return None, f"⚠️ Error: {str(e)}"

def run_strategy():
    tickers, status_msg = get_official_mf_tickers()
    if TELEGRAM_TOKEN:
        requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                     params={"chat_id": TELEGRAM_CHAT_ID, "text": f"💓 **Heartbeat**: {status_msg}"})
    
if __name__ == "__main__":
    run_strategy()
