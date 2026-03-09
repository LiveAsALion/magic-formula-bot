import os
import time
import requests
import pandas as pd
import yfinance as yf
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
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

CASH_PER_STOCK = 1000
TRAIL_PERCENT = 10.0

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

# --- 2. THE MAGIC FORMULA ENGINE ---
def get_magic_formula_picks():
    print("🔭 Scanning S&P 500 universe for Magic Formula candidates...")
    try:
        # Step 1: Get the S&P 500 list from Wikipedia
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        table = pd.read_html(url, attrs={'id': 'constituents'})[0]
        tickers = table['Symbol'].str.replace('.', '-', regex=True).tolist()
        
        # We'll analyze the top 50 to keep the script fast
        universe = tickers[:50]
        scored_data = []
        
        for symbol in universe:
            try:
                stock = yf.Ticker(symbol)
                info = stock.info
                
                # Formula Component 1: Earnings Yield (EBIT / Enterprise Value)
                # We use EBITDA as a proxy for EBIT for reliability
                ebitda = info.get('ebitda', 0)
                ev = info.get('enterpriseValue', 1)
                earnings_yield = ebitda / ev if ev > 0 else 0
                
                # Formula Component 2: Return on Assets (ROA)
                roa = info.get('returnOnAssets', 0)
                
                if earnings_yield > 0 and roa > 0:
                    scored_data.append({'ticker': symbol, 'ey': earnings_yield, 'roa': roa})
                
                time.sleep(0.1) # Be polite to the API
            except:
                continue
        
        df = pd.DataFrame(scored_data)
        # Rank them (Lower is better rank)
        df['ey_rank'] = df['ey'].rank(ascending=False)
        df['roa_rank'] = df['roa'].rank(ascending=False)
        df['combined_rank'] = df['ey_rank'] + df['roa_rank']
        
        picks = df.sort_values('combined_rank').head(15)['ticker'].tolist()
        print(f"✅ Found {len(picks)} candidates via local calculation.")
        return picks
    except Exception as e:
        print(f"⚠️ Screening Error: {e}")
        return []

# --- 3. TREND FILTER (200-MA) ---
def is_above_200_ma(symbol):
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        request = StockBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame.Day, start=start_date, end=end_date)
        bars = data_client.get_stock_bars(request).df
        current_price = bars['close'].iloc[-1]
        ma200 = bars['close'].rolling(window=200).mean().iloc[-1]
        return current_price > ma200
    except:
        return False

# --- 4. EXECUTION ---
def run_strategy():
    print("🚀 Starting Trawler Run...")
    candidates = get_magic_formula_picks()
    
    if not candidates:
        send_telegram_msg("⚠️ **System Error**: Failed to calculate Magic Formula picks.")
        return

    # Filter for the 200-MA Momentum
    final_picks = [t for t in candidates if is_above_200_ma(t)][:5]
    
    status_msg = f"💚 System Healthy. Scanned {len(candidates)} stocks. Found {len(final_picks)} trending picks."
    send_telegram_msg(f"💓 **Heartbeat**: {status_msg}")

    if not final_picks:
        send_telegram_msg("📊 Scan complete. No trending stocks found today.")
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
                symbol=ticker, qty=pos.qty, side=OrderSide.SELL, time_in_force=TimeInForce.GTC, trail_percent=TRAIL_PERCENT
            ))
            summary += f"✅ **{ticker}**\n"
        except Exception as e:
            summary += f"❌ **{ticker}**: {e}\n"
    
    send_telegram_msg(summary)

def send_telegram_msg(text):
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.get(url, params={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)

if __name__ == "__main__":
    run_strategy()
