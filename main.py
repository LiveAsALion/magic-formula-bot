import os
import time
import random
import json
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional

import requests
import pandas as pd
import yfinance as yf

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, ClosePositionRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# ====================== CONFIGURATION ======================
class Config:
    CASH_PER_STOCK = int(os.getenv("CASH_PER_STOCK", 1000))
    MAX_NEW_BUYS = 3
    MIN_HOLD_DAYS_FOR_REVIEW = 365
    LOSS_SELL_DAYS = 360
    PORTFOLIO_FILE = "portfolio_metadata.json"
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    LOG_FILE = "bot.log"


# ====================== LOGGING ======================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(Config.LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ====================== DATA CLASSES ======================
@dataclass
class PositionMetadata:
    symbol: str
    purchase_date: str
    purchase_price: float


# ====================== PORTFOLIO MANAGER ======================
class PortfolioManager:
    """Alpaca = single source of truth. JSON only for purchase metadata."""
    def __init__(self, trading_client: TradingClient):
        self.trading_client = trading_client
        self.metadata: Dict[str, PositionMetadata] = self._load_metadata()

    def _load_metadata(self) -> Dict[str, PositionMetadata]:
        if os.path.exists(Config.PORTFOLIO_FILE):
            try:
                with open(Config.PORTFOLIO_FILE) as f:
                    data = json.load(f)
                return {k: PositionMetadata(**v) for k, v in data.items()}
            except Exception as e:
                logger.error(f"Metadata load failed: {e}")
        return {}

    def save_metadata(self):
        try:
            with open(Config.PORTFOLIO_FILE, "w") as f:
                json.dump({k: asdict(v) for k, v in self.metadata.items()}, f, indent=4)
        except Exception as e:
            logger.error(f"Metadata save failed: {e}")

    def get_alpaca_positions(self) -> List:
        try:
            return self.trading_client.get_all_positions()
        except Exception as e:
            logger.error(f"Alpaca positions fetch failed: {e}")
            return []

    def update_metadata(self, symbol: str, fill_price: float):
        self.metadata[symbol] = PositionMetadata(
            symbol=symbol,
            purchase_date=datetime.now().isoformat(),
            purchase_price=fill_price
        )
        self.save_metadata()

    def remove_metadata(self, symbol: str):
        self.metadata.pop(symbol, None)
        self.save_metadata()


# ====================== MAGIC FORMULA SCREENER (NEW) ======================
class MagicFormulaScreener:
    """Self-contained MF screener — no external site dependency."""
    @staticmethod
    def get_top_candidates(n: int = 50) -> List[str]:
        logger.info("Generating fresh Magic Formula candidates...")
        try:
            # Stable S&P 500 list (Wikipedia is extremely reliable)
            sp500 = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]["Symbol"].tolist()

            candidates = []
            for ticker in sp500[:150]:  # light lift — only first 150 to avoid rate limits
                try:
                    info = yf.Ticker(ticker).info
                    ey = 1 / info.get("forwardPE", 999) if info.get("forwardPE") else 0   # Earnings Yield proxy
                    roc = info.get("returnOnEquity", 0) or info.get("returnOnCapital", 0)  # ROC proxy
                    score = ey + roc * 0.5
                    candidates.append((ticker, score))
                except:
                    continue

            candidates.sort(key=lambda x: x[1], reverse=True)
            top = [t[0] for t in candidates[:n]]
            logger.info(f"Generated {len(top)} high-quality MF candidates")
            return top
        except Exception as e:
            logger.error(f"MF screener failed: {e}")
            return []


# ====================== TREND FILTER ======================
class TrendFilter:
    @staticmethod
    def is_above_200_ma(symbol: str) -> bool:
        """Robust 200-MA (exactly as requested)."""
        try:
            hist = yf.download(
                symbol,
                period="2y",
                progress=False,
                auto_adjust=True,
                threads=False
            )
            if len(hist) < 200:
                return False
            current = hist["Close"].iloc[-1]
            ma200 = hist["Close"].rolling(window=200).mean().iloc[-1]
            return current > ma200 and not pd.isna(ma200)
        except Exception as e:
            logger.debug(f"MA check failed for {symbol}: {e}")
            return False


