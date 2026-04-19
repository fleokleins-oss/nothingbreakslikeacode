"""
Book surface — derives a 3D grid from a price series for visualization.

Grid axes:
  X = time (tick index)
  Y = price level relative to mid
  Z = estimated depth-proxy density (log), so "valleys" = illiquid bands

The surface is sampled sparsely for the viz (GRID_T × GRID_P). It is not
used by the trading logic — which derives depth inline from features.py —
so this is a view of the same substrate, not a second source of truth.
"""
from __future__ import annotations
import numpy as np

from ..config import DEPTH_PROXY_WINDOW


def build_surface(prices: np.ndarray,
                  grid_t: int = 60,
                  grid_p: int = 40,
                  levels_span_frac: float = 0.02) -> dict:
    """
    Return a dict with keys 't' (len grid_t), 'price_levels' (len grid_p),
    'Z' (grid_t × grid_p) density — higher = more liquidity.
    """
    n = len(prices)
    if n < DEPTH_PROXY_WINDOW + 10:
        empty = np.zeros((grid_t, grid_p))
        return {"t": np.linspace(0, n, grid_t),
                "price_levels": np.linspace(-levels_span_frac, levels_span_frac, grid_p),
                "mid_per_t": np.full(grid_t, float(prices.mean() if n else 0.0)),
                "Z": empty}

    tick_samples = np.linspace(DEPTH_PROXY_WINDOW, n - 1, grid_t).astype(int)
    levels = np.linspace(-levels_span_frac, levels_span_frac, grid_p)
    Z = np.zeros((grid_t, grid_p))
    mids = np.zeros(grid_t)

    for ti, t in enumerate(tick_samples):
        mid = float(prices[t])
        mids[ti] = mid
        w = prices[max(0, t - DEPTH_PROXY_WINDOW):t + 1]
        rel = (w - mid) / max(mid, 1e-9)
        # Density = histogram of recent relative prices across levels
        hist, _ = np.histogram(rel, bins=np.concatenate(
            [[levels[0] - 1e6], (levels[:-1] + levels[1:]) / 2, [levels[-1] + 1e6]]))
        # Log-compress so fat bins don't drown out tails
        Z[ti, :] = np.log1p(hist.astype(float))

    return {"t": tick_samples.astype(int),
            "price_levels": levels,
            "mid_per_t": mids,
            "Z": Z}
