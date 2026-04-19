"""
Tick-by-tick simulator shared by all creatures.

The simulator owns:
  - the reef-wide crowding accumulator (exponentially decaying with
    CROWDING_HALF_LIFE); every filled order inflates it proportionally
    to notional, so many creatures acting the same tick pay more
  - the depth proxy (rolling stddev of mid * capital-independent constant)
  - the single clock (tick index) all creatures read

It deliberately does NOT own strategy logic, which lives on creatures.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
import numpy as np

from ..config import (CROWDING_HALF_LIFE, DEPTH_PROXY_WINDOW,
                      DECISION_DELAY_TICKS)
from .fills import execute_market, FillResult


def _depth_proxy_usd(prices: np.ndarray, i: int,
                     window: int = DEPTH_PROXY_WINDOW) -> float:
    """Rough top-of-book depth in USD using local vol × scale.
    Lower-vol stretches → thicker book. Multiplied by a constant so numbers
    are in the USD thousands, which keeps slippage realistic for 100 USD
    creatures making 5-100 USD trades."""
    if i < window + 1:
        return 5_000.0
    w = prices[i - window:i]
    m = float(w.mean()) or 1e-9
    stdrel = float(w.std()) / m
    # Thicker book when calm; 1%-vol pockets give ~5000 USD proxy.
    # Floor at 500 USD so simulation never becomes infinitely liquid.
    return max(500.0, 50.0 / max(stdrel, 1e-4))


@dataclass
class SimState:
    prices: np.ndarray
    tick: int = 0
    crowding: float = 0.0

    def advance(self) -> None:
        self.tick += 1
        # Exponential decay: half-life CROWDING_HALF_LIFE ticks
        decay = math.exp(-math.log(2.0) / max(1, CROWDING_HALF_LIFE))
        self.crowding *= decay

    @property
    def n_ticks(self) -> int:
        return int(len(self.prices))

    @property
    def mid(self) -> float:
        return float(self.prices[min(self.tick, self.n_ticks - 1)])

    def mid_at(self, t: int) -> float:
        t = max(0, min(t, self.n_ticks - 1))
        return float(self.prices[t])

    def depth_usd(self) -> float:
        return _depth_proxy_usd(self.prices, self.tick)

    def submit(self, side: int, requested_usd: float) -> FillResult | None:
        """
        Execute a market order decided at self.tick, filling at
        self.tick + DECISION_DELAY_TICKS. Returns None if no room left
        (filled at the very last tick).
        """
        fill_t = self.tick + DECISION_DELAY_TICKS
        if fill_t >= self.n_ticks:
            return None
        depth = self.depth_usd()
        fill_cap = depth  # can take at most "depth" USD at a time
        result = execute_market(
            decision_tick=self.tick,
            fill_tick_price=self.mid_at(fill_t),
            side=side,
            requested_usd=max(0.0, requested_usd),
            depth_usd=depth,
            fill_cap_usd=fill_cap,
            crowding=self.crowding,
        )
        # This creature's own trade contributes to next-tick crowding.
        # Normalize by depth so a 1x-depth trade adds 1 unit of crowding.
        self.crowding += result.filled_usd / max(depth, 1e-9)
        return result
