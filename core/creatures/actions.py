"""
Decision rules. Reads features (orthogonal channels) + genes + regime,
returns an integer direction or 0.

Entry rules are deliberately regime-dependent so creatures with regime_pref
have an edge exactly where they claim to, and no edge elsewhere. No signal
confluence shortcut — we require agreement between *different* channels
(momentum vs imbalance), never confluence of two momentum proxies.
"""
from __future__ import annotations
import math
from typing import Literal

Side = Literal[-1, 0, 1]


def entry_signal(features: dict, genes: dict, regime: str) -> Side:
    """
    Returns +1 (long), -1 (short), or 0 (no entry).
    """
    # Regime filter (categorical gene)
    pref = genes.get("regime_pref", "any")
    if pref != "any" and regime != pref:
        return 0

    vol = features["vol"]
    if vol < genes["vol_entry_min"] or vol > genes["vol_entry_max"]:
        return 0

    # Depth pressure abort — don't fight illiquid pockets
    if features["depth_decay"] > genes["depth_pressure_limit"] + 1.0:
        return 0

    mz  = features["mom_z"]
    imb = features["imbalance"]
    thr = genes.get("mean_revert_zscore_k", 2.0)

    direction: int = 0
    if regime in ("trend", "breakout"):
        if abs(mz) < 1.2:
            return 0
        direction = 1 if mz > 0 else -1
        # Require imbalance to agree with momentum (orthogonal confirmation).
        # Do NOT require imbalance magnitude — that would be redundant
        # with momentum magnitude; sign alignment is the orthogonal check.
        if (imb > 0 and direction < 0) or (imb < 0 and direction > 0):
            return 0
    elif regime == "revert":
        # Revert regime is *defined* by low |mz| (tight range) so we can't
        # use mz magnitude here — that would never fire. Instead we fade
        # imbalance extremes: buy-side exhaustion → go short, and vice versa.
        # Momentum must NOT strongly agree with imbalance (i.e. no fresh push).
        imb_thr = float(genes.get("imbalance_trigger", 0.2))
        if abs(imb) < imb_thr:
            return 0
        direction = -1 if imb > 0 else 1
        if (imb > 0 and mz > thr) or (imb < 0 and mz < -thr):
            return 0
    else:  # chop — normally skip, but allow when TWO orthogonal channels
           # agree strongly. mz (momentum t-stat) and imb (tick-sign auction)
           # are computed from different statistics; joint strong agreement
           # is genuine signal, not confluence-trap. This fills the "deserto
           # de chop" so selection has enough trades to sort good from bad.
        imb_strong = float(genes.get("imbalance_trigger", 0.2))
        if abs(mz) < 1.8 or abs(imb) < max(0.3, imb_strong):
            return 0
        # Both must point the same way (orthogonal confluence)
        if (mz > 0) != (imb > 0):
            return 0
        direction = 1 if mz > 0 else -1

    # Action-bias filter (categorical gene)
    ab = genes.get("action_bias", "both")
    if ab == "long_only" and direction < 0:
        return 0
    if ab == "short_only" and direction > 0:
        return 0
    return direction  # type: ignore[return-value]


def exit_signal(price_now: float, entry_price: float, side: int,
                ticks_in_position: int, genes: dict) -> str | None:
    """
    Return 'stop' | 'target' | 'timeout' | None.
    All thresholds in decimal of entry (dimensionally coherent).
    """
    move = (price_now - entry_price) / max(entry_price, 1e-9) * side
    if move <= -genes["stop_frac"]:
        return "stop"
    if move >= genes["target_frac"]:
        return "target"
    # Time stop: 5× trend_lookback, so a 60-tick momentum trader
    # has a 300-tick patience budget (relatively tight, prevents drift)
    max_hold = int(5 * genes.get("trend_lookback", 60))
    if ticks_in_position >= max_hold:
        return "timeout"
    return None


def kelly_capped_size(base_size_frac: float, win_rate: float,
                      avg_win: float, avg_loss: float,
                      cap: float) -> float:
    """
    Per-creature online Kelly estimate. Used at each entry to scale the
    genome's nominal size_frac by the EVIDENCE the creature itself has
    gathered. Early in life: no trades → default to min(base, cap/2).
    """
    if avg_win <= 0 or avg_loss <= 0:
        return min(base_size_frac, cap * 0.5)
    p = max(0.0, min(1.0, win_rate))
    f = (p * avg_win - (1.0 - p) * avg_loss) / avg_win
    f = max(0.0, min(cap, f))
    return min(base_size_frac, f) if f > 0 else 0.0
