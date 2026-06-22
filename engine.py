"""
FILE: engine.py
FUNCTION: Stateful grid math. Tracks levels, which ones are filled,
          and decides when the grid needs to recenter.

This module has NO network or DB calls. It is pure logic so it can be
unit tested and reasoned about without touching the exchange.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GridLevel:
    side: str          # 'buy' or 'sell'
    price: float
    qty: float
    filled: bool = False
    order_id: Optional[str] = None


class GridEngine:
    def __init__(self, levels: int, step_percent: float, capital_usdt: float):
        """
        levels: number of buy levels below center AND sell levels above center
                (so total grid lines = levels * 2)
        step_percent: spacing between adjacent grid lines, e.g. 1.5 = 1.5%
        capital_usdt: total capital budgeted across ALL levels. Split evenly.
        """
        if levels < 1:
            raise ValueError("levels must be >= 1")
        if step_percent <= 0:
            raise ValueError("step_percent must be > 0")
        if capital_usdt <= 0:
            raise ValueError("capital_usdt must be > 0")

        self.levels = levels
        self.step = step_percent / 100
        self.capital_usdt = capital_usdt
        self.center_price: Optional[float] = None
        self.grid: list[GridLevel] = []

    def build_grid(self, center_price: float):
        """
        (Re)build the grid around a center price. Capital is split evenly
        across all 2*levels lines, so qty per level = (capital / num_levels) / price.
        """
        self.center_price = center_price
        num_lines = self.levels * 2
        usdt_per_level = self.capital_usdt / num_lines

        grid = []
        for i in range(1, self.levels + 1):
            buy_price = round(center_price * (1 - self.step * i), 8)
            sell_price = round(center_price * (1 + self.step * i), 8)
            grid.append(GridLevel(side='buy', price=buy_price,
                                   qty=round(usdt_per_level / buy_price, 8)))
            grid.append(GridLevel(side='sell', price=sell_price,
                                   qty=round(usdt_per_level / sell_price, 8)))
        self.grid = grid
        return self.grid

    def calculate_levels(self, center_price: float):
        """Kept for backwards compatibility: returns (side, price) tuples only."""
        self.build_grid(center_price)
        return [(lvl.side, lvl.price) for lvl in self.grid]

    def range_bounds(self):
        """Returns (lowest_price, highest_price) the grid currently covers."""
        if not self.grid:
            return None, None
        prices = [lvl.price for lvl in self.grid]
        return min(prices), max(prices)

    def is_out_of_range(self, current_price: float) -> bool:
        """True if price has broken out of the grid's full range."""
        low, high = self.range_bounds()
        if low is None:
            return False
        return current_price < low or current_price > high

    def crossed_levels(self, current_price: float, last_price: float):
        """
        Returns unfilled levels that current_price has crossed since last_price.
        A buy level crosses when price moves DOWN through it.
        A sell level crosses when price moves UP through it.
        """
        crossed = []
        for lvl in self.grid:
            if lvl.filled:
                continue
            if lvl.side == 'buy' and last_price > lvl.price >= current_price:
                crossed.append(lvl)
            elif lvl.side == 'sell' and last_price < lvl.price <= current_price:
                crossed.append(lvl)
        return crossed

    def mark_filled(self, level: GridLevel, order_id: str):
        level.filled = True
        level.order_id = order_id

    def reset_fills(self):
        """Unfill all levels (used right after a recenter)."""
        for lvl in self.grid:
            lvl.filled = False
            lvl.order_id = None

    def filled_buy_qty_total(self) -> float:
        """Total base-asset quantity currently held from filled buy levels
        that have not yet had a matching sell. Used for position sizing checks."""
        return sum(lvl.qty for lvl in self.grid if lvl.side == 'buy' and lvl.filled)
