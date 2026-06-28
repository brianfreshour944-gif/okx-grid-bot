
       
"""
FILE: database.py
FUNCTION: Manages all DB operations. Shared across all bots.

FIX: log_trade() previously had a signature that nothing in the codebase
actually called correctly (exchange.py imported a totally different
log_trade from utils.py that never wrote to Postgres at all). This is now
the single source of truth and exchange.py calls it directly.
"""
import os
import psycopg2
import logging

logger = logging.getLogger(__name__)


def get_connection():
    """
    Retrieves the raw connection string and strips away any SQLAlchemy-specific
    prefixes so psycopg2 can connect perfectly without throwing a DSN error.
    """
    url = os.getenv('DATABASE_URL', '')
    if url.startswith('postgresql+psycopg2://'):
        url = url.replace('postgresql+psycopg2://', 'postgresql://', 1)
    return psycopg2.connect(url)


def ensure_schema():
    """
    Creates required tables if they don't already exist. Safe to call on
    every startup.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_status (
                bot_name TEXT PRIMARY KEY,
                status TEXT,
                last_update TIMESTAMP,
                session_start_time TIMESTAMP
            )
        """)
        cur.execute("ALTER TABLE bot_status ADD COLUMN IF NOT EXISTS starting_equity NUMERIC")
        cur.execute("ALTER TABLE bot_status ADD COLUMN IF NOT EXISTS live_equity NUMERIC")
        cur.execute("ALTER TABLE bot_status ADD COLUMN IF NOT EXISTS live_equity_updated_at TIMESTAMP")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id SERIAL PRIMARY KEY,
                bot_name TEXT,
                exchange TEXT,
                symbol TEXT,
                side TEXT,
                price NUMERIC,
                quantity NUMERIC,
                value NUMERIC,
                fee NUMERIC DEFAULT 0,
                order_id TEXT,
                timestamp TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_errors (
                id SERIAL PRIMARY KEY,
                bot_name TEXT,
                error_message TEXT,
                timestamp TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_events (
                id SERIAL PRIMARY KEY,
                bot_name TEXT,
                event_type TEXT,
                detail TEXT,
                timestamp TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()


def update_status(bot_name, status):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE bot_status
            SET status = %s, last_update = NOW()
            WHERE bot_name = %s
        """, (status, bot_name))

        if cur.rowcount == 0:
            cur.execute("""
                INSERT INTO bot_status (bot_name, status, last_update, session_start_time)
                VALUES (%s, %s, NOW(), NOW())
            """, (bot_name, status))
        conn.commit()


def check_status(bot_name):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM bot_status WHERE bot_name = %s", (bot_name,))
        row = cur.fetchone()
        return row[0] if row else 'RUNNING'


def report_equity(bot_name, current_equity):
    """
    Reports this bot's real account equity to the dashboard.
    starting_equity is set the first time a bot reports in and is never
    overwritten afterward. live_equity and live_equity_updated_at are
    overwritten on every call.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO bot_status (bot_name, starting_equity, live_equity, live_equity_updated_at, last_update)
            VALUES (%s, %s, %s, NOW(), NOW())
            ON CONFLICT (bot_name) DO UPDATE
            SET live_equity = EXCLUDED.live_equity,
                live_equity_updated_at = NOW(),
                last_update = NOW(),
                starting_equity = COALESCE(bot_status.starting_equity, EXCLUDED.starting_equity)
        """, (bot_name, float(current_equity), float(current_equity)))
        conn.commit()


def log_trade(bot_name, exchange, symbol, side, price, qty, order_id, fee=0.0):
    """
    Single source of truth for trade logging. price/qty must be non-null
    and positive or the row is rejected (mirrors the old validation that
    lived in utils.py, but now actually reaches the DB).
    """
    if price is None or qty is None or float(price) <= 0 or float(qty) <= 0:
        logger.warning(f"⚠️ Rejected trade log with invalid price/qty: price={price} qty={qty}")
        return
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO trades (bot_name, exchange, symbol, side, price, quantity, value, fee, order_id, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (bot_name, exchange, symbol, side, float(price), float(qty),
              float(price) * float(qty), float(fee), str(order_id)))
        conn.commit()


def log_error(bot_name, error_msg):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO bot_errors (bot_name, error_message) VALUES (%s, %s)",
                    (bot_name, str(error_msg)))
        conn.commit()


def log_event(bot_name, event_type, detail=""):
    """New: tracks recenters, circuit-breaker trips, halts, etc. so you
    can see in the dashboard WHY the bot behaved a certain way."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO bot_events (bot_name, event_type, detail) VALUES (%s, %s, %s)",
                    (bot_name, event_type, str(detail)))
        conn.commit()


def get_realized_pnl(bot_name):
    """
    Sums realized PnL from matched buy/sell pairs is non-trivial with a
    simple trades table (FIFO matching needed). For now this returns net
    cash flow (sells - buys), which approximates realized PnL once a full
    round trip has occurred. Good enough for a dashboard sanity check;
    not a substitute for proper accounting.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN side = 'sell' THEN value ELSE 0 END), 0) -
                COALESCE(SUM(CASE WHEN side = 'buy' THEN value ELSE 0 END), 0) AS net_cash_flow
            FROM trades WHERE bot_name = %s
        """, (bot_name,))
        row = cur.fetchone()
        return float(row[0]) if row else 0.0
