"""
FILE: engine.py
FUNCTION: Pure math for grid level calculations.
"""
class GridEngine:
    def __init__(self, levels, step_percent):
        self.levels = levels
        self.step = step_percent / 100

    def calculate_levels(self, center_price):
        grid = []
        for i in range(1, self.levels + 1):
            grid.append(('buy', round(center_price * (1 - self.step * i), 8)))
            grid.append(('sell', round(center_price * (1 + self.step * i), 8)))
        return grid
