"""
Four orthogonal feature channels. Each creature reads ONE of each at
every tick. No two channels measure the same quantity — that is how we
kill the signal correlation trap at the feature layer.

  (A) momentum z-score         — trend channel
  (B) realized vol (rel stddev) — volatility channel
  (C) imbalance proxy          — microstructure (buy vs sell pressure)
  (D) depth decay              — liquidity / Z-axis pressure

None of these depend on the same moment of the price series in the same way:
(A) uses ratio of drift to spread, (B) uses dispersion, (C) uses sign-count
asymmetry, (D) uses how fast local range grows with window size (convexity
in the variogram).
"""
from __future__ import annotations
import numpy as np

from ..config import DEPTH_PROXY_WINDOW


def _safe_std(x: np.ndarray) -> float:
    s = float(x.std())
    return s if s > 1e-12 else 1e-12


def momentum_z(prices: np.ndarray, i: int, lookback: int) -> float:
    """(A) Standardized drift: signed, unit-less. ~N(0,1) under random walk."""
    lookback = int(max(2, min(lookback, i)))
    if i < lookback + 1:
        return 0.0
    w = prices[i - lookback:i + 1]
    logrets = np.diff(np.log(np.maximum(w, 1e-12)))
    return float(logrets.mean() / (_safe_std(logrets) / np.sqrt(len(logrets))))


def realized_vol(prices: np.ndarray, i: int, lookback: int = 50) -> float:
    """(B) Relative stddev of returns over lookback (dimensionless)."""
    lookback = int(max(2, min(lookback, i)))
    if i < lookback + 1:
        return 0.0
    w = prices[i - lookback:i + 1]
    r = np.diff(w) / np.maximum(w[:-1], 1e-12)
    return float(_safe_std(r))


def imbalance(prices: np.ndarray, i: int, lookback: int = 30) -> float:
    """(C) Fraction of up-ticks minus fraction of down-ticks over lookback.
    A proxy for book imbalance in absence of L2: more ups than downs = buy side
    winning the recent auction. Range [-1, 1]."""
    lookback = int(max(2, min(lookback, i)))
    if i < lookback + 1:
        return 0.0
    diffs = np.sign(np.diff(prices[i - lookback:i + 1]))
    up = float((diffs > 0).sum())
    dn = float((diffs < 0).sum())
    tot = up + dn
    return 0.0 if tot == 0 else (up - dn) / tot


def depth_decay(prices: np.ndarray, i: int,
                window: int = DEPTH_PROXY_WINDOW) -> float:
    """(D) How fast does range grow with sqrt(t)? RW gives ratio ≈ 1;
    crowded/illiquid pockets >1 (range grows faster → depth thin and brittle).
    Unit-less, orthogonal to all three above."""
    w_small = max(4, window // 4)
    if i < window + 1:
        return 1.0
    large = prices[i - window:i + 1]
    small = prices[i - w_small:i + 1]
    rng_large = float(large.max() - large.min())
    rng_small = float(small.max() - small.min())
    if rng_small <= 1e-12:
        return 1.0
    # Random walk: rng scales as sqrt(N). Ratio below expects 1.0 under RW.
    expected = np.sqrt(window / w_small)
    observed = rng_large / rng_small
    return float(observed / max(expected, 1e-9))


def snapshot(prices: np.ndarray, i: int,
             trend_lookback: int = 60) -> dict:
    """All four channels at once, for passing to decision logic."""
    return {
        "mom_z":        momentum_z(prices, i, trend_lookback),
        "vol":          realized_vol(prices, i, 50),
        "imbalance":    imbalance(prices, i, 30),
        "depth_decay":  depth_decay(prices, i),
    }
