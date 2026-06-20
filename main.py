THIS_IS_A_TEST_SYNTAX_ERROR_TO_FIND_COOLIFY !!!
"""
FILE: main.py
FUNCTION: Orchestrates the bot execution flow.
"""
import time
import sys
import os

# Force Python to flush logs immediately
sys.stdout.reconfigure(line_buffering=True)

print("🚀 [STARTUP]: Initializing okx_grid_bot...")

try:
    from exchange import ExchangeManager
    from engine import GridEngine
    import database as db
    print("✅ [STARTUP]: Modules and files imported successfully.")
except Exception as e:
    print(f"❌ [CRITICAL ERROR]: Failed during module imports: {e}")
    sys.exit(1)

def main():
    print("🤖 [STARTUP]: Starting main execution loop...")
    
    try:
        # Fixed the broken {...} placeholder syntax. 
        # This will look for your API keys setup in your ExchangeManager
        ex = ExchangeManager() 
        eng = GridEngine(levels=3, step_percent=4.0)
        print("✅ [STARTUP]: ExchangeManager and GridEngine initialized.")
    except Exception as e:
        print(f"❌ [CRITICAL ERROR]: Failed to initialize engines: {e}")
        sys.exit(1)
        
    while True:
        try:
            # Match the exact name used in your Postgres database: 'okx_grid_bot'
            if db.check_status('okx_grid_bot') == 'STOP':
                print("🛑 [STATUS]: Stop signal detected in database. Exiting loop.")
                break
                
            price = ex.get_current_price()
            print(f"📈 [TICK]: Current Price: {price}")
            
            # Update the database session timestamp to show it's active
            db.update_status('okx_grid_bot', 'RUNNING')
            
        except Exception as e:
            print(f"⚠️ [LOOP ERROR]: Something went wrong inside the main loop: {e}")
            
        time.sleep(5)

if __name__ == "__main__":
    main()
