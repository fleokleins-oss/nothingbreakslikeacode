"""
Regime classifier — uses the orthogonal features (not price moments) to label
a window. Keeps the classification dimensionally stable across symbols.

Regimes:
  trend       — |mom_z| > 2 AND depth_decay < 1.2 (clean drift)
  revert      — |mom_z| < 1 AND depth_decay < 1.0 (tight range)
  breakout    — vol > p75 AND depth_decay > 1.3 (fat-tailed burst)
  chop        — everything else (noise)
"""
from __future__ import annotations
from .features import momentum_z, realized_vol, depth_decay

REGIMES = ("trend", "revert", "breakout", "chop")


def classify(prices, i: int, trend_lookback: int = 100) -> str:
    mz = momentum_z(prices, i, trend_lookback)
    v  = realized_vol(prices, i, 50)
    dd = depth_decay(prices, i)

    # Rough per-dataset vol anchor: use recent window as p75 proxy
    import numpy as np
    vw = max(50, i - 500)
    recent = prices[max(0, i - 500):i + 1]
    if len(recent) >= 20:
        rets = np.abs(np.diff(recent) / np.maximum(recent[:-1], 1e-12))
        vhi = float(np.quantile(rets, 0.75))
    else:
        vhi = v

    if v >= vhi and dd > 1.3:
        return "breakout"
    if abs(mz) > 2.0 and dd < 1.2:
        return "trend"
    if abs(mz) < 1.0 and dd < 1.0:
        return "revert"
    return "chop"
