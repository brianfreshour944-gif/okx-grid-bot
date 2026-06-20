"""
FILE: exchange.py
FUNCTION: Manages connectivity, circuit breaking, and order execution.
"""
import ccxt
import time
import logging
import os
from utils import log_trade

class ExchangeManager:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Pull keys from Coolify Environment Variables dynamically
        api_key = os.getenv("OKX_API_KEY", "")
        secret = os.getenv("OKX_SECRET", "")
        password = os.getenv("OKX_PASSWORD", "")

        # Initialize OKX connection
        self.exchange = ccxt.okx({
            'apiKey': api_key,
            'secret': secret,
            'password': password,
            'enableRateLimit': True
        })
        
        # Use sandbox/demo trading mode by default
        self.exchange.set_sandbox_mode(True)
        self.logger.info("📡 OKX Exchange Manager initialized in Sandbox Mode.")

    def execute_with_backoff(self, func, *args, **kwargs):
        """
        Executes an exchange function with an exponential backoff loop 
        to gracefully handle network hiccups or rate limits.
        """
        retries = 5
        delay = 1
        for i in range(retries):
            try:
                return func(*args, **kwargs)
            except ccxt.RateLimitExceeded as e:
                self.logger.warning(f"⚠️ Rate limit hit. Retrying in {delay}s... Error: {e}")
                time.sleep(delay)
                delay *= 2
            except ccxt.NetworkError as e:
                self.logger.warning(f"⚠️ Network issue. Retrying in {delay}s... Error: {e}")
                time.sleep(delay)
                delay *= 2
            except Exception as e:
                self.logger.error(f"❌ Unhandled exchange exception: {e}")
                raise e
        raise Exception("💥 Max retries exceeded on exchange execution.")

    def get_current_price(self, symbol=None):
        """
        Fetches the latest ticker price from the exchange.
        Defaults to the TRADING_SYMBOL environment variable or BTC/USDT.
        """
        if not symbol:
            symbol = os.getenv("TRADING_SYMBOL", "BTC/USDT")
            
        try:
            ticker = self.execute_with_backoff(self.exchange.fetch_ticker, symbol)
            return float(ticker['last'])
        except Exception as e:
            self.logger.error(f"❌ Failed to fetch current price for {symbol}: {e}")
            raise e

    def place_order(self, side, symbol, price, qty):
        """
        Executes market orders and routes confirmation data to utils.log_trade
        """
        try:
            # 1. Execute the actual order through CCXT using our backoff protection
            # Market orders do not strictly require a price parameter for execution
            order = self.execute_with_backoff(
                self.exchange.create_order, 
                symbol, 'market', side, qty
            )
            
            # Fetch execution price from the order response, fallback to target price
            execution_price = order.get('price', price) or price
            
            # 2. Log to your dashboard ONLY after verified success
            # Matches parameters expected by your current utils.py exactly
            log_trade(
                bot_name="okx_grid_bot", 
                symbol=symbol,
                side=side,
                qty=float(qty),
                entry_price=float(execution_price)
            )
            
            self.logger.info(f"✅ Order executed and logged: {symbol} {side}")
            return order
            
        except Exception as e:
            self.logger.error(f"❌ Order deployment failed: {e}")
            return None
