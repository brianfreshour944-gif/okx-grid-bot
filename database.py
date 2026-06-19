"""
FILE: database.py
FUNCTION: Manages all DB operations. Shared across all bots.
"""
import os
import psycopg2
import logging

def get_connection():
    return psycopg2.connect(os.getenv('DATABASE_URL'))

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

def check_status(bot_name):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM bot_status WHERE bot_name = %s", (bot_name,))
        row = cur.fetchone()
        return row[0] if row else 'RUNNING'
