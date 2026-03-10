import os
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderStatus, OrderType

# --- CONFIGURATION ---
API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

# Initialize Alpaca TradingClient
trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)

def cancel_all_trailing_stops():
    print("🚀 Starting Trailing Stop Cancellation...")
    cancelled_count = 0
    errors_count = 0

    try:
        # Get all open orders
        open_orders = trading_client.get_orders(status=OrderStatus.OPEN)
        
        print(f"Found {len(open_orders)} open orders.")

        for order in open_orders:
            # Check if the order is a trailing stop order
            if order.order_type == OrderType.TRAILING_STOP:
                print(f"Attempting to cancel trailing stop order {order.id} for {order.symbol}...")
                try:
                    trading_client.cancel_order(order.id)
                    print(f"✅ Successfully cancelled trailing stop order {order.id} for {order.symbol}.")
                    cancelled_count += 1
                except Exception as e:
                    print(f"❌ Error cancelling order {order.id} for {order.symbol}: {e}")
                    errors_count += 1
            else:
                print(f"Skipping non-trailing stop order {order.id} for {order.symbol} (Type: {order.order_type}).")

    except Exception as e:
        print(f"An error occurred while fetching or cancelling orders: {e}")
        errors_count += 1

    print("--- Cancellation Summary ---")
    print(f"Total trailing stop orders cancelled: {cancelled_count}")
    print(f"Errors encountered: {errors_count}")
    print("✅ Trailing Stop Cancellation Complete.")

if __name__ == "__main__":
    cancel_all_trailing_stops()
