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
    
    # Precise URL for the screening tool
    url = "https://www.magicformulainvesting.com/Screening/StockScreen"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Referer": "https://www.magicformulainvesting.com/",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1"
    }
    
    if not MF_COOKIE_VAL:
        return None, "❌ Error: MF_COOKIE Secret is missing."

    # Sanitization: Strip spaces and remove any accidental quotes
    clean_cookie = MF_COOKIE_VAL.strip().replace('"', '').replace("'", "")

    cookie_obj = requests.cookies.create_cookie(
        name="mfi", 
        value=clean_cookie, 
        domain="
