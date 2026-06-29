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
        secret = os.getenv("OKX_API_SECRET", "")
        password = os.getenv("OKX_PASSPHRASE", "")
        sandbox = os.getenv("OKX_SANDBOX", "true").lower() in ("1", "true", "yes")

        missing = [name for name, val in [
            ("OKX_API_KEY", api_key), ("OKX_API_SECRET", secret), ("OKX_PASSPHRASE", password)
        ] if not val]
        if missing:
            raise ValueError(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                f"Set these in your deployment environment (e.g. Coolify env vars) "
                f"before starting the bot. OKX_PASSPHRASE is your API passphrase, "
                f"not your account login password."
            )

        # ccxt's default OKX hostname (www.okx.com) returns "API key
        # doesn't exist" (error 50119) for some regions/accounts even with
        # valid, freshly-created keys — a known ccxt issue where the
        # hostname it signs requests against doesn't match the regional
        # endpoint OKX actually validates the key on. OKX's own web UI
        # redirects to app.okx.com, and overriding ccxt's hostname to match
        # resolves it. Override via OKX_HOSTNAME if you hit this on a
        # different region/subdomain (e.g. OKX's EEA endpoint).
        hostname = os.getenv("OKX_HOSTNAME", "app.okx.com")

        self.exchange = ccxt.okx({
            'apiKey': api_key,
            'secret': secret,
            'password': password,
            'enableRateLimit': True,
            'hostname': hostname,
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
        Returns total account equity in USDT terms -- cash AND the current
        market value of any held crypto, using OKX's own totalEq figure.
        Used by the risk manager to check drawdown against the real
        account, not just theoretical grid math.

        FIX: previously only summed USDT cash (balance['USDT']['total']),
        which meant the drawdown check was blind to losses sitting in held
        BTC/etc inventory -- a real risk-management gap, not just a
        reporting one, since the bot could be down significantly in
        unrealized terms while this number looked unchanged.

        DIAGNOSTIC (temporary): logs the raw totalEq string and a
        per-currency eqUsd breakdown at INFO level so we can see exactly
        what OKX is sending, since a reported ~$5M figure has been
        confirmed wrong for a real account. Remove this logging once the
        root cause is found.
        """
        try:
            balance = self.execute_with_backoff(self.exchange.fetch_balance)
            data = balance.get('info', {}).get('data', [])

            usdt_total = balance.get('USDT', {}).get('total', 0) or 0
            print(f"🔍 [EQUITY DEBUG] Number of account entries in data[]: {len(data)}")
            for i, entry in enumerate(data):
                print(f"🔍 [EQUITY DEBUG] entry[{i}] raw totalEq: {entry.get('totalEq')!r}")
                details = entry.get('details', [])
                print(f"🔍 [EQUITY DEBUG] entry[{i}] has {len(details)} currency detail(s)")
                for d in details:
                    print(f"🔍 [EQUITY DEBUG]   ccy={d.get('ccy')!r} eq={d.get('eq')!r} "
                         f"eqUsd={d.get('eqUsd')!r} cashBal={d.get('cashBal')!r}")
            print(f"🔍 [EQUITY DEBUG] USDT-only total (fallback path): {usdt_total!r}")

            if data and data[0].get('totalEq'):
                result = float(data[0]['totalEq'])
                print(f"🔍 [EQUITY DEBUG] Returning totalEq-based result: {result}")
                return result
            # Fallback: USDT cash only, if totalEq isn't present for some reason
            print(f"🔍 [EQUITY DEBUG] No totalEq found, returning USDT-only fallback: {usdt_total}")
            return float(usdt_total)
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
