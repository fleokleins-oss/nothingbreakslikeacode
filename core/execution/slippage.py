"""
Slippage model — concave in size, sensitive to crowding.

For a creature wanting `size_usd` at `price`, with an estimated local book
depth `depth_usd` and a reef-wide crowding factor `crowding` in [0, +inf),
the price impact is:

    impact_frac = SLIPPAGE_K * sqrt(size_usd / max(depth_usd, eps))
                               * (1 + crowding)

Square-root comes from standard market-impact literature (Almgren et al):
doubling size costs √2 more in impact, not 2x. The (1+crowding) term is
the reef's false-ecology guard — many creatures pushing the same side at
the same tick all pay more.
"""
from __future__ import annotations
import math

from ..config import SLIPPAGE_K

_EPS = 1e-9


def slippage_frac(size_usd: float, depth_usd: float,
                  crowding: float = 0.0,
                  k: float = SLIPPAGE_K) -> float:
    """Decimal price impact (e.g. 0.0012 = 12 bps). Always ≥ 0."""
    if size_usd <= 0 or depth_usd <= 0:
        return 0.0
    ratio = size_usd / max(depth_usd, _EPS)
    return k * math.sqrt(ratio) * (1.0 + max(0.0, crowding))


def effective_fill_price(mid_price: float, side: int,
                         size_usd: float, depth_usd: float,
                         crowding: float = 0.0) -> float:
    """
    side = +1 buy, -1 sell. Buyers pay UP (price * (1+slip)); sellers give UP.
    """
    slip = slippage_frac(size_usd, depth_usd, crowding)
    return mid_price * (1.0 + side * slip)
