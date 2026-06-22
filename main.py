
"""
FILE: main.py
FUNCTION: Orchestrates the bot execution flow.

FIX: The previous version of this file only fetched price and wrote a
heartbeat to the DB — it never placed a single order. GridEngine was
imported but never used. This version actually trades the grid, with
risk.py guardrails to prevent unbounded drawdown.
"""
import time
import sys
import os

sys.stdout.reconfigure(line_buffering=True)

print("🚀 [STARTUP]: Initializing okx_grid_bot...")

try:
    from exchange import ExchangeManager
    from engine import GridEngine
    from risk import RiskManager
    import database as db
    print("✅ [STARTUP]: Modules and files imported successfully.")
except Exception as e:
    print(f"❌ [CRITICAL ERROR]: Failed during module imports: {e}")
    sys.exit(1)

BOT_NAME = "okx_grid_bot"
SYMBOL = os.getenv("TRADING_SYMBOL", "BTC/USDT")

# Grid configuration — all overridable via env so you can tune without
# editing code.
LEVELS = int(os.getenv("GRID_LEVELS", "3"))
STEP_PERCENT = float(os.getenv("GRID_STEP_PERCENT", "1.5"))
CAPITAL_USDT = float(os.getenv("GRID_CAPITAL_USDT", "500"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "5"))


def main():
    print("🤖 [STARTUP]: Starting main execution loop...")

    try:
        db.ensure_schema()
        ex = ExchangeManager()
        eng = GridEngine(levels=LEVELS, step_percent=STEP_PERCENT, capital_usdt=CAPITAL_USDT)
        risk = RiskManager()
        print(f"✅ [STARTUP]: Initialized. symbol={SYMBOL} levels={LEVELS} "
              f"step={STEP_PERCENT}% capital={CAPITAL_USDT} USDT")
    except Exception as e:
        print(f"❌ [CRITICAL ERROR]: Failed to initialize engines: {e}")
        sys.exit(1)

    last_price = None

    try:
        starting_equity = ex.get_equity_usdt()
        risk.set_starting_equity(starting_equity)
        print(f"💰 [STARTUP]: Starting equity recorded: {starting_equity:.2f} USDT")
    except Exception as e:
        print(f"⚠️ [STARTUP]: Could not fetch starting equity ({e}). "
              f"Drawdown circuit breaker will be disabled until balance is reachable.")

    while True:
        try:
            if db.check_status(BOT_NAME) == 'STOP':
                print("🛑 [STATUS]: Stop signal detected in database. Exiting loop.")
                break

            if risk.halted:
                db.update_status(BOT_NAME, f"HALTED: {risk.halt_reason}")
                print(f"⛔ [HALTED]: {risk.halt_reason}")
                time.sleep(POLL_SECONDS)
                continue

            price = ex.get_current_price(SYMBOL)
            now = time.time()
            print(f"📈 [TICK]: Current Price: {price}")

            # First tick: build the initial grid around current price.
            if not eng.grid:
                eng.build_grid(price)
                db.log_event(BOT_NAME, "GRID_BUILT", f"center={price} levels={LEVELS} step={STEP_PERCENT}%")
                print(f"🧮 [GRID]: Built grid around {price}")

            # Drawdown circuit breaker check (real account equity)
            try:
                equity = ex.get_equity_usdt()
                if risk.check_drawdown(equity, now):
                    db.log_event(BOT_NAME, "CIRCUIT_BREAKER", risk.halt_reason)
                    print(f"⛔ [CIRCUIT BREAKER]: {risk.halt_reason}")
                    db.update_status(BOT_NAME, f"HALTED: {risk.halt_reason}")
                    time.sleep(POLL_SECONDS)
                    continue
            except Exception as e:
                print(f"⚠️ [RISK CHECK]: Could not verify equity for drawdown check: {e}")

            # If price breaks out of the grid's range entirely, halt and
            # wait for a human. We deliberately do NOT recenter here:
            # recentering on breakout means the bot keeps buying into a
            # trend that's left the range it was designed for, which is
            # the main mechanism that turns a grid bot's normal small
            # losses into a large, unbounded drawdown. Better to stop and
            # let a person decide whether to redeploy the grid at a new
            # range once things stabilize.
            if eng.is_out_of_range(price):
                reason = (f"Price {price} broke out of grid range "
                          f"{eng.range_bounds()}. Halting — redeploy manually "
                          f"once you've reviewed the market.")
                risk.halt(reason)
                db.log_event(BOT_NAME, "HALT_BREAKOUT", reason)
                print(f"⛔ [HALT]: {reason}")
                db.update_status(BOT_NAME, f"HALTED: {reason}")
                time.sleep(POLL_SECONDS)
                continue

            # Check for crossed grid levels since last tick
            if last_price is not None:
                crossed = eng.crossed_levels(price, last_price)
                for lvl in crossed:
                    if lvl.side == 'buy':
                        position_usdt = eng.filled_buy_qty_total() * price
                        level_usdt = lvl.qty * lvl.price
                        if not risk.can_open_position(position_usdt, level_usdt):
                            print(f"🚫 [RISK]: Skipping buy at {lvl.price} — would exceed "
                                  f"max position ({risk.max_position_usdt} USDT)")
                            db.log_event(BOT_NAME, "RISK_SKIP_BUY",
                                         f"price={lvl.price} position_would_be={position_usdt + level_usdt:.2f}")
                            continue
                    else:
                        # Spot trading: can't sell more than we currently hold.
                        # filled_buy_qty_total() tracks unmatched buys (our
                        # actual base-asset inventory from this bot's own fills).
                        held_qty = eng.filled_buy_qty_total()
                        if lvl.qty > held_qty:
                            print(f"🚫 [RISK]: Skipping sell at {lvl.price} — would require "
                                  f"shorting (hold {held_qty:.6f}, level wants {lvl.qty:.6f})")
                            db.log_event(BOT_NAME, "RISK_SKIP_SELL",
                                         f"price={lvl.price} held={held_qty:.6f} requested={lvl.qty:.6f}")
                            continue

                    order = ex.place_order(lvl.side, SYMBOL, lvl.price, lvl.qty, bot_name=BOT_NAME)
                    if order is not None:
                        eng.mark_filled(lvl, order.get('id', 'unknown'))
                        print(f"✅ [FILL]: {lvl.side} {lvl.qty} @ {lvl.price}")

            last_price = price
            db.update_status(BOT_NAME, 'RUNNING')

        except Exception as e:
            print(f"⚠️ [LOOP ERROR]: Something went wrong inside the main loop: {e}")
            try:
                db.log_error(BOT_NAME, str(e))
            except Exception:
                pass

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
