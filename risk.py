"""
FILE: risk.py
FUNCTION: Guardrails that sit on top of the grid logic. This is what
          was missing entirely from the original bot. Recentering on
          breakout (chasing a trend) is the single biggest cause of
          runaway drawdown in grid bots, so everything here exists to
          cap how much damage a bad trend can do before the bot stops
          itself.
"""
import os


class RiskManager:
    def __init__(self):
        # Max USDT value of base-asset inventory the bot is allowed to hold
        # at once (sum of unmatched filled buys). Prevents unlimited
        # accumulation during a downtrend.
        self.max_position_usdt = float(os.getenv("MAX_POSITION_USDT", "500"))

        # Max number of times the grid is allowed to recenter in one
        # session before the bot halts and waits for a human.
        # NOTE: recentering has been removed from main.py — once price
        # breaks out of the grid range, the bot halts and waits for a
        # human to decide whether to redeploy at a new range. This field
        # is kept only for backwards compatibility with old configs.
        self.max_recenters = int(os.getenv("MAX_RECENTERS", "0"))

        # If realized + unrealized loss since session start exceeds this
        # percent of starting capital, halt trading entirely.
        self.max_drawdown_percent = float(os.getenv("MAX_DRAWDOWN_PERCENT", "10"))

        self.session_start_equity = None
        self.halted = False
        self.halt_reason = None

    def set_starting_equity(self, equity_usdt: float):
        if self.session_start_equity is None:
            self.session_start_equity = equity_usdt

    def check_drawdown(self, current_equity_usdt: float, now: float) -> bool:
        """Returns True (and halts) if drawdown exceeds the configured limit."""
        if self.session_start_equity is None or self.halted:
            return self.halted
        loss_percent = (self.session_start_equity - current_equity_usdt) / self.session_start_equity * 100
        if loss_percent >= self.max_drawdown_percent:
            self.halted = True
            self.halt_reason = (
                f"Max drawdown hit: {loss_percent:.2f}% >= {self.max_drawdown_percent}% "
                f"(start equity {self.session_start_equity:.2f}, now {current_equity_usdt:.2f})"
            )
        return self.halted

    def can_open_position(self, current_position_usdt: float, additional_usdt: float) -> bool:
        return (current_position_usdt + additional_usdt) <= self.max_position_usdt

    def halt(self, reason: str):
        self.halted = True
        self.halt_reason = reason
