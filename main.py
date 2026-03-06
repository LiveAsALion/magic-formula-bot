import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.requests import MarketOrderRequest, TrailingStopOrderRequest, GetPortfolioHistoryRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# --- 1. CONFIGURATION (READING GITHUB SECRETS) ---
# These commands tell the bot to look in your GitHub 'Secrets' for the keys
API_KEY = os.getenv('ALPACA_API_KEY')
SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

PORTFOLIO_SIZE = 5 
CASH_PER_STOCK = 1000 
TRAIL_PERCENT = 10.0 

# Top Momentum-Enhanced Magic Formula Picks (March 2026)
value_candidates = ["GDDY", "EXPE", "BKNG", "GIB", "CTSH", "YOU", "ADBE"]

# Initialize Alpaca Clients
trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

# --- 2. NOTIFICATION SYSTEM ---
def send_telegram_msg(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram keys missing. Skipping notification.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.get(url, params=params)
    except Exception as e:
        print(f"Telegram error: {e}")

# --- 3. THE STRATEGY ENGINE ---
def get_6m_momentum(symbol):
    """Calculates if the stock has gone up over the last 6 months."""
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=180)
        request = StockBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame.Day, start=start_date, end=end_date)
        bars = data_client.get_stock_bars(request).df
        # Formula: (Current Price / Price 180 days ago) - 1
        return (bars['close'].iloc[-1] / bars['close'].iloc[0]) - 1
    except:
        return -99 # Skip stocks with errors

def run_strategy():
    summary = "🚨 **Magic Momentum Execution Report**\n\n"
    
    # Filter candidates for positive momentum
    scored_list = []
    for ticker in value_candidates:
        score = get_6m_momentum(ticker)
        if score > 0:
            scored_list.append({'ticker': ticker, 'score': score})
    
    # Sort by strongest momentum and pick top 5
    top_picks = pd.DataFrame(scored_list).sort_values(by='score', ascending=False).head(PORTFOLIO_SIZE)
    
    if top_picks.empty:
        send_telegram_msg("⚠️ No stocks met the momentum criteria today.")
        return

    # Execute Trades
    for ticker in top_picks['ticker']:
        try:
            # Step A: Submit Market Buy Order
            buy_order = trading_client.submit_order(MarketOrderRequest(
                symbol=ticker, notional=CASH_PER_STOCK, side=OrderSide.BUY, time_in_force=TimeInForce.DAY
            ))
            
            # Step B: Wait for the trade to finish processing
            time.sleep(5) 
            
            # Step C: Attach Trailing Stop for protection
            pos = trading_client.get_open_position(ticker)
            trading_client.submit_order(TrailingStopOrderRequest(
                symbol=ticker, qty=pos.qty, side=OrderSide.SELL, 
                time_in_force=TimeInForce.GTC, trail_percent=TRAIL_PERCENT
            ))
            summary += f"✅ **{ticker}**: Bought & Protected ({TRAIL_PERCENT}% Trail)\n"
            
        except Exception as e:
            summary += f"❌ **{ticker}**: Order Failed. Error: {str(e)}\n"

    # Portfolio Health Snapshot
    try:
        history = trading_client.get_portfolio_history(GetPortfolioHistoryRequest(period="1M", timeframe="1D"))
        summary += f"\n📈 **Account Performance (1M):** {history.profit_loss_pct[-1]:.2%}"
    except:
        pass

    send_telegram_msg(summary)

if __name__ == "__main__":
    run_strategy()
    
