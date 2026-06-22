# okx-grid-bot

A grid trading bot for OKX. Watches price, places market orders when grid
levels are crossed, and halts (rather than chasing the market) if price
breaks out of the configured range or losses exceed a drawdown limit.

## What was wrong before

The previous version of this bot **never actually traded**. `main.py` only
fetched price and wrote a heartbeat to the database; `GridEngine` and
`ExchangeManager.place_order` were never called from the main loop. On top
of that:

- `exchange.py` called a `log_trade` from `utils.py` that only printed to
  stdout and never wrote to Postgres — so even if trades had been placed,
  none would show up in the `trades` table.
- `database.py`'s own `log_trade` had a different signature that nothing
  called correctly.
- Sandbox mode was hardcoded `True`, so this code could never place real
  orders even by accident — useful to know if you were trying to explain
  real account losses from this exact code.
- There was no stop-loss, no max position size, and no circuit breaker
  anywhere in the code.

## What changed

- **`main.py`** now actually runs the grid: builds levels around the
  starting price, detects when price crosses a level, and places real
  orders through `ExchangeManager`.
- **`engine.py`** is now stateful — it tracks which levels are filled, and
  exposes `is_out_of_range()` so the bot knows when price has left the
  grid entirely.
- **No recentering on breakout.** If price leaves the grid's range, the
  bot halts and waits for a human, rather than rebuilding the grid around
  the new price and continuing to trade. Recentering into a trend is the
  most common way grid bots turn a normal small loss into a large,
  unbounded drawdown — see `simulate.py` for a side-by-side comparison.
- **`risk.py`** (new) adds:
  - A max position size cap (`MAX_POSITION_USDT`) — refuses to open new
    buy levels once inventory value exceeds this.
  - A max drawdown circuit breaker (`MAX_DRAWDOWN_PERCENT`) checked
    against real account equity each tick — halts all trading if tripped.
- **Spot short-sell guard** — the bot will not place a sell order for more
  quantity than it actually holds from its own filled buys.
- **`database.py`** — `log_trade` is now the single source of truth, has a
  consistent signature, and is actually called by `exchange.py`. Added
  `ensure_schema()` (creates tables on first run) and `log_event()` for
  recording halts/circuit-breaker trips so you can see *why* the bot
  stopped from the dashboard.
- **`exchange.py`** — sandbox mode is now driven by `OKX_SANDBOX` (default
  `true`), not hardcoded. `place_order` logs the actual fill price/qty/fee
  from the order response, not just the target price.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `OKX_API_KEY`, `OKX_SECRET`, `OKX_PASSWORD` | — | OKX API credentials |
| `OKX_SANDBOX` | `true` | Set to `false` to trade with real funds |
| `TRADING_SYMBOL` | `BTC/USDT` | Market to trade |
| `GRID_LEVELS` | `3` | Number of buy levels below center (and sell levels above) |
| `GRID_STEP_PERCENT` | `1.5` | Spacing between adjacent grid lines, in percent |
| `GRID_CAPITAL_USDT` | `500` | Total capital split evenly across all grid levels |
| `MAX_POSITION_USDT` | `500` | Hard cap on inventory value before new buys are refused |
| `MAX_DRAWDOWN_PERCENT` | `10` | Halts all trading if account equity drops this much from session start |
| `POLL_SECONDS` | `5` | How often to check price |
| `DATABASE_URL` | — | Postgres connection string |

## Files

- `main.py` — trading loop
- `engine.py` — grid math + level-fill tracking (pure logic, no I/O)
- `risk.py` — position size cap + drawdown circuit breaker (pure logic, no I/O)
- `exchange.py` — OKX connectivity via ccxt
- `database.py` — Postgres logging (trades, status, errors, events)
- `test_engine.py` — unit tests for `engine.py` and `risk.py`
- `simulate.py` — synthetic price-path simulation comparing old
  (no-halt/recenter) vs. new (halt-on-breakout) behavior during a crash

## Running tests

```
pip install pytest --break-system-packages
python3 -m pytest test_engine.py -v
python3 simulate.py
```

## Important caveats

- This still places **market orders**, not limit orders, when a level is
  crossed. You'll pay the taker fee and get some slippage on every fill —
  factor that into your step size (too tight a grid relative to fees +
  slippage will lose money on volume alone, even in a perfectly ranging
  market).
- `get_realized_pnl()` in `database.py` is a simple net-cash-flow estimate
  (sells minus buys), not true FIFO-matched realized P&L. Treat it as a
  sanity check, not an accounting source of truth.
- The drawdown circuit breaker checks against real exchange equity, which
  means it depends on `fetch_balance` succeeding. If that call fails
  repeatedly, the breaker can't see real losses — the bot will log a
  warning each tick but keep trading. Don't treat this as a substitute for
  occasionally checking the account yourself.
- Halting on breakout means a strongly trending market will leave the bot
  idle (and out of new trades) until you manually redeploy — that's
  intentional, but it does mean the bot won't capture trend-following
  profit. Grid bots are a range-trading strategy; this isn't a trend
  strategy and the rewrite doesn't try to make it one.
