"""
FILE: exchange.py
FUNCTION: Manages connectivity, circuit breaking, and order execution.
"""
import ccxt
import time
import logging
from utils import log_trade # Import your centralized reporting tool

class ExchangeManager:
    def __init__(self, config):
        self.exchange = ccxt.okx(config)
        self.exchange.set_sandbox_mode(True)
        self.logger = logging.getLogger(__name__)

    def execute_with_backoff(self, func, *args, **kwargs):
        # ... (Insert your current _execute_with_backoff logic here)
        pass

    def place_order(self, side, symbol, price, qty):
        try:
            # 1. Execute the actual order through CCXT
            order = self.exchange.create_order(symbol, 'market', side, qty, price)
            
            # 2. Log to your dashboard ONLY after success
            log_trade(
                bot_name="Grok_Alpaca_Apex_v9_Final", # Or pass this in via config
                symbol=symbol,
                side=side,
                qty=float(qty),
                entry_price=float(price),
                order_id=order['id']
            )
            
            self.logger.info(f"✅ Order executed and logged: {symbol} {side}")
            return order
            
        except Exception as e:
            self.logger.error(f"❌ Order failed: {e}")
            return None
