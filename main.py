import pandas as pd
from datetime import datetime, timedelta
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.requests import MarketOrderRequest, TrailingStopOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# --- 1. CONFIGURATION ---
API_KEY = "YOUR_API_KEY"
SECRET_KEY = "YOUR_SECRET_KEY"
PORTFOLIO_SIZE = 5  # Number of stocks to buy
CASH_PER_STOCK = 1000  # Dollar amount per position
TRAIL_PERCENT = 10.0  # % drop to trigger exit

# Current Magic Formula Leaders (March 2026)
# Sourced from high Earnings Yield + high ROIC screens
value_candidates = ["EXPE", "BKNG", "GDDY", "YOU", "ECPG", "CTSH", "GIB", "ADBE"]

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

# --- 2. MOMENTUM FILTERING ENGINE ---
def get_6m_momentum(symbol):
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=180)
        request = StockBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame.Day, start=start_date, end=end_date)
        bars = data_client.get_stock_bars(request).df
        return (bars['close'].iloc[-1] / bars['close'].iloc[0]) - 1
    except:
        return -99  # Skip if data error

# --- 3. MASTER EXECUTION ---
def run_magic_momentum_strategy():
    print(f"--- Starting Strategy Execution: {datetime.now().strftime('%Y-%m-%d')} ---")
    
    # Step A: Rank by Momentum
    scored_list = []
    for ticker in value_candidates:
        score = get_6m_momentum(ticker)
        if score > 0: # Only buy if momentum is positive
            scored_list.append({'ticker': ticker, 'score': score})
    
    top_picks = pd.DataFrame(scored_list).sort_values(by='score', ascending=False).head(PORTFOLIO_SIZE)
    print(f"Top {PORTFOLIO_SIZE} Momentum-Value Picks:\n{top_picks}\n")

    # Step B: Execute Trades with Protection
    for ticker in top_picks['ticker']:
        try:
            # 1. Buy Order
            buy_order = trading_client.submit_order(MarketOrderRequest(
                symbol=ticker, notional=CASH_PER_STOCK, side=OrderSide.BUY, time_in_force=TimeInForce.DAY
            ))
            print(f"BUY SUCCESS: {ticker}")

            # 2. Trailing Stop Order (The 'Insurance Policy')
            # Wait a moment for the buy to fill so we have the 'qty'
            import time; time.sleep(2) 
            position = trading_client.get_open_position(ticker)
            
            trading_client.submit_order(TrailingStopOrderRequest(
                symbol=ticker, qty=position.qty, side=OrderSide.SELL, 
                time_in_force=TimeInForce.GTC, trail_percent=TRAIL_PERCENT
            ))
            print(f"STOP LOSS ACTIVE: {ticker} at {TRAIL_PERCENT}% trail.")

        except Exception as e:
            print(f"ORDER FAILED for {ticker}: {e}")

if __name__ == "__main__":
    run_magic_momentum_strategy()
