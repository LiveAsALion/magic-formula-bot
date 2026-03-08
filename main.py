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

# --- 2. THE SCREENER & HEARTBEAT ---
def get_official_mf_tickers():
    session = requests.Session()
    cookie_obj = requests.cookies.create_cookie(name="mfi", value=MF_COOKIE_VAL, domain="www.magicformulainvesting.com")
    session.cookies.set_cookie(cookie_obj)
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.magicformulainvesting.com/Screening/StockScreen"}
    
    try:
        url = "https://www.magicformulainvesting.com/Screening/StockScreen"
        initial_page = session.get(url, headers=headers)
        if "Log Off" not in initial_page.text:
            return None, "💔 Session Expired"
        
        soup = BeautifulSoup(initial_page.text, 'html.parser')
        token = soup.find('input', {'name': '__RequestVerificationToken'})['value']
        payload = {"MinimumMarketCap": "50", "Select30": "false", "Submit": "Get Stocks", "__RequestVerificationToken": token}
        
        response = session.post(url, data=payload, headers=headers)
        result_soup = BeautifulSoup(response.text, 'html.parser')
        tickers = [link.text.strip() for link in result_soup.find_all('a') if '/Screening/StockDetails/' in link.get('href', '')]
        return list(set(tickers)), "💚 Session Healthy"
    except:
        return None, "⚠️ Connection Error"

# --- 3. PERFORMANCE REPORTING ---
def send_monthly_report():
    """Generates a high-level summary of the account health."""
    try:
        account = trading_client.get_account()
        history = trading_client.get_portfolio_history(GetPortfolioHistoryRequest(period="1M", timeframe="1D"))
        
        equity_now = float(account.equity)
        pnl_pct = ((equity_now / float(account.last_equity)) - 1) * 100
        
        msg = (
            f"📅 **MONTHLY PERFORMANCE REPORT**\n"
            f"--- --- --- ---\n"
            f"💰 **Total Equity**: ${equity_now:,.2f}\n"
            f"📈 **Buying Power**: ${float(account.buying_power):,.2f}\n"
            f"📊 **Monthly Change**: {pnl_pct:+.2%}\n"
            f"🛠 **System Status**: Fully Operational"
        )
        send_telegram_msg(msg)
    except Exception as e:
        print(f"Report Error: {e}")

# --- 4. TREND FILTER ---
def is_above_200_ma(symbol):
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        request = StockBarsRequest(symbol_or_symbols=[symbol.replace('.', '-')], timeframe=TimeFrame.Day, start=start_date, end=end_date)
        bars = data_client.get_stock_bars(request).df
        return bars['close'].iloc[-1] > bars['close'].rolling(window=200).mean().iloc[-1]
    except: return False

# --- 5. MAIN SEQUENCE ---
def run_strategy():
    now = datetime.now()
    # Trigger report on the 1st of the month
    if now.day == 1:
        send_monthly_report()

    tickers, status_msg = get_official_mf_tickers()
    send_telegram_msg(f"💓 **Heartbeat**: {status_msg}")
    
    if not tickers: return

    final_picks = [t for t in tickers if is_above_200_ma(t)][:5]
    if not final_picks:
        send_telegram_msg("📊 Scan complete. Market trend is down; no new buys today.")
        return

    summary = "🚀 **Trades Executed**\n"
    for ticker in final_picks:
        try:
            trading_client.submit_order(MarketOrderRequest(symbol=ticker.replace('.', '-'), notional=CASH_PER_STOCK, side="buy", time_in_force="day"))
            summary += f"✅ **{ticker}**\n"
        except Exception as e: summary += f"❌ **{ticker}**: {e}\n"
    send_telegram_msg(summary)

def send_telegram_msg(text):
    if not TELEGRAM_TOKEN: return
    requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", params={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"})

if __name__ == "__main__":
    run_strategy()