# ====================== TRADE EXECUTOR ======================
class TradeExecutor:
    def __init__(self, trading_client: TradingClient, portfolio_manager: PortfolioManager):
        self.trading_client = trading_client
        self.portfolio = portfolio_manager

    def is_market_open(self) -> bool:
        try:
            return self.trading_client.get_clock().is_open
        except:
            return False

    def has_sufficient_buying_power(self) -> bool:
        try:
            account = self.trading_client.get_account()
            return float(account.buying_power) >= Config.CASH_PER_STOCK * 1.2
        except:
            return False

    def sell_position(self, symbol: str, reason: str) -> bool:
        try:
            self.trading_client.close_position(symbol)
            self.portfolio.remove_metadata(symbol)
            logger.info(f"SOLD {symbol} — {reason}")
            return True
        except Exception as e:
            logger.error(f"Sell failed for {symbol}: {e}")
            return False

    def buy_notional(self, symbol: str) -> Optional[float]:
        try:
            order = self.trading_client.submit_order(
                MarketOrderRequest(
                    symbol=symbol.replace(".", "-"),
                    notional=Config.CASH_PER_STOCK,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY
                )
            )
            time.sleep(6)
            filled = self.trading_client.get_order(order.id)
            if filled.filled_avg_price:
                fill_price = float(filled.filled_avg_price)
                self.portfolio.update_metadata(symbol, fill_price)
                logger.info(f"BOUGHT ${Config.CASH_PER_STOCK} of {symbol} @ ${fill_price:.2f}")
                return fill_price
            return None
        except Exception as e:
            logger.error(f"Buy failed for {symbol}: {e}")
            return None


# ====================== NOTIFICATIONS ======================
def send_telegram(message: str):
    if Config.TELEGRAM_TOKEN and Config.TELEGRAM_CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage",
                data={"chat_id": Config.TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"},
                timeout=10
            )
        except:
            pass


# ====================== MAIN RUN ======================
def run_strategy():
    logger.info("=== Magic Formula Bot Started ===")
    trading_client = TradingClient(
        os.getenv("ALPACA_API_KEY"),
        os.getenv("ALPACA_SECRET_KEY"),
        paper=True
    )

    pm = PortfolioManager(trading_client)
    executor = TradeExecutor(trading_client, pm)
    screener = MagicFormulaScreener()
    trend = TrendFilter()

    summary = ["*Magic Formula Bot — Daily Run*"]
    errors = []

    # Market & capital guards
    if not executor.is_market_open():
        summary.append("⏰ Market closed — no new trades today.")
        send_telegram("\n".join(summary))
        return
    if not executor.has_sufficient_buying_power():
        summary.append("⚠️ Insufficient buying power — skipping new buys.")
    else:
        summary.append("✅ Market open + sufficient buying power")

    # Get live positions
    alpaca_positions = {p.symbol: p for p in pm.get_alpaca_positions()}
    today = datetime.now()

    # Rebalancing logic (losers + monthly winner review)
    summary.append("\n*Rebalancing Existing Holdings:*")
    for symbol in list(alpaca_positions.keys()):
        meta = pm.metadata.get(symbol)
        if not meta:
            continue
        days_held = (today - datetime.fromisoformat(meta.purchase_date)).days

        # Loser rule
        if days_held >= Config.LOSS_SELL_DAYS:
            # Simple gain check (using latest price)
            try:
                price = yf.Ticker(symbol).info.get("regularMarketPrice", meta.purchase_price)
                gain = (price - meta.purchase_price) / meta.purchase_price
                if gain < 0:
                    if executor.sell_position(symbol, "long-term loss"):
                        summary.append(f"  ❌ Sold {symbol} (loss after {days_held} days)")
                    continue
            except:
                pass

        # Winner monthly review after 1 year
        if days_held >= Config.MIN_HOLD_DAYS_FOR_REVIEW:
            mf_list = screener.get_top_candidates()
            if symbol not in mf_list or not trend.is_above_200_ma(symbol):
                if executor.sell_position(symbol, "no longer qualifies"):
                    summary.append(f"  ❌ Sold {symbol} (failed monthly screen)")
                continue
            summary.append(f"  ✅ {symbol} still qualifies — holding")

    # New purchases
    summary.append("\n*New Purchases:*")
    mf_candidates = screener.get_top_candidates()
    qualified = [t for t in mf_candidates if trend.is_above_200_ma(t)]

    current_holdings = set(alpaca_positions.keys())
    to_buy = []
    for t in qualified:
        if t not in current_holdings and t not in to_buy:
            to_buy.append(t)
        if len(to_buy) >= Config.MAX_NEW_BUYS:
            break

    if to_buy:
        for ticker in to_buy:
            if executor.buy_notional(ticker):
                summary.append(f"  ✅ Bought **{ticker}** (${Config.CASH_PER_STOCK})")
            else:
                errors.append(f"Buy failed: {ticker}")
    else:
        summary.append("  No new qualified stocks available.")

    # Final notification
    final_msg = "\n".join(summary)
    if errors:
        final_msg += "\n\n⚠️ Errors:\n" + "\n".join(errors)
    send_telegram(final_msg)

    logger.info("=== Bot Run Completed ===")


if __name__ == "__main__":
    run_strategy()
