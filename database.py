"""
FILE: database.py
FUNCTION: Manages all DB operations. Shared across all bots.
"""
import os
import psycopg2
import logging

def get_connection():
    """
    Retrieves the raw connection string and strips away any SQLAlchemy-specific 
    prefixes so psycopg2 can connect perfectly without throwing a DSN error.
    """
    url = os.getenv('DATABASE_URL', '')
    
    # Auto-convert SQLAlchemy dialect tags to standard Postgres URIs
    if url.startswith('postgresql+psycopg2://'):
        url = url.replace('postgresql+psycopg2://', 'postgresql://', 1)
        
    return psycopg2.connect(url)

def update_status(bot_name, status):
    """
    Updates the live runtime heartbeat and state inside the bot_status table.
    If the bot name doesn't exist yet, it safely creates the row.
    """
    with get_connection() as conn, conn.cursor() as cur:
        # 1. Attempt to update the existing bot's row heartbeat
        cur.execute("""
            UPDATE bot_status 
            SET status = %s, last_update = NOW() 
            WHERE bot_name = %s
        """, (status, bot_name))
        
        # 2. Fallback check: If the row doesn't exist, insert it fresh
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

def log_trade(bot_name, exchange, symbol, side, price, qty, order_id, fee=0.0):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO trades (bot_name, exchange, symbol, side, price, quantity, value, fee, order_id, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (bot_name, exchange, symbol, side, float(price), float(qty), float(price*qty), float(fee), str(order_id)))
        conn.commit()

def log_error(bot_name, error_msg):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO bot_errors (bot_name, error_message) VALUES (%s, %s)", (bot_name, str(error_msg)))
        conn.commit()
