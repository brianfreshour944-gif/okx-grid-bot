"""
FILE: exchange.py
FUNCTION: Manages connectivity, circuit breaking, and order execution.

FIXES:
- Sandbox mode is now driven by OKX_SANDBOX env var (was hardcoded True,
  meaning real-money trading was impossible even by accident, but also
  meant you could never go live without editing code).
- log_trade now imported from database.py (the one that actually writes
  to Postgres) with the correct argument names, instead of the
  print-only stub in utils.py.
- Added get_equity_usdt() so risk.py can check drawdown against real
  account balance.
"""
import ccxt
import time
import logging
import os
import database as db

logger = logging.getLogger(__name__)


class ExchangeManager:
    def __init__(self):
        api_key = os.getenv("OKX_API_KEY", "")
        secret = os.getenv("OKX_SECRET", "")
        password = os.getenv("OKX_PASSWORD", "")
        sandbox = os.getenv("OKX_SANDBOX", "true").lower() in ("1", "true", "yes")

        missing = [name for name, val in [
            ("OKX_API_KEY", api_key), ("OKX_SECRET", secret), ("OKX_PASSWORD", password)
        ] if not val]
        if missing:
            raise ValueError(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                f"Set these in your deployment environment (e.g. Coolify env vars) "
                f"before starting the bot. OKX_PASSWORD is your API passphrase, "
                f"not your account login password."
            )

        self.exchange = ccxt.okx({
            'apiKey': api_key,
            'secret': secret,
            'password': password,
            'enableRateLimit': True
        })

        self.exchange.set_sandbox_mode(sandbox)
        self.sandbox = sandbox
        logger.info(f"📡 OKX Exchange Manager initialized. Sandbox mode: {sandbox}")
        if not sandbox:
            logger.warning("🔴 LIVE TRADING MODE — real funds are at risk.")

    def execute_with_backoff(self, func, *args, **kwargs):
        retries = 5
        delay = 1
        for i in range(retries):
            try:
                return func(*args, **kwargs)
            except ccxt.RateLimitExceeded as e:
                logger.warning(f"⚠️ Rate limit hit. Retrying in {delay}s... Error: {e}")
                time.sleep(delay)
                delay *= 2
            except ccxt.NetworkError as e:
                logger.warning(f"⚠️ Network issue. Retrying in {delay}s... Error: {e}")
                time.sleep(delay)
                delay *= 2
            except Exception as e:
                logger.error(f"❌ Unhandled exchange exception: {e}")
                raise e
        raise Exception("💥 Max retries exceeded on exchange execution.")

    def get_current_price(self, symbol=None):
        if not symbol:
            symbol = os.getenv("TRADING_SYMBOL", "BTC/USDT")
        try:
            ticker = self.execute_with_backoff(self.exchange.fetch_ticker, symbol)
            return float(ticker['last'])
        except Exception as e:
            logger.error(f"❌ Failed to fetch current price for {symbol}: {e}")
            raise e

    def get_equity_usdt(self):
        """
        Returns total account equity in USDT terms (free + used USDT balance).
        Used by the risk manager to check drawdown against the real account,
        not just theoretical grid math.
        """
        try:
            balance = self.execute_with_backoff(self.exchange.fetch_balance)
            usdt = balance.get('USDT', {}).get('total', 0) or 0
            return float(usdt)
        except Exception as e:
            logger.error(f"❌ Failed to fetch balance: {e}")
            raise e

    def place_order(self, side, symbol, price, qty, bot_name="okx_grid_bot"):
        """
        Executes market orders and logs confirmed fills to the database.
        Returns the order dict on success, None on failure (caller must
        check for None and NOT assume the order filled).
        """
        try:
            order = self.execute_with_backoff(
                self.exchange.create_order,
                symbol, 'market', side, qty
            )

            execution_price = order.get('price') or order.get('average') or price
            execution_qty = order.get('filled') or qty
            order_id = order.get('id', 'unknown')
            fee = 0.0
            if order.get('fee') and order['fee'].get('cost'):
                fee = float(order['fee']['cost'])

            db.log_trade(
                bot_name=bot_name,
                exchange="okx",
                symbol=symbol,
                side=side,
                price=float(execution_price),
                qty=float(execution_qty),
                order_id=order_id,
                fee=fee,
            )

            logger.info(f"✅ Order executed and logged: {symbol} {side} qty={execution_qty} @ {execution_price}")
            return order

        except Exception as e:
            logger.error(f"❌ Order deployment failed: {e}")
            db.log_error(bot_name, f"Order failed: {side} {symbol} qty={qty}: {e}")
            return None
