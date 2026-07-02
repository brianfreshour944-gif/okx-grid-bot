import requests
import os

# 1. Removed the trailing '...' from the parameters so Python doesn't crash
def log_trade(bot_name, symbol, side, qty, entry_price, pnl=None, exit_price=None):
    """
    Centralized validation and reporting logic for execution alerts.
    """
    # Validation logic to keep your database clean
    if entry_price is None or float(entry_price) <= 0:
        return 
    
    # 2. Expanded the payload dictionary cleanly using real variables
    payload = {
        "bot_name": bot_name,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "entry_price": entry_price,
        "pnl": pnl,
        "exit_price": exit_price
    }
    
    # 3. Print out the payload to your Coolify logs so you can see it working
    print(f"📊 [TRADE LOG SENT]: {payload}")
    
    # If you end up sending this to an external Discord/Telegram webhook or API later:
    # webhook_url = os.getenv("WEBHOOK_URL")
    # if webhook_url:
    #     requests.post(webhook_url, json=payload)
